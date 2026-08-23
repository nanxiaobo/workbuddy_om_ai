"""
routers/memories.py —— 角色记忆（猫箱式：每条手动要点 / 总结要点）
记忆本身挂在 character 上，接口路径以 character_id 与 memory_id 双形态。
"""
from fastapi import APIRouter, HTTPException, Request

from core.models import MemoryIn
from core.security import current_user, run_sync
import db

router = APIRouter()


@router.get("/api/characters/{cid}/memories")
def api_list_memories(cid: str):
    return run_sync(db.list_memories, cid)


@router.post("/api/characters/{cid}/memories")
def api_add_memory(cid: str, m: MemoryIn, request: Request):
    if not m.content.strip():
        raise HTTPException(400, "记忆内容不能为空")
    mem = run_sync(db.add_memory, cid, m.content.strip())
    ch = run_sync(db.get_character, cid)
    run_sync(db.log_activity, current_user(request), "add_memory",
             f"为角色 {ch.get('name') if ch else cid} 添加记忆", mem.get("id"))
    return mem


@router.put("/api/memories/{mid}")
def api_update_memory(mid: str, m: MemoryIn):
    return run_sync(db.update_memory, mid, m.content.strip())


@router.delete("/api/memories/{mid}")
def api_delete_memory(mid: str):
    run_sync(db.delete_memory, mid)
    return {"ok": True}
