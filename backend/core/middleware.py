"""
core/middleware.py —— 通用 HTTP 中间件
"""
from starlette.middleware.base import BaseHTTPMiddleware


# 让前端静态资源强制每次重新拉（避免 SW / 浏览器缓存命中旧版本看不到效果）。
# 仅作用于非 /api 接口；流式响应的 SSE /api/chat 已经自带 no-cache。
class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        path = request.url.path
        if path.startswith("/api"):
            return resp
        # 仅对 html/css/js/icon 等前端静态资源强制 no-cache；不影响其他附件。
        if any(path.endswith(ext) for ext in (".html", ".htm", ".css", ".js", ".json", ".png", ".svg", ".ico")):
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        return resp
