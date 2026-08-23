"""
main.py —— FastAPI 应用入口（装配）
-----------------------------------------------------------------
职责：
  1. 初始化数据库（db.init_db）
  2. 创建 FastAPI 实例、注册 CORS / NoCache / Auth 中间件
  3. 注册所有 router（来自 routers/）
  4. 托管 static/ 目录作为前端静态资源

本文件**不**写业务逻辑 / 不定义 Pydantic model / 不直接挂 @app.get/post。
所有业务接口在 routers/ 下按域拆分。
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

import db
from core.middleware import NoCacheStaticMiddleware
from core.security import AuthMiddleware
from routers import all_routers

# 初始化数据库（含默认管理员账户）
db.init_db()

# FastAPI 应用
app = FastAPI(title="沉浸式 AI 聊天", version="3.0.0")

# 跨域（前端可直接以 file:// 打开或部署到任意域名调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 中间件顺序：外层 NoCacheStatic → 内层 Auth
app.add_middleware(NoCacheStaticMiddleware)
app.add_middleware(AuthMiddleware)

# 注册所有业务路由
for r in all_routers():
    app.include_router(r)

# ------------------------- 静态前端托管 -------------------------
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@app.get("/")
def index():
    """首页：强制 no-cache，避免浏览器或 Service Worker 缓存返回旧 DOM。"""
    return FileResponse(
        os.path.join(STATIC_DIR, "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# 把 static/ 目录作为静态资源（/css、/js、/manifest.json、/sw.js、/icons 等）
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
