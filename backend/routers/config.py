"""
routers/config.py —— 配置接口（GET / PUT /api/config）
v4 起每位用户用自己 db.users.api_key + db.users.image_api_key；两者都独立，调用方按需取用。
"""
from fastapi import APIRouter, Request

from core.models import ConfigPatch
from core.security import current_user, is_admin, resolve_user_key_payload
import config as cfg_mod

router = APIRouter()


@router.get("/api/config")
def api_get_config(request: Request):
    """返回当前用户应当使用的配置：每位用户都自己看自己的 key（明文）。"""
    user = current_user(request)
    cfg = cfg_mod.get_effective_config(user)
    cfg["is_admin"] = is_admin(request)
    cfg["api_key_source"] = "individual"
    return cfg


@router.put("/api/config")
def api_update_config(patch: ConfigPatch, request: Request):
    """
    所有用户的 api_key / image_api_key 字段都写到自己 db.users 对应行；其他字段（model / temperature 等）走 config.json。
    """
    data = {k: v for k, v in patch.dict().items() if v is not None}
    data, ignored = resolve_user_key_payload(data, request)
    if data:
        cfg_mod.update_config(data)
    # 返回 effective（让前端立刻看到自己改完的 key 落地）
    user = current_user(request)
    result = cfg_mod.get_effective_config(user)
    result["is_admin"] = is_admin(request)
    result["api_key_source"] = "individual"
    if ignored:
        result["ignored_keys"] = ignored
    return result
