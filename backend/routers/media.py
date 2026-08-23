"""
routers/media.py —— 多媒体生成：人物状态图 + 消息级生图
"""
from fastapi import APIRouter, HTTPException, Request

from core.security import current_user, run_sync
from llm import generate_image, generate_portrait_prompt
import config as cfg_mod
import db

router = APIRouter()


@router.post("/api/conversations/{vid}/portrait")
async def api_portrait(vid: str, request: Request):
    """
    根据角色设定、记忆与最近聊天，生成「人物当前状态」画面描述；
    若配置了 image_api_base，则进一步调用图像生成接口出图。
    返回 { ok, description, image(可空), image_error(可空) }
    """
    conv = run_sync(db.get_conversation, vid)
    if not conv:
        raise HTTPException(404, "会话不存在")
    character = run_sync(db.get_character, conv["character_id"])
    if not character:
        raise HTTPException(404, "角色不存在")
    cfg = cfg_mod.get_effective_config(current_user(request))
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
             f"生成角色 {character.get('name')} 状态图"
             + ("（含图片）" if image else (f"（失败：{image_error}）" if image_error else "（文字描述）")),
             vid)
    return {"ok": True, "description": description, "image": image, "image_error": image_error}


@router.post("/api/messages/{mid}/image")
async def api_message_image(mid: str, request: Request):
    """
    为某条角色（assistant）消息生成配图：基于角色设定、记忆与这条消息内容，
    结合角色头像与参考图，调用图像生成接口出图，并把图片存回该消息。
    返回 { ok, image } 或 { ok:false, error }
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
    cfg = cfg_mod.get_effective_config(current_user(request))
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
