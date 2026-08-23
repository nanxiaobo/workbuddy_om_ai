"""
routers/auth.py —— 鉴权与会话：登录 / 登出 / 当前用户 / 心跳 / 健康检查
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from core.security import current_user, run_sync
import db

router = APIRouter()


@router.post("/api/login")
def api_login(body: dict):
    """登录。body: {username, password}。返回 {token, username}。"""
    if not db.verify_user(body.get("username", ""), body.get("password", "")):
        raise HTTPException(401, "用户名或密码错误")
    token = db.create_token(body["username"])
    return {"token": token, "username": body["username"]}


@router.post("/api/logout")
def api_logout(request: Request):
    """登出：删除当前 token。"""
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else auth
    if token:
        db.delete_token(token)
    return {"ok": True}


@router.get("/api/me")
def api_me(request: Request):
    """当前登录用户信息。"""
    username = current_user(request)
    if not username:
        raise HTTPException(401, "未登录")
    return {"username": username, "is_admin": username == db.DEFAULT_ADMIN_USER}


@router.get("/api/ping")
def api_ping(request: Request):
    """心跳：续期 token（实际续期在 AuthMiddleware.validate_token 已完成；这里再调一次 extend_token 双保险）。"""
    username = current_user(request)
    if not username:
        raise HTTPException(401, "未登录")
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else auth
    db.extend_token(token)
    return {"ok": True, "username": username, "ts": int(datetime.now(timezone.utc).timestamp())}


@router.get("/api/health")
def api_health():
    """健康检查（无需鉴权）。"""
    return {"status": "ok"}
