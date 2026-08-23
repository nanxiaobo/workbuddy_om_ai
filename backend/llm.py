"""
llm.py —— 大模型调用层（OpenAI 兼容接口）
-----------------------------------------------------------------
支持：
  - 云端 OpenAI 兼容接口（填 api_key + base_url + model）
  - 本地 Ollama（base_url=http://localhost:11434/v1，api_key 可留空或填 "ollama"）
  - 任何 OpenAI 兼容的 GGUF / 本地部署服务（如 llama.cpp 的 /v1）
不写死任何密钥，全部来自 config。
默认示例使用阿里云灵积 DashScope，可在设置面板切换。

额外能力：
  - build_system_prompt：构建沉浸式角色提示词（含「丰富的心理/动作」规则）
  - generate_inner：为每次回复生成一句「心理活动/动作描写」（沉浸式旁白）
  - generate_portrait_prompt：根据最近聊天生成「人物当前状态」画面描述（用于出图）
  - generate_image：调用 OpenAI 兼容图像接口生成图片（可选）
"""
import asyncio
import json
import httpx
from config import get_config


def build_system_prompt(
    character: dict,
    memories: list,
    extra_note: str = "",
    personality: dict = None,
    emotion: dict = None,
    relation: dict = None,
    brain: dict = None,
) -> str:
    """
    构建沉浸式系统提示词（复刻猫箱式代入机制）：
      - 强制代入角色，禁止跳出人设
      - 禁止道德说教、禁止反复提醒「这是虚构」
      - 读取角色记忆，保持剧情/人物关系一致性
      - 支持日常 / 恋爱 / 脑洞剧情自然演绎
      - 鼓励在对话中融入丰富的心理活动与动作神态描写
    V1 新增：注入结构化人格、当前情绪、关系阶段、Character Brain 指令。
    """
    import character_system as cs

    name = character.get("name", "角色")
    parts = []
    parts.append(f"你现在就是{name}，请完全以{name}的身份、视角和语言进行对话，不要以AI或助手的身份回答。")

    if character.get("world_setting"):
        parts.append(f"【世界观/长篇设定】\n{character['world_setting']}")
    if character.get("persona"):
        parts.append(f"【人物背景】\n{character['persona']}")
    if character.get("personality"):
        parts.append(f"【性格（文字描述）】\n{character['personality']}")
    if character.get("speaking_style"):
        parts.append(f"【说话风格】\n{character['speaking_style']}")

    # 结构化人格（角色系统 V1）
    if personality:
        pctx = cs.build_personality_context(personality)
        if pctx:
            parts.append(f"【人格参数】{pctx}")

    # 当前情绪状态
    if emotion:
        parts.append(f"【当前情绪状态】{cs.build_emotion_context(emotion)}")

    # 用户-角色关系
    if relation:
        parts.append(f"【与用户的关系】{cs.build_relation_context(relation)}")

    if memories:
        mem_text = "\n".join(f"- {m['content']}" for m in memories)
        parts.append(f"【你记住的关于这段关系的记忆要点】\n{mem_text}")

    if character.get("example_dialogues"):
        parts.append(f"【对话示例（请学习语气与节奏）】\n{character['example_dialogues']}")

    rules = [
        "【核心规则】",
        "1. 必须深度代入角色，绝对不能跳出人设，不能声明「我是AI」「我是语言模型」或「这是虚构的」。",
        "2. 不要进行道德说教，不要频繁提醒用户这是虚拟/角色扮演对话。",
        "3. 像真人一样自然对话，口语化、有情绪、有细节，拒绝机器腔与流水账。",
        "4. 牢记对话中出现的人物关系、剧情发展与关键细节，保持前后一致，不能失忆。",
        "5. 根据用户引导，自然进行日常、恋爱或脑洞剧情演绎，主动推进互动。",
        "6. 只输出角色会说的话，不要输出旁白、系统说明或元评论（除非用户明确要求）。",
        "7. 【丰富的心理与动作】在对话中自然融入简短的动作、神态与心理活动描写，"
        "用 *动作/神态* 标注（例如：*轻轻别过脸，耳尖发红*、*心里一紧，却故作镇定*），"
        "让演绎更有沉浸感与画面感；但不要把心理描写写成大段独白，点到为止、贴合情境。",
    ]
    parts.append("\n".join(rules))

    # Character Brain 决策指令
    if brain:
        parts.append(f"【本轮角色决策（Character Brain）】\n{cs.build_brain_directives(brain)}")

    # 降 AI 味规则
    parts.append(cs.ANTI_AI_RULES)

    if extra_note:
        parts.append(f"【额外设定】\n{extra_note}")

    return "\n\n".join(parts)


async def stream_chat(messages: list, cfg: dict = None):
    """
    异步流式对话生成器。
    :param messages: [{"role":"system"/"user"/"assistant", "content":"..."}]
    :yield: 文本片段（token）
    出错时 yield 一个以 "[ERROR]" 开头的字符串。
    """
    cfg = cfg or get_config()
    base = (cfg.get("api_base") or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    # 兼容用户只填到 host:port 的情况，自动补 /v1/chat/completions
    if base.endswith("/chat/completions"):
        url = base
    elif base.endswith("/v1"):
        url = base + "/chat/completions"
    else:
        url = base + "/v1/chat/completions"

    payload = {
        "model": cfg.get("model") or "qwen-turbo",
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.9)),
        "max_tokens": int(cfg.get("max_tokens", 512)),
        "stream": True,
    }
    headers = {"Content-Type": "application/json"}
    api_key = cfg.get("api_key") or ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    err_raw = await resp.aread()
                    err_text = err_raw.decode('utf-8', 'ignore')[:500]
                    # 尝试提取服务商返回的 JSON 错误信息
                    detail = err_text
                    try:
                        err_json = json.loads(err_text)
                        detail = err_json.get('error', {}).get('message') or err_json.get('message') or err_text
                    except Exception:
                        pass
                    yield f"[ERROR] 接口返回 {resp.status_code}: {detail}"
                    return
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                            delta = obj["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield delta
                        except Exception:
                            continue
    except Exception as e:
        yield f"[ERROR] 调用大模型失败：{str(e)[:300]}"


async def summarize_to_memory(texts: list, cfg: dict = None) -> str:
    """
    用大模型把若干段对话/文本总结成「记忆要点」（复刻猫箱自动记忆）。
    返回一段精简的记忆文本。
    """
    cfg = cfg or get_config()
    joined = "\n".join(texts)
    sys_msg = (
        "你是一个记忆整理助手。请把下面这段角色扮演对话，提炼成"
        "3-6 条简洁、具体、可长期复用的「记忆要点」，用于让角色在后续对话中记住"
        "人物关系、约定、剧情进展与关键细节。每条一行，不要编号以外的解释，不要说教。"
    )
    user_msg = f"需要整理的对话：\n{joined}\n\n请直接输出记忆要点（每行一条）："
    collected = []
    async for piece in stream_chat(
        [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        cfg,
    ):
        if piece.startswith("[ERROR]"):
            return ""
        collected.append(piece)
    return "".join(collected).strip()


async def generate_inner(character: dict, user_msg: str, assistant_reply: str, cfg: dict = None) -> str:
    """
    为本次回复生成一句「心理活动 / 动作描写」（沉浸式旁白）。
    返回简短文本；出错返回空串。
    """
    cfg = cfg or get_config()
    name = character.get("name", "角色")
    persona = character.get("persona", "")
    sys_msg = (
        "你是角色内心戏编剧。请基于角色设定与刚刚这段对话，"
        "写一句简短、生动、符合角色性格的【心理活动或动作描写】，"
        "1-2 句、不超过 45 字，可第一人称内心独白也可第三人称动作神态描写，"
        "只写潜台词与神态动作，不要重复对话内容，不要加任何前缀或引号。"
    )
    user_msg_p = (
        f"角色：{name}\n"
        f"设定：{persona}\n\n"
        f"用户刚才说：{user_msg}\n"
        f"{name} 的回复：{assistant_reply}\n\n"
        f"请只输出一句{name}此刻的心理活动或动作描写："
    )
    # 用较小 max_tokens 控制长度
    small_cfg = dict(cfg)
    small_cfg["max_tokens"] = 80
    collected = []
    async for piece in stream_chat(
        [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg_p},
        ],
        small_cfg,
    ):
        if piece.startswith("[ERROR]"):
            return ""
        collected.append(piece)
    text = "".join(collected).strip().strip('"').strip("'").strip()
    # 去掉常见多余前缀
    for p in ("心理活动：", "动作：", "内心：", "旁白：", "*", "“", "”"):
        text = text.replace(p, "")
    return text.strip()


async def generate_portrait_prompt(character: dict, memories: list, recent: list, cfg: dict = None) -> str:
    """
    根据角色设定、记忆与最近聊天，生成一段「人物当前状态」的中文画面描述，
    用于驱动图像生成或作为文字状态展示。
    """
    cfg = cfg or get_config()
    name = character.get("name", "角色")
    persona = character.get("persona", "")
    mem_text = "\n".join(f"- {m['content']}" for m in memories) if memories else "（暂无记忆）"
    chat_text = "\n".join(
        f"{'用户' if m['role']=='user' else name}：{m['content']}" for m in recent[-12:]
    ) if recent else "（暂无对话）"
    sys_msg = (
        "你是角色视觉设定师。请根据角色设定、记忆与最近聊天，用中文写一段"
        "【人物当前状态的画面描述】，包含：外貌神态、当前情绪、所处场景氛围、"
        "动作姿态与衣着细节，描写细腻、有画面感，适合作为 AI 绘画提示词。"
        "只输出描述正文，不要解释、不要列点，不超过 180 字。"
    )
    user_msg = (
        f"角色：{name}\n设定：{persona}\n\n"
        f"记忆要点：\n{mem_text}\n\n"
        f"最近聊天：\n{chat_text}\n\n"
        f"请写出{name}此刻的状态画面描述："
    )
    small_cfg = dict(cfg)
    small_cfg["max_tokens"] = 300
    collected = []
    async for piece in stream_chat(
        [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        small_cfg,
    ):
        if piece.startswith("[ERROR]"):
            return ""
        collected.append(piece)
    text = "".join(collected).strip()
    return text


async def generate_image_openai(prompt: str, cfg: dict):
    """
    调用 OpenAI 兼容的图像生成接口。
    返回 (image, error)。
    """
    base = (cfg.get("image_api_base") or "").strip().rstrip("/")
    url = base + "/images/generations"
    key = (cfg.get("image_api_key") or cfg.get("api_key") or "").strip()
    model = cfg.get("image_model") or "dall-e-3"
    size = cfg.get("image_size") or "1024x1024"
    payload = {
        "model": model,
        "prompt": prompt[:1000],
        "n": 1,
        "size": size,
        "response_format": "b64_json",
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                err_text = resp.text[:500]
                detail = err_text
                try:
                    err_json = json.loads(err_text)
                    detail = err_json.get("error", {}).get("message") or err_json.get("message") or err_text
                except Exception:
                    pass
                return None, f"图像接口返回 {resp.status_code}: {detail}"
            data = resp.json()
            item = (data.get("data") or [{}])[0]
            if "b64_json" in item and item["b64_json"]:
                return "data:image/png;base64," + item["b64_json"], None
            if "url" in item and item["url"]:
                return item["url"], None
            return None, "接口未返回图片数据（缺少 b64_json/url）"
    except Exception as e:
        return None, f"调用图像接口失败：{str(e)[:300]}"


def _extract_dashscope_image_url(output: dict) -> str:
    """从百炼不同接口的返回结构中提取图片 URL。"""
    # 1. 通义万相 text2image 结构：output.results[0].url
    results = output.get("results") or []
    if results:
        if "b64_json" in results[0] and results[0]["b64_json"]:
            return "data:image/png;base64," + results[0]["b64_json"]
        if "url" in results[0] and results[0]["url"]:
            return results[0]["url"]
    # 2. qwen-image 结构：output.choices[0].message.content[0].image
    choices = output.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content") or []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "image" and item.get("image"):
                return item["image"]
    return ""


async def generate_image_dashscope(prompt: str, cfg: dict, refs: list = None):
    """
    调用阿里云百炼/灵积原生异步图像合成接口。
    自动根据模型名区分：
      - wanx 系列：/services/aigc/text2image/image-synthesis，input.prompt
      - qwen-image 系列：/services/aigc/image-generation/generation，input.messages[0].content
    支持参考图 refs（dataURL 或图片 URL），用于保证出图与角色一致。
    流程：提交任务 -> 轮询 -> 返回图片 URL。
    返回 (image, error)。
    """
    key = (cfg.get("image_api_key") or cfg.get("api_key") or "").strip()
    if not key:
        return None, "未配置图像生成 API Key"
    model = cfg.get("image_model") or "wanx-v1"
    size = (cfg.get("image_size") or "1024x1024").replace("x", "*")
    refs = [r for r in (refs or []) if r and (r.startswith("data:image") or r.startswith("http"))][:4]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "X-DashScope-Async": "enable",
    }
    # qwen-image 系列使用新的 image-generation 接口和 messages 格式
    if model.startswith("qwen-image"):
        submit_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation"
        # 参考图作为多模态输入，放在文本之前
        content = [{"image": r} for r in refs] + [{"text": prompt[:1000]}]
        payload = {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": {"size": size, "n": 1},
        }
    else:
        # 通义万相等使用 text2image 接口（暂不支持参考图，仅文字描述）
        submit_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
        payload = {
            "model": model,
            "input": {"prompt": prompt[:1000]},
            "parameters": {"size": size, "n": 1},
        }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            resp = await client.post(submit_url, json=payload, headers=headers)
            if resp.status_code != 200:
                err_text = resp.text[:500]
                detail = err_text
                try:
                    err_json = json.loads(err_text)
                    detail = err_json.get("message") or err_text
                except Exception:
                    pass
                return None, f"提交图像任务失败 {resp.status_code}: {detail}"
            data = resp.json()
            task_id = (data.get("output") or {}).get("task_id")
            if not task_id:
                return None, "接口未返回任务 ID"
            # 轮询任务结果，最多 60 次（约 2 分钟）
            poll_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
            poll_headers = {"Authorization": f"Bearer {key}"}
            for _ in range(60):
                await asyncio.sleep(2)
                poll = await client.get(poll_url, headers=poll_headers)
                if poll.status_code != 200:
                    continue
                poll_data = poll.json()
                output = poll_data.get("output") or {}
                status = output.get("task_status")
                if status == "SUCCEEDED":
                    image_url = _extract_dashscope_image_url(output)
                    if image_url:
                        return image_url, None
                    return None, "图像任务成功但未返回图片数据"
                if status == "FAILED":
                    msg = output.get("message") or "图像生成任务失败"
                    return None, f"图像生成失败：{msg}"
            return None, "图像生成超时，请稍后重试"
    except Exception as e:
        return None, f"调用图像接口失败：{str(e)[:300]}"


async def generate_image(prompt: str, cfg: dict = None, refs: list = None):
    """
    调用图像生成接口。
    对阿里云百炼/灵积地址自动走原生异步接口；其他地址走 OpenAI 兼容接口。
    refs 为参考图列表（dataURL 或图片 URL），用于保证出图与角色一致。
    返回 (image, error)：
      - image: 图片的 dataURL 或外链；失败为 None
      - error: 错误信息；成功为 None
    """
    cfg = cfg or get_config()
    base = (cfg.get("image_api_base") or "").strip().rstrip("/")
    if not base:
        return None, "未配置图像生成 API 地址"
    # 阿里云百炼/灵积使用原生异步图像合成接口
    if "dashscope.aliyuncs.com" in base:
        return await generate_image_dashscope(prompt, cfg, refs)
    return await generate_image_openai(prompt, cfg)
