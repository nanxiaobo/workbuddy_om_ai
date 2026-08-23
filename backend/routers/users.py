"""
routers/users.py —— 用户管理（CRUD / 密码 / API Key 分配 / 审计 / 角色-会话-记忆详情）
所有接口仅管理员可调（除改自己密码）。
"""
from fastapi import APIRouter, HTTPException, Request

from core.models import PasswordIn, UserCreateIn, UserUpdateIn
from core.security import current_user, is_admin, require_admin, run_sync
import db

router = APIRouter()


# ------------------------- 用户列表 / CRUD -------------------------
@router.get("/api/users")
def api_list_users(request: Request):
    require_admin(request)
    return run_sync(db.list_users)


@router.post("/api/users")
def api_create_user(request: Request, u: UserCreateIn):
    require_admin(request)
    if not u.username.strip() or not u.password:
        raise HTTPException(400, "用户名和密码不能为空")
    try:
        created = run_sync(db.create_user, u.username.strip(), u.password, u.role or "user")
        run_sync(db.log_activity, current_user(request), "create_user",
                 f"创建用户 {created.get('username')}", created.get("id"))
        return created
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.get("/api/users/{uid}")
def api_get_user(request: Request, uid: str):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    user["stats"] = run_sync(db.get_user_stats, user["username"])
    return user


@router.put("/api/users/{uid}")
def api_update_user(request: Request, uid: str, u: UserUpdateIn):
    require_admin(request)
    try:
        updated = run_sync(db.update_user, uid, u.dict(exclude_unset=True))
        run_sync(db.log_activity, current_user(request), "update_user",
                 f"修改用户 {updated.get('username')} 信息", uid)
        return updated
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/users/{uid}")
def api_delete_user(request: Request, uid: str):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    try:
        run_sync(db.delete_user, uid)
        run_sync(db.log_activity, current_user(request), "delete_user",
                 f"删除用户 {user.get('username') if user else uid}", uid)
    except ValueError as e:
        raise HTTPException(403, str(e))
    return {"ok": True}


# ------------------------- 修改自己密码 -------------------------
@router.put("/api/users/me/password")
def api_change_password(request: Request, p: PasswordIn):
    username = current_user(request)
    if not username:
        raise HTTPException(401, "未登录")
    if p.old_password and not db.verify_user(username, p.old_password):
        raise HTTPException(401, "旧密码错误")
    if not p.new_password or len(p.new_password) < 4:
        raise HTTPException(400, "新密码至少 4 位")
    run_sync(db.change_password, username, p.new_password)
    return {"ok": True}


# ------------------------- 分配 / 清空 API Key -------------------------
@router.put("/api/users/{uid}/api-key")
def api_set_user_api_key(request: Request, uid: str, body: dict):
    """
    管理员在 users.html 内联编辑某用户 API Key 时调用。
    body: {api_key: str}，空串 = 清空。
    """
    if not is_admin(request):
        raise HTTPException(403, "仅管理员可分配密钥")
    api_key = (body or {}).get("api_key", "")
    if not isinstance(api_key, str):
        raise HTTPException(400, "api_key 必须是字符串")
    api_key = api_key.strip()
    try:
        user = db.set_user_api_key(uid, api_key)
    except ValueError as e:
        raise HTTPException(404, str(e))
    run_sync(db.log_activity, current_user(request), "set_user_api_key",
             f"{'分配' if api_key else '清空'}用户 {user.get('username') if user else uid} 的 API Key", uid)
    return {"ok": True, "user": user}


@router.put("/api/users/{uid}/image-api-key")
def api_set_user_image_api_key(request: Request, uid: str, body: dict):
    """
    管理员给指定用户写入 / 清空图像生成 API Key。空串=清空（回退到 api_key）。
    """
    if not is_admin(request):
        raise HTTPException(403, "仅管理员可分配密钥")
    image_api_key = (body or {}).get("image_api_key", "")
    if not isinstance(image_api_key, str):
        raise HTTPException(400, "image_api_key 必须是字符串")
    image_api_key = image_api_key.strip()
    try:
        user = db.set_user_image_api_key(uid, image_api_key)
    except ValueError as e:
        raise HTTPException(404, str(e))
    run_sync(db.log_activity, current_user(request), "set_user_image_api_key",
             f"{'分配' if image_api_key else '清空'}用户 {user.get('username') if user else uid} 的 图像 API Key", uid)
    return {"ok": True, "user": user}


# ------------------------- 审计 / 子资源详情 -------------------------
@router.get("/api/users/{uid}/activity")
def api_user_activity(request: Request, uid: str, limit: int = 200):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    return {
        "user": user,
        "stats": run_sync(db.get_user_stats, user["username"]),
        "activity": run_sync(db.list_activity, user["username"], limit),
    }


@router.get("/api/users/{uid}/characters")
def api_user_characters(request: Request, uid: str):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    return run_sync(db.list_characters, user["username"])


@router.get("/api/users/{uid}/conversations")
def api_user_conversations(request: Request, uid: str):
    require_admin(request)
    user = run_sync(db.get_user_by_id, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    return run_sync(db.list_conversations, user=user["username"])
