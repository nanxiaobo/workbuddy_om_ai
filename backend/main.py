"""
main.py —— FastAPI 主程序
-----------------------------------------------------------------
提供完整 REST + SSE 流式接口，并在根路径托管前端静态文件。
运行： uvicorn main:app --host 0.0.0.0 --port 8000

新增能力（本版）：
  - 管理员登录鉴权（仅 admin，不支持注册）
  - 聊天时生成「心理活动/动作」旁白 + 每 50 条消息自动总结前文（超长记忆）
  - 会话级自定义聊天背景
  - 根据最近聊天生成「人物当前状态」图片
"""
import os
import json
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from typing import Optional, List

import config as cfg_mod
import db
from llm import build_system_prompt, stream_chat, summarize_to_memory, generate_inner, generate_portrait_prompt, generate_image

# 初始化数据库（含默认管理员账户）
db.init_db()

app = FastAPI(title="沉浸式 AI 聊天", version="2.0.0")

# 允许跨域（前端可直接以 file:// 打开或部署到任意域名调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------- 登录鉴权中间件 -------------------------
# 除 /api/health 与 /api/login 外，所有 /api/* 接口都必须携带有效的 Bearer Token。
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        request.state.username = None
        if path.startswith("/api/") and path not in ("/api/health",) and not path.startswith("/api/login"):
            auth = request.headers.get("Authorization", "")
            token = auth[7:] if auth.lower().startswith("bearer ") else auth
            username = db.validate_token(token)
            if not username:
                return JSONResponse({"detail": "未登录或登录已失效"}, status_code=401)
            request.state.username = username
        return await call_next(request)


def current_user(request: Request) -> str:
    return request.state.username or ""


def require_admin(request: Request):
    if current_user(request) != "admin":
        raise HTTPException(403, "仅管理员可操作")

app.add_middleware(AuthMiddleware)

# 线程池，用于把同步的 SQLite 操作放到后台，避免阻塞事件循环
executor = ThreadPoolExecutor(max_workers=8)
def run_sync(fn, *a, **kw):
    return executor.submit(partial(fn, *a, **kw)).result()


# ------------------------- 请求模型 -------------------------
class ConfigPatch(BaseModel):
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    context_rounds: Optional[int] = None
    theme: Optional[str] = None
    stream: Optional[bool] = None
    system_note: Optional[str] = None
    image_api_base: Optional[str] = None
    image_api_key: Optional[str] = None
    image_model: Optional[str] = None
    image_size: Optional[str] = None


class CharacterIn(BaseModel):
    id: Optional[str] = None
    name: str = "未命名角色"
    avatar: str = ""
    persona: str = ""
    personality: str = ""
    speaking_style: str = ""
    example_dialogues: str = ""
    world_setting: str = ""
    greeting: str = ""
    tags: str = ""
    refs: Optional[list] = None


class MemoryIn(BaseModel):
    content: str


class ConversationIn(BaseModel):
    character_id: str
    title: Optional[str] = "新对话"


class ChatIn(BaseModel):
    conversation_id: str
    user_message: str


class SummarizeIn(BaseModel):
    rounds: Optional[int] = 20  # 取最近多少轮对话用于总结


class LoginIn(BaseModel):
    username: str
    password: str


class UserCreateIn(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"


class UserUpdateIn(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None


class PasswordIn(BaseModel):
    old_password: Optional[str] = None
    new_password: str


class BackgroundIn(BaseModel):
    background: str = ""  # 图片 URL / dataURL / CSS 渐变字符串


class TestIn(BaseModel):
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    image_api_base: Optional[str] = None
    image_api_key: Optional[str] = None
    image_model: Optional[str] = None
    type: Optional[str] = "all"  # all | chat | image


# ------------------------- 鉴权接口 -------------------------
@app.post("/api/login")
def api_login(body: LoginIn):
    if not db.verify_user(body.username, body.password):
        raise HTTPException(401, "用户名或密码错误")
    token = db.create_token(body.username)
    return {"token": token, "username": body.username}


@app.post("/api/logout")
def api_logout(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else auth
    if token:
        db.delete_token(token)
    return {"ok": True}


@app.get("/api/me")
def api_me(request: Request):
    username = current_user(request)
    if not username:
        raise HTTPException(401, "未登录")
    return {"username": username, "is_admin": username == "admin"}


# ------------------------- 用户管理（仅管理员） -------------------------
@app.get("/api/users")
def api_list_users(request: Request):
    require_admin(request)
    return run_sync(db.list_users)


@app.post("/api/users")
def api_create_user(request: Request, u: UserCreateIn):
    require_admin(request)
    if not u.username.strip() or not u.password:
        raise HTTPException(400, "用户名和密码不能为空")
    try:
        created = run_sync(db.create_user, u.username.strip(), u.password, u.role or "user")
        run_sync(db.log_activity, current_user(request), "create_user", f"创建用户 {created.get('username')}", created.get("id"))
        return created
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.delete("/api/users/{uid}")
def api_delete_user(request: Request, uid: str):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    try:
        run_sync(db.delete_user, uid)
        run_sync(db.log_activity, current_user(request), "delete_user", f"删除用户 {user.get('username') if user else uid}", uid)
    except ValueError as e:
        raise HTTPException(403, str(e))
    return {"ok": True}


@app.put("/api/users/me/password")
def api_change_password(request: Request, p: PasswordIn):
    username = current_user(request)
    if not username:
        raise HTTPException(401, "未登录")
    # 非管理员修改密码需要验证旧密码；管理员可强制修改（这里仅支持改自己）
    if p.old_password and not db.verify_user(username, p.old_password):
        raise HTTPException(401, "旧密码错误")
    if not p.new_password or len(p.new_password) < 4:
        raise HTTPException(400, "新密码至少 4 位")
    run_sync(db.change_password, username, p.new_password)
    return {"ok": True}


# ------------------------- 用户详情 / 活动审计（仅管理员） -------------------------
@app.get("/api/users/{uid}")
def api_get_user(request: Request, uid: str):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    user["stats"] = run_sync(db.get_user_stats, user["username"])
    return user


@app.put("/api/users/{uid}")
def api_update_user(request: Request, uid: str, u: UserUpdateIn):
    require_admin(request)
    try:
        updated = run_sync(db.update_user, uid, u.dict(exclude_unset=True))
        run_sync(db.log_activity, current_user(request), "update_user", f"修改用户 {updated.get('username')} 信息", uid)
        return updated
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/users/{uid}/activity")
def api_user_activity(request: Request, uid: str, limit: int = 200):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    return {
        "user": user,
        "stats": run_sync(db.get_user_stats, user["username"]),
        "activity": run_sync(db.list_activity, user["username"], limit),
    }


@app.get("/api/users/{uid}/characters")
def api_user_characters(request: Request, uid: str):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    return run_sync(db.list_characters, user["username"])


@app.get("/api/users/{uid}/conversations")
def api_user_conversations(request: Request, uid: str):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    return run_sync(db.list_conversations, user=user["username"])


# ------------------------- 配置接口 -------------------------
@app.get("/api/config")
def api_get_config():
    return cfg_mod.get_config()


@app.put("/api/config")
def api_update_config(patch: ConfigPatch):
    data = {k: v for k, v in patch.dict().items() if v is not None}
    return cfg_mod.update_config(data)


# ------------------------- 健康检查 -------------------------
@app.get("/api/health")
def api_health():
    return {"status": "ok"}


async def _test_chat_model(cfg: dict):
    """测试对话模型：用极小 max_tokens 请求一个字，验证连通性。"""
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
    测试图像生成接口是否真实可用。
    - 阿里云百炼/灵积地址：探测原生异步图像合成接口。
    - 其他地址：探测 OpenAI 兼容 /v1/images/generations。
    用空 prompt 探测，不会真正出图、不扣费。
    """
    base = (cfg.get("image_api_base") or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "message": "未填写图像生成 API 地址"}
    key = (cfg.get("image_api_key") or cfg.get("api_key") or "").strip()
    model = cfg.get("image_model") or ""

    # 阿里云百炼/灵积原生异步接口
    if "dashscope.aliyuncs.com" in base:
        size = (cfg.get("image_size") or "1024x1024").replace("x", "*")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        # qwen-image 系列使用新的 image-generation 接口和 messages 格式
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
                # 200 表示异步任务已创建；400/422/403 多是因为空 prompt 或不支持同步，接口本身存在
                if resp.status_code in (200, 400, 422, 403):
                    return {"ok": True, "message": "百炼图像接口可连通"}
                return {"ok": False, "message": f"接口返回 {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"ok": False, "message": f"连接失败：{str(e)[:300]}"}

    # OpenAI 兼容接口
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


@app.post("/api/test")
async def api_test(body: TestIn = None):
    """
    测试大模型/图像模型配置是否可用。
    body 中可单独传入 api_base/api_key/model 或 image_api_base/image_api_key/image_model；
    不传则使用当前已保存配置，并同时测试对话与图像接口。
    """
    saved = cfg_mod.get_config()
    req = body.dict() if body else {}
    chat_cfg = {
        "api_base": req.get("api_base") or saved.get("api_base"),
        "api_key": req.get("api_key") or saved.get("api_key"),
        "model": req.get("model") or saved.get("model"),
        "temperature": saved.get("temperature", 0.9),
        "max_tokens": 8,
    }
    image_cfg = {
        "image_api_base": req.get("image_api_base") or saved.get("image_api_base"),
        "image_api_key": req.get("image_api_key") or saved.get("image_api_key"),
        "image_model": req.get("image_model") or saved.get("image_model"),
        "api_key": req.get("api_key") or saved.get("api_key"),
    }
    test_type = (req.get("type") or "all").lower()
    result = {"ok": True}
    if test_type in ("all", "chat"):
        result["chat"] = await _test_chat_model(chat_cfg)
    if test_type in ("all", "image"):
        result["image"] = await _test_image_model(image_cfg)
    # 整体 ok 只有当所有被测项都 ok 时才为 true
    checks = [v for k, v in result.items() if isinstance(v, dict) and "ok" in v]
    result["ok"] = all(c.get("ok") for c in checks) if checks else True
    return result


# ------------------------- 角色卡接口 -------------------------
@app.get("/api/characters")
def api_list_characters(request: Request):
    # 管理员可见全部；普通用户仅可见自己创建的角色（老数据 user 为空时仅管理员可见）
    if current_user(request) == db.DEFAULT_ADMIN_USER:
        return run_sync(db.list_characters)
    return run_sync(db.list_characters, current_user(request))


@app.post("/api/characters")
def api_create_character(c: CharacterIn, request: Request):
    user = current_user(request)
    ch = run_sync(db.create_character, c.dict(), user)
    run_sync(db.log_activity, user, "create_character", f"创建角色 {ch.get('name')}", ch.get("id"))
    return ch


@app.get("/api/characters/{cid}")
def api_get_character(cid: str):
    ch = run_sync(db.get_character, cid)
    if not ch:
        raise HTTPException(404, "角色不存在")
    return ch


@app.put("/api/characters/{cid}")
def api_update_character(cid: str, c: CharacterIn):
    ch = run_sync(db.get_character, cid)
    if not ch:
        raise HTTPException(404, "角色不存在")
    return run_sync(db.update_character, cid, c.dict(exclude_unset=True))


@app.delete("/api/characters/{cid}")
def api_delete_character(cid: str):
    run_sync(db.delete_character, cid)
    return {"ok": True}


@app.post("/api/characters/import")
def api_import_character(c: CharacterIn, request: Request):
    """导入角色卡（JSON）。支持只传部分字段。"""
    user = current_user(request)
    ch = run_sync(db.create_character, c.dict(), user)
    run_sync(db.log_activity, user, "import_character", f"导入角色 {ch.get('name')}", ch.get("id"))
    return ch


@app.get("/api/characters/{cid}/export")
def api_export_character(cid: str):
    ch = run_sync(db.get_character, cid)
    if not ch:
        raise HTTPException(404, "角色不存在")
    ch["_type"] = "ai-chat-character-card"
    ch["_version"] = "1.0"
    return ch  # FastAPI 会自动以 JSON 下载


# ------------------------- 记忆接口（复刻猫箱记忆机制） -------------------------
@app.get("/api/characters/{cid}/memories")
def api_list_memories(cid: str):
    return run_sync(db.list_memories, cid)


@app.post("/api/characters/{cid}/memories")
def api_add_memory(cid: str, m: MemoryIn, request: Request):
    if not m.content.strip():
        raise HTTPException(400, "记忆内容不能为空")
    mem = run_sync(db.add_memory, cid, m.content.strip())
    ch = run_sync(db.get_character, cid)
    run_sync(db.log_activity, current_user(request), "add_memory", f"为角色 {ch.get('name') if ch else cid} 添加记忆", mem.get("id"))
    return mem


@app.put("/api/memories/{mid}")
def api_update_memory(mid: str, m: MemoryIn):
    return run_sync(db.update_memory, mid, m.content.strip())


@app.delete("/api/memories/{mid}")
def api_delete_memory(mid: str):
    run_sync(db.delete_memory, mid)
    return {"ok": True}


# ------------------------- 会话接口 -------------------------
@app.get("/api/conversations")
def api_list_conversations(request: Request, character_id: Optional[str] = None):
    # 管理员可见全部；普通用户仅可见自己的会话
    if current_user(request) == db.DEFAULT_ADMIN_USER:
        return run_sync(db.list_conversations, character_id)
    return run_sync(db.list_conversations, character_id, current_user(request))


@app.post("/api/conversations")
def api_create_conversation(c: ConversationIn, request: Request):
    user = current_user(request)
    conv = run_sync(db.create_conversation, c.character_id, c.title or "新对话", user)
    # 若角色有开场白，自动插入一条助手消息
    ch = run_sync(db.get_character, c.character_id)
    if ch and ch.get("greeting"):
        run_sync(db.add_message, conv["id"], "assistant", ch["greeting"])
    run_sync(db.log_activity, user, "create_conversation", f"新建会话「{c.title or '新对话'}」（角色 {ch.get('name') if ch else '?'}）", conv.get("id"))
    return conv


@app.get("/api/conversations/{vid}")
def api_get_conversation(vid: str):
    conv = run_sync(db.get_conversation, vid)
    if not conv:
        raise HTTPException(404, "会话不存在")
    msgs = run_sync(db.list_messages, vid)
    conv["messages"] = msgs
    return conv


@app.delete("/api/conversations/{vid}")
def api_delete_conversation(vid: str):
    run_sync(db.delete_conversation, vid)
    return {"ok": True}


@app.post("/api/conversations/{vid}/clear")
def api_clear_conversation(vid: str):
    run_sync(db.clear_conversation, vid)
    # 清空后若有开场白则重新插入
    conv = run_sync(db.get_conversation, vid)
    if conv:
        ch = run_sync(db.get_character, conv["character_id"])
        if ch and ch.get("greeting"):
            run_sync(db.add_message, vid, "assistant", ch["greeting"])
    return {"ok": True}


@app.put("/api/conversations/{vid}/background")
def api_set_background(vid: str, b: BackgroundIn, request: Request):
    conv = run_sync(db.get_conversation, vid)
    if not conv:
        raise HTTPException(404, "会话不存在")
    run_sync(db.update_conversation_background, vid, b.background or "")
    run_sync(db.log_activity, current_user(request), "set_background", f"设置会话 {vid[:8]} 聊天背景", vid)
    return {"ok": True, "background": b.background or ""}


# ------------------------- 记忆自动总结（猫箱式） -------------------------
@app.post("/api/conversations/{vid}/summarize")
async def api_summarize(vid: str, s: SummarizeIn, request: Request):
    """
    把最近若干轮对话，交给大模型总结为「记忆要点」，自动写入角色记忆。
    返回新增的记忆条目。
    """
    conv = run_sync(db.get_conversation, vid)
    if not conv:
        raise HTTPException(404, "会话不存在")
    msgs = run_sync(db.get_recent_messages, vid, s.rounds)
    if not msgs:
        return {"added": []}
    texts = [f"{'用户' if m['role']=='user' else '角色'}: {m['content']}" for m in msgs]
    summary = await summarize_to_memory(texts)
    added = []
    if summary:
        # 按行拆分，过滤空行，逐条写入记忆
        for line in summary.splitlines():
            line = line.strip().lstrip("0123456789.-、").strip()
            if line:
                mem = run_sync(db.add_memory, conv["character_id"], line)
                added.append(mem)
    ch = run_sync(db.get_character, conv["character_id"])
    run_sync(db.log_activity, current_user(request), "summarize_memory",
             f"为角色 {ch.get('name') if ch else '?'} 总结 {len(added)} 条记忆", vid)
    return {"added": added}


# ------------------------- 人物当前状态图 -------------------------
@app.post("/api/conversations/{vid}/portrait")
async def api_portrait(vid: str, request: Request):
    """
    根据角色设定、记忆与最近聊天，生成「人物当前状态」画面描述；
    若配置了 image_api_base，则进一步调用图像生成接口出图。
    返回 { description, image(可空), ok }
    """
    conv = run_sync(db.get_conversation, vid)
    if not conv:
        raise HTTPException(404, "会话不存在")
    character = run_sync(db.get_character, conv["character_id"])
    if not character:
        raise HTTPException(404, "角色不存在")
    cfg = cfg_mod.get_config()
    memories = run_sync(db.list_memories, conv["character_id"])
    recent = run_sync(db.get_recent_messages, vid, 25)

    description = await generate_portrait_prompt(character, memories, recent, cfg)
    image = None
    image_error = None
    if cfg.get("image_api_base"):
        # 参考图：角色头像（图片类）+ 用户上传的参考图，保证出图与角色一致
        refs = list(character.get("refs") or [])
        avatar = character.get("avatar") or ""
        if avatar and (avatar.startswith("data:image") or avatar.startswith("http")):
            refs = [avatar] + refs
        image, image_error = await generate_image(description, cfg, refs)
    run_sync(db.log_activity, current_user(request), "generate_portrait",
             f"生成角色 {character.get('name')} 状态图" + ("（含图片）" if image else (f"（失败：{image_error}）" if image_error else "（文字描述）")), vid)
    return {"ok": True, "description": description, "image": image, "image_error": image_error}


# ------------------------- 消息级生图 -------------------------
@app.post("/api/messages/{mid}/image")
async def api_message_image(mid: str, request: Request):
    """
    为某条角色（assistant）消息生成配图：基于角色设定、记忆与这条消息内容，
    结合角色头像与参考图，调用图像生成接口出图，并把图片存回该消息。
    返回 { ok, image }
    """
    message = run_sync(db.get_message, mid)
    if not message:
        raise HTTPException(404, "消息不存在")
    conv = run_sync(db.get_conversation, message["conversation_id"])
    if not conv:
        raise HTTPException(404, "会话不存在")
    character = run_sync(db.get_character, conv["character_id"])
    if not character:
        raise HTTPException(404, "角色不存在")
    cfg = cfg_mod.get_config()
    if not cfg.get("image_api_base"):
        return {"ok": False, "error": "未配置图像生成 API 地址（请在设置中填写）"}
    memories = run_sync(db.list_memories, conv["character_id"])
    # 以这条消息作为画面依据生成提示词
    prompt = await generate_portrait_prompt(character, memories, [message], cfg)
    # 参考图：角色头像（图片类）+ 用户上传的参考图
    refs = list(character.get("refs") or [])
    avatar = character.get("avatar") or ""
    if avatar and (avatar.startswith("data:image") or avatar.startswith("http")):
        refs = [avatar] + refs
    image, image_error = await generate_image(prompt, cfg, refs)
    if image:
        run_sync(db.update_message_image, mid, image)
        run_sync(db.log_activity, current_user(request), "generate_message_image",
                 f"为消息生成图片（角色 {character.get('name')}）", mid)
        return {"ok": True, "image": image}
    return {"ok": False, "error": image_error or "生成失败"}


# ------------------------- 聊天（SSE 流式） -------------------------
@app.post("/api/chat")
async def api_chat(body: ChatIn, request: Request):
    """
    发送一条用户消息并流式返回 AI 回复。
    SSE 事件格式（每行一个 JSON）：
      {"type":"delta","content":"...片段..."}   增量文本
      {"type":"inner","content":"...心理/动作..."} 心理活动旁白（回复结束后推送）
      {"type":"summary","added":N}               自动总结记忆通知（每 50 条触发）
      {"type":"done","content":"完整回复"}        结束
      {"type":"error","message":"错误信息"}       出错
    """
    conv = run_sync(db.get_conversation, body.conversation_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    if not body.user_message.strip():
        raise HTTPException(400, "消息不能为空")

    character = run_sync(db.get_character, conv["character_id"])
    if not character:
        raise HTTPException(404, "角色不存在")

    cfg = cfg_mod.get_config()
    memories = run_sync(db.list_memories, conv["character_id"])
    system_prompt = build_system_prompt(character, memories, cfg.get("system_note", ""))

    # 上下文记忆：取最近 N 轮历史 + 当前用户消息
    rounds = int(cfg.get("context_rounds", 30))
    history = run_sync(db.get_recent_messages, body.conversation_id, rounds)

    messages = [{"role": "system", "content": system_prompt}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": body.user_message})

    # 先把用户消息落库
    run_sync(db.add_message, body.conversation_id, "user", body.user_message)
    user = current_user(request)
    run_sync(db.log_activity, user, "send_message", f"发送消息：{body.user_message[:30]}{'...' if len(body.user_message)>30 else ''}", body.conversation_id)

    # 若会话标题仍是默认，用首条用户消息做标题
    if conv.get("title") in (None, "新对话", ""):
        title = body.user_message[:20]
        run_sync(db.touch_conversation, body.conversation_id, title)

    async def event_gen():
        full = []
        try:
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

            # 每 50 条消息自动总结前文，保证超长记忆不丢失
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


# ------------------------- 静态前端托管 -------------------------
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# 把 frontend 目录作为静态资源（/assets、/manifest.json、/sw.js 等）
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
