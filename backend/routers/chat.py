"""
routers/chat.py —— 聊天 SSE 流式 + 配置测试
包含 /api/chat（SSE 流式回复）+ /api/test（连通性测试）。
V1：集成角色系统（人格 / 情绪 / 关系 / Character Brain）。
"""
import json

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.models import ChatIn, TestIn
from core.security import current_user, is_admin, run_sync
from llm import build_system_prompt, generate_inner, stream_chat, summarize_to_memory
import character_system as cs
import config as cfg_mod
import db

router = APIRouter()


# ------------------------- 聊天 SSE 流式 -------------------------
@router.post("/api/chat")
async def api_chat(body: ChatIn, request: Request):
    """
    发送一条用户消息并流式返回 AI 回复。
    SSE 事件格式（每行一个 JSON）：
      {"type":"delta","content":"片段"}      增量文本
      {"type":"inner","content":"心理活动"}   心理活动旁白（回复结束后推送）
      {"type":"brain","emotion":"...","attitude":"...","stage":"..."}  角色决策（回复前推送）
      {"type":"summary","added":N}            自动总结记忆通知（每 50 条触发）
      {"type":"done","content":"完整回复"}     结束
      {"type":"error","message":"错误"}        出错
    """
    conv = run_sync(db.get_conversation, body.conversation_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    if not body.user_message.strip():
        raise HTTPException(400, "消息不能为空")

    character = run_sync(db.get_character, conv["character_id"])
    if not character:
        raise HTTPException(404, "角色不存在")

    user = current_user(request)
    cfg = cfg_mod.get_effective_config(user)

    # ===== 角色系统 V1：加载人格 / 情绪 / 关系 =====
    personality = cs.parse_personality(character.get("personality_json"))
    emotion = cs.parse_emotion(character.get("emotion_json"))
    rel_row = run_sync(db.get_relation, user, conv["character_id"])
    relation = cs.parse_relation(rel_row["relation_json"]) if rel_row else dict(cs.DEFAULT_RELATION)

    # Character Brain：纯代码决策（不调 LLM）
    signals = cs.analyze_message(body.user_message)
    brain = cs.character_brain(character, personality, emotion, relation, body.user_message)

    memories = run_sync(db.list_memories, conv["character_id"])
    system_prompt = build_system_prompt(
        character, memories, cfg.get("system_note", ""),
        personality=personality, emotion=emotion, relation=relation, brain=brain,
    )

    # 上下文记忆：取最近 N 轮历史 + 当前用户消息
    rounds = int(cfg.get("context_rounds", 30))
    history = run_sync(db.get_recent_messages, body.conversation_id, rounds)

    messages = [{"role": "system", "content": system_prompt}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": body.user_message})

    # 先把用户消息落库
    run_sync(db.add_message, body.conversation_id, "user", body.user_message)
    run_sync(db.log_activity, user, "send_message",
             f"发送消息：{body.user_message[:30]}{'...' if len(body.user_message)>30 else ''}", body.conversation_id)

    # ===== 角色系统 V1：先更新情绪 + 关系（基于用户消息，不依赖 LLM 是否成功） =====
    try:
        new_emotion = cs.update_emotion(emotion, personality, signals, brain)
        new_relation = cs.update_relation(relation, new_emotion, signals, brain)
        run_sync(db.set_character_emotion, conv["character_id"], cs.emotion_to_json(new_emotion))
        run_sync(db.upsert_relation, user, conv["character_id"],
                 cs.relation_to_json(new_relation), new_relation.get("stage", 0))
    except Exception:
        pass

    # 若会话标题仍是默认，用首条用户消息做标题
    if conv.get("title") in (None, "新对话", ""):
        title = body.user_message[:20]
        run_sync(db.touch_conversation, body.conversation_id, title)

    # SSE 事件生成器
    async def event_gen():
        full = []
        try:
            # 先推送 Character Brain 决策（让前端实时显示角色状态）
            yield f"data: {json.dumps({'type':'brain', 'emotion': brain['emotion_label'], 'attitude': brain['attitude'], 'intent': brain['intent'], 'style': brain['style'], 'stage': cs.stage_name(new_relation.get('stage', 0))}, ensure_ascii=False)}\n\n"

            async for piece in stream_chat(messages, cfg):
                if piece.startswith("[ERROR]"):
                    yield f"data: {json.dumps({'type':'error','message': piece[len('[ERROR]'):]}, ensure_ascii=False)}\n\n"
                    return
                full.append(piece)
                yield f"data: {json.dumps({'type':'delta','content': piece}, ensure_ascii=False)}\n\n"
            complete = "".join(full)
            # 落库助手回复
            run_sync(db.add_message, body.conversation_id, "assistant", complete)
            run_sync(db.touch_conversation, body.conversation_id)
            yield f"data: {json.dumps({'type':'done','content': complete}, ensure_ascii=False)}\n\n"

            # 心理活动 / 动作描写（沉浸式旁白）
            try:
                inner = await generate_inner(character, body.user_message, complete, cfg)
                if inner:
                    yield f"data: {json.dumps({'type':'inner','content': inner}, ensure_ascii=False)}\n\n"
            except Exception:
                pass

            # 每 50 条消息自动总结前文
            try:
                cnt = run_sync(db.count_messages, body.conversation_id)
                if cnt > 0 and cnt % 50 == 0:
                    recent = run_sync(db.get_recent_messages, body.conversation_id, 50)
                    texts = [f"{'用户' if m['role']=='user' else '角色'}: {m['content']}" for m in recent]
                    summary = await summarize_to_memory(texts)
                    added = 0
                    if summary:
                        for line in summary.splitlines():
                            line = line.strip().lstrip("0123456789.-、").strip()
                            if line:
                                run_sync(db.add_memory, conv["character_id"], line)
                                added += 1
                    yield f"data: {json.dumps({'type':'summary','added': added}, ensure_ascii=False)}\n\n"
            except Exception:
                pass

        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------- 配置测试（chat / image） -------------------------
async def _test_chat_model(cfg: dict):
    """用极小 max_tokens 请求一个字，验证对话模型连通性。"""
    test_cfg = dict(cfg)
    test_cfg["max_tokens"] = 8
    chunks = []
    try:
        async for piece in stream_chat(
            [
                {"role": "system", "content": "你是测试助手。"},
                {"role": "user", "content": "请只回复一个字：好"},
            ],
            test_cfg,
        ):
            if piece.startswith("[ERROR]"):
                return {"ok": False, "message": piece[len("[ERROR]"):]}
            chunks.append(piece)
        if chunks:
            return {"ok": True, "sample": "".join(chunks)[:50]}
        return {"ok": False, "message": "未收到任何返回，请检查模型名称与接口地址"}
    except Exception as e:
        return {"ok": False, "message": str(e)[:300]}


async def _test_image_model(cfg: dict):
    """
    测试图像生成接口是否真实可用（不真正出图、不扣费）。
    - 阿里云百炼/灵积地址：探测原生异步图像合成接口。
    - 其他地址：探测 OpenAI 兼容 /v1/images/generations。
    """
    base = (cfg.get("image_api_base") or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "message": "未填写图像生成 API 地址"}
    key = (cfg.get("image_api_key") or cfg.get("api_key") or "").strip()
    model = cfg.get("image_model") or ""

    if "dashscope.aliyuncs.com" in base:
        size = (cfg.get("image_size") or "1024x1024").replace("x", "*")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        if model.startswith("qwen-image"):
            url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation"
            probe_payload = {
                "model": model or "qwen-image-3.0",
                "input": {"messages": [{"role": "user", "content": [{"text": ""}]}]},
                "parameters": {"size": size, "n": 1},
            }
        else:
            url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
            probe_payload = {"model": model or "wanx-v1", "input": {"prompt": ""}, "parameters": {"size": size, "n": 1}}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                resp = await client.post(url, json=probe_payload, headers=headers)
                if resp.status_code == 401:
                    return {"ok": False, "message": "API Key 无效或未经授权"}
                if resp.status_code == 404:
                    return {"ok": False, "message": "该地址不是百炼图像合成接口"}
                if resp.status_code in (200, 400, 422, 403):
                    return {"ok": True, "message": "百炼图像接口可连通"}
                return {"ok": False, "message": f"接口返回 {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"ok": False, "message": f"连接失败：{str(e)[:300]}"}

    url = base + "/images/generations"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    headers["Content-Type"] = "application/json"
    probe_payload = {"model": model or "dall-e-3", "prompt": "", "n": 1, "size": "1024x1024"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            resp = await client.post(url, json=probe_payload, headers=headers)
            if resp.status_code == 404:
                return {"ok": False, "message": "该地址不支持 /v1/images/generations，请更换为 OpenAI 兼容的图像生成接口"}
            if resp.status_code == 401:
                return {"ok": False, "message": "API Key 无效或未经授权"}
            if resp.status_code == 200:
                return {"ok": True, "message": "图像接口可连通且支持出图"}
            if resp.status_code in (400, 422):
                return {"ok": True, "message": "图像接口可连通（探测返回参数错误，实际生成可正常使用）"}
            return {"ok": False, "message": f"接口返回 {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "message": f"连接失败：{str(e)[:300]}"}


@router.post("/api/test")
async def api_test(body: TestIn, request: Request):
    """
    测试大模型 / 图像模型配置是否可用。
    body 中可单独传入 api_base/api_key/model 或 image_api_base/image_api_key/image_model；
    不传则使用当前已保存配置。
    非管理员请求中若携带 api_key/image_api_key，会被忽略（防止探测他人密钥）。
    """
    saved = cfg_mod.get_effective_config(current_user(request))
    req = body.dict() if body else {}
    if not is_admin(request):
        for k in ("api_key", "image_api_key"):
            if req.get(k):
                req[k] = None
    chat_cfg = {
        "api_base": req.get("api_base") or saved.get("api_base"),
        "api_key": req.get("api_key") or saved.get("api_key"),
        "model": req.get("model") or saved.get("model"),
        "temperature": saved.get("temperature", 0.9),
        "max_tokens": 8,
    }
    image_cfg = {
        "image_api_base": req.get("image_api_base") or saved.get("image_api_base"),
        "image_api_key": req.get("image_api_key") or saved.get("image_key") or saved.get("api_key"),
        "image_model": req.get("image_model") or saved.get("image_model"),
        "api_key": saved.get("api_key"),
    }
    test_type = (req.get("type") or "all").lower()
    result = {"ok": True}
    if test_type in ("all", "chat"):
        result["chat"] = await _test_chat_model(chat_cfg)
    if test_type in ("all", "image"):
        result["image"] = await _test_image_model(image_cfg)
    checks = [v for k, v in result.items() if isinstance(v, dict) and "ok" in v]
    result["ok"] = all(c.get("ok") for c in checks) if checks else True
    return result
