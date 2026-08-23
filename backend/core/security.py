"""
core/security.py —— 鉴权 / 跨业务公共工具
-----------------------------------------------------------------
集中所有与鉴权、角色分流、后台线程池相关的工具，避免散落在 main.py / 各 router。
"""
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import db

# 全局线程池：把同步的 SQLite 操作放到后台线程，避免阻塞 FastAPI 事件循环。
# 所有 router 都通过 run_sync() 调用 db 的同步函数。
executor = ThreadPoolExecutor(max_workers=8)


def run_sync(fn, *a, **kw):
    """把同步函数放到线程池里执行，返回 awaitable 同步结果。"""
    return executor.submit(partial(fn, *a, **kw)).result()


# ------------------------- 鉴权中间件 -------------------------
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
    """从 request.state.username 读取当前登录用户；空字符串表示未登录（中间件不会让未登录请求到达这里）。"""
    return request.state.username or ""


def is_admin(request: Request) -> bool:
    """是否管理员。管理员用户名在 db.DEFAULT_ADMIN_USER 中定义（默认 'admin'）。"""
    return current_user(request) == db.DEFAULT_ADMIN_USER


def require_admin(request: Request):
    """权限闸门：非 admin 抛 403。"""
    if not is_admin(request):
        raise HTTPException(403, "仅管理员可操作")


# ------------------------- 角色分流工具 -------------------------
def resolve_user_key_payload(data: dict, request: Request):
    """
    v4 起所有用户（含 admin）的两类密钥都直接写到 db.users 自己行：
      - api_key       → db.users.api_key       （对话 LLM 用）
      - image_api_key → db.users.image_api_key （图像生成用；空串=回退到 api_key）
    没有「系统共享 key」概念。
    返回 (cleaned_data, ignored)
      cleaned_data: 仍要交给 cfg.update 的字段（非密钥字段，与 key 无关）
      ignored     : 被丢弃的字段名列表（当前永远空，留作扩展位）
    """
    user = current_user(request)
    ignored = []
    if "api_key" in data:
        val = (data.pop("api_key") or "")
        row = db.get_user_by_username(user)
        if not row:
            raise HTTPException(404, "用户不存在")
        db.set_user_api_key(row["id"], val.strip())
        db.log_activity(user, "set_user_api_key",
                        ("设置" if val else "清空") + " 自己的 API Key", row["id"])
    if "image_api_key" in data:
        val = (data.pop("image_api_key") or "")
        row = db.get_user_by_username(user)
        if not row:
            raise HTTPException(404, "用户不存在")
        db.set_user_image_api_key(row["id"], val.strip())
        db.log_activity(user, "set_user_image_api_key",
                        ("设置" if val else "清空") + " 自己的 图像 API Key", row["id"])
    return data, ignored
