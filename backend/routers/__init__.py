"""
routers/__init__.py —— 聚合所有业务路由，统一在 main.py 一次性 include_router。
"""
from fastapi import APIRouter

from . import auth, users, config as config_router, characters, conversations, memories, chat, media


def all_routers() -> list[APIRouter]:
    """返回所有 router 的列表（顺序不影响，FastAPI 按注册顺序匹配）。"""
    return [
        auth.router,
        users.router,
        config_router.router,
        characters.router,
        memories.router,
        conversations.router,
        chat.router,
        media.router,
    ]
