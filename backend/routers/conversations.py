"""
routers/conversations.py —— 会话 CRUD + 背景 / 总结 / 状态图
"""
from fastapi import APIRouter, HTTPException, Request
from typing import Optional

from core.models import BackgroundIn, ConversationIn, SummarizeIn
from core.security import current_user, is_admin, run_sync
from llm import summarize_to_memory
import config as cfg_mod
import db

router = APIRouter()


@router.get("/api/conversations")
def api_list_conversations(request: Request, character_id: Optional[str] = None):
    """管理员可见全部；普通用户仅可见自己的会话。"""
    if is_admin(request):
        return run_sync(db.list_conversations, character_id)
    return run_sync(db.list_conversations, character_id, current_user(request))


@router.post("/api/conversations")
def api_create_conversation(c: ConversationIn, request: Request):
    user = current_user(request)
    conv = run_sync(db.create_conversation, c.character_id, c.title or "新对话", user)
    # 若角色有开场白，自动插入一条助手消息
    ch = run_sync(db.get_character, c.character_id)
    if ch and ch.get("greeting"):
        run_sync(db.add_message, conv["id"], "assistant", ch["greeting"])
    run_sync(db.log_activity, user, "create_conversation",
             f"新建会话「{c.title or '新对话'}」（角色 {ch.get('name') if ch else '?'}）", conv.get("id"))
    return conv


@router.get("/api/conversations/{vid}")
def api_get_conversation(vid: str):
    conv = run_sync(db.get_conversation, vid)
    if not conv:
        raise HTTPException(404, "会话不存在")
    msgs = run_sync(db.list_messages, vid)
    conv["messages"] = msgs
    return conv


@router.delete("/api/conversations/{vid}")
def api_delete_conversation(vid: str):
    run_sync(db.delete_conversation, vid)
    return {"ok": True}


@router.post("/api/conversations/{vid}/clear")
def api_clear_conversation(vid: str):
    """清空上下文：删除所有消息并重新插入开场白。"""
    run_sync(db.clear_conversation, vid)
    conv = run_sync(db.get_conversation, vid)
    if conv:
        ch = run_sync(db.get_character, conv["character_id"])
        if ch and ch.get("greeting"):
            run_sync(db.add_message, vid, "assistant", ch["greeting"])
    return {"ok": True}


@router.put("/api/conversations/{vid}/background")
def api_set_background(vid: str, b: BackgroundIn, request: Request):
    """设置会话级聊天背景。"""
    conv = run_sync(db.get_conversation, vid)
    if not conv:
        raise HTTPException(404, "会话不存在")
    run_sync(db.update_conversation_background, vid, b.background or "")
    run_sync(db.log_activity, current_user(request), "set_background",
             f"设置会话 {vid[:8]} 聊天背景", vid)
    return {"ok": True, "background": b.background or ""}


@router.post("/api/conversations/{vid}/summarize")
async def api_summarize(vid: str, s: SummarizeIn, request: Request):
    """把最近若干轮对话交给 LLM 总结为记忆要点，自动写入角色记忆。"""
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
        for line in summary.splitlines():
            line = line.strip().lstrip("0123456789.-、").strip()
            if line:
                mem = run_sync(db.add_memory, conv["character_id"], line)
                added.append(mem)
    ch = run_sync(db.get_character, conv["character_id"])
    run_sync(db.log_activity, current_user(request), "summarize_memory",
             f"为角色 {ch.get('name') if ch else '?'} 总结 {len(added)} 条记忆", vid)
    return {"added": added}
