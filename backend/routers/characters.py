"""
routers/characters.py —— 角色卡 CRUD + 导入 / 导出
"""
from fastapi import APIRouter, HTTPException, Request

from core.models import CharacterIn
from core.security import current_user, is_admin, run_sync
import db

router = APIRouter()


@router.get("/api/characters")
def api_list_characters(request: Request):
    """管理员可见全部；普通用户仅可见自己创建的角色（老数据 user 为空时仅管理员可见）。"""
    if is_admin(request):
        return run_sync(db.list_characters)
    return run_sync(db.list_characters, current_user(request))


@router.post("/api/characters")
def api_create_character(c: CharacterIn, request: Request):
    user = current_user(request)
    ch = run_sync(db.create_character, c.dict(), user)
    run_sync(db.log_activity, user, "create_character", f"创建角色 {ch.get('name')}", ch.get("id"))
    return ch


@router.post("/api/characters/import")
def api_import_character(c: CharacterIn, request: Request):
    """导入角色卡（JSON）。支持只传部分字段。"""
    user = current_user(request)
    ch = run_sync(db.create_character, c.dict(), user)
    run_sync(db.log_activity, user, "import_character", f"导入角色 {ch.get('name')}", ch.get("id"))
    return ch


@router.get("/api/characters/{cid}")
def api_get_character(cid: str):
    ch = run_sync(db.get_character, cid)
    if not ch:
        raise HTTPException(404, "角色不存在")
    return ch


@router.put("/api/characters/{cid}")
def api_update_character(cid: str, c: CharacterIn):
    ch = run_sync(db.get_character, cid)
    if not ch:
        raise HTTPException(404, "角色不存在")
    return run_sync(db.update_character, cid, c.dict(exclude_unset=True))


@router.delete("/api/characters/{cid}")
def api_delete_character(cid: str):
    run_sync(db.delete_character, cid)
    return {"ok": True}


@router.get("/api/characters/{cid}/export")
def api_export_character(cid: str):
    """导出角色卡 JSON（前端下载）。"""
    ch = run_sync(db.get_character, cid)
    if not ch:
        raise HTTPException(404, "角色不存在")
    ch["_type"] = "ai-chat-character-card"
    ch["_version"] = "1.0"
    return ch
