"""
test_e2e.py —— 全功能端到端测试
覆盖：auth / users / config / characters / memories / conversations / chat / media / 前端页面
运行：python test_e2e.py
"""
import json
import time
import httpx

BASE = "http://127.0.0.1:8011"
PASS = 0
FAIL = 0
SKIP = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def skip(name, reason=""):
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name}  {reason}")


c = httpx.Client(base_url=BASE, timeout=30)


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


print("=" * 60)
print("【1】前端页面访问")
print("=" * 60)
for path in ["/", "/index.html", "/users.html", "/css/style.css", "/js/shared.js", "/js/app.js", "/js/users.js", "/sw.js", "/manifest.json"]:
    r = c.get(path, follow_redirects=False)
    check(f"GET {path} -> 200", r.status_code == 200, f"got {r.status_code}")

# users.html 必须强制登录（不读 localStorage 是前端行为，后端只保证页面返回）
check("users.html 含强制登录提示", "此页面每次访问都会要求重新登录" in c.get("/users.html").text)

print()
print("=" * 60)
print("【2】鉴权 auth")
print("=" * 60)
# health 无需鉴权
r = c.get("/api/health")
check("GET /api/health (无需鉴权)", r.json().get("status") == "ok")

# 未登录访问受保护接口应 401
r = c.get("/api/me")
check("未登录 GET /api/me -> 401", r.status_code == 401)

# 登录 admin（默认密码来自 db.DEFAULT_ADMIN_PASS）
r = c.post("/api/login", json={"username": "admin", "password": "nxb03070"})
check("POST /api/login admin", r.status_code == 200 and "token" in r.json(), r.text)
admin_token = r.json().get("token", "")
check("登录返回 token 非空", bool(admin_token))

# /api/me
r = c.get("/api/me", headers=auth_headers(admin_token))
check("GET /api/me -> 当前用户", r.json().get("username") == "admin")
check("/api/me is_admin=True", r.json().get("is_admin") is True)

# /api/ping 续期
r = c.get("/api/ping", headers=auth_headers(admin_token))
check("GET /api/ping 续期", r.json().get("ok") is True and r.json().get("username") == "admin")

# 错误 token 应 401
r = c.get("/api/me", headers={"Authorization": "Bearer invalidtoken123"})
check("错误 token -> 401", r.status_code == 401)

print()
print("=" * 60)
print("【3】用户管理 users（每位用户独立 api_key，明文展示）")
print("=" * 60)
H = auth_headers(admin_token)

# 列表
r = c.get("/api/users", headers=H)
check("GET /api/users (管理员)", r.status_code == 200 and isinstance(r.json(), list))
users = r.json()
check("列表含 admin 用户", any(u.get("username") == "admin" for u in users))
check("列表返回明文 api_key 字段", all("api_key" in u for u in users), "字段缺失")

# 创建测试用户
test_user = f"tester_{int(time.time())}"
r = c.post("/api/users", json={"username": test_user, "password": "test1234", "role": "user"}, headers=H)
check("POST /api/users 创建 tester", r.status_code in (200, 201), r.text)
if r.status_code in (200, 201):
    test_uid = r.json().get("id")
    check("创建返回 id", bool(test_uid))
else:
    test_uid = None

if test_uid:
    # 给 tester 分配 api_key（明文）
    test_key = "sk-test-key-abc123"
    r = c.put(f"/api/users/{test_uid}/api-key", json={"api_key": test_key}, headers=H)
    check("PUT api-key 分配", r.json().get("ok") is True, r.text)
    check("返回明文 api_key", r.json().get("user", {}).get("api_key") == test_key)

    # 重新列表确认明文回显
    r = c.get("/api/users", headers=H)
    tu = next((u for u in r.json() if u.get("id") == test_uid), None)
    check("列表明文回显 api_key", tu and tu.get("api_key") == test_key)

    # 清空 api_key
    r = c.put(f"/api/users/{test_uid}/api-key", json={"api_key": ""}, headers=H)
    check("PUT api-key 清空", r.json().get("user", {}).get("api_key") == "")

    # 重新分配以便后续
    c.put(f"/api/users/{test_uid}/api-key", json={"api_key": test_key}, headers=H)

    # 详情 + stats
    r = c.get(f"/api/users/{test_uid}", headers=H)
    check("GET /api/users/{uid} 详情+stats", r.json().get("stats") is not None)

    # activity
    r = c.get(f"/api/users/{test_uid}/activity", headers=H)
    check("GET activity", r.json().get("user") is not None and r.json().get("activity") is not None)

    # characters / conversations 子资源
    r = c.get(f"/api/users/{test_uid}/characters", headers=H)
    check("GET user characters (list)", isinstance(r.json(), list))
    r = c.get(f"/api/users/{test_uid}/conversations", headers=H)
    check("GET user conversations (list)", isinstance(r.json(), list))

    # 编辑用户
    r = c.put(f"/api/users/{test_uid}", json={"password": "newpass1234"}, headers=H)
    check("PUT /api/users/{uid} 改密码", r.status_code == 200, r.text)

    # 删除用户
    r = c.delete(f"/api/users/{test_uid}", headers=H)
    check("DELETE /api/users/{uid}", r.json().get("ok") is True)

print()
print("=" * 60)
print("【4】配置 config（每位用户独立 key）")
print("=" * 60)
r = c.get("/api/config", headers=H)
check("GET /api/config", r.status_code == 200)
cfg_before = r.json()
check("config 含 api_key 字段", "api_key" in cfg_before)

# PUT 配置
r = c.put("/api/config", json={"api_key": "sk-admin-config-test", "model": "qwen-turbo"}, headers=H)
check("PUT /api/config", r.status_code == 200 and r.json().get("api_key") == "sk-admin-config-test", r.text)

# 确认持久化
r = c.get("/api/config", headers=H)
check("config 持久化生效", r.json().get("api_key") == "sk-admin-config-test")

print()
print("=" * 60)
print("【5】角色卡 characters")
print("=" * 60)
r = c.post("/api/characters", json={
    "name": "测试角色", "avatar": "🧪", "persona": "我是一个测试角色",
    "greeting": "你好，我是测试角色", "tags": "测试",
}, headers=H)
check("POST /api/characters 创建", r.status_code in (200, 201), r.text)
char_id = r.json().get("id") if r.status_code in (200, 201) else None

if char_id:
    r = c.get("/api/characters", headers=H)
    check("GET /api/characters 列表", any(ch.get("id") == char_id for ch in r.json()))
    r = c.put(f"/api/characters/{char_id}", json={"persona": "更新后的设定"}, headers=H)
    check("PUT /api/characters/{id} 更新", r.status_code == 200, r.text)

print()
print("=" * 60)
print("【6】记忆 memories")
print("=" * 60)
if char_id:
    r = c.post(f"/api/characters/{char_id}/memories", json={"content": "测试记忆条目"}, headers=H)
    check("POST memory 创建", r.status_code in (200, 201), r.text)
    mem_id = r.json().get("id") if r.status_code in (200, 201) else None
    r = c.get(f"/api/characters/{char_id}/memories", headers=H)
    check("GET memories 列表", isinstance(r.json(), list))
    if mem_id:
        r = c.put(f"/api/memories/{mem_id}", json={"content": "更新记忆"}, headers=H)
        check("PUT /api/memories/{mid} 更新", r.status_code == 200, r.text)

print()
print("=" * 60)
print("【7】会话 conversations")
print("=" * 60)
if char_id:
    r = c.post("/api/conversations", json={"character_id": char_id, "title": "测试会话"}, headers=H)
    check("POST /api/conversations 创建", r.status_code in (200, 201), r.text)
    conv_id = r.json().get("id") if r.status_code in (200, 201) else None
    if conv_id:
        r = c.get("/api/conversations", headers=H)
        check("GET /api/conversations 列表", isinstance(r.json(), list))
        r = c.get(f"/api/conversations/{conv_id}", headers=H)
        check("GET /api/conversations/{vid} 详情", r.status_code == 200, r.text)
        r = c.put(f"/api/conversations/{conv_id}/background", json={"background": "linear-gradient(135deg,#1a1a2e,#16213e)"}, headers=H)
        check("PUT /api/conversations/{vid}/background", r.status_code == 200, r.text)

print()
print("=" * 60)
print("【8】聊天 chat（SSE 流式，无真实 Key 应优雅报错而非崩溃）")
print("=" * 60)
if char_id and conv_id:
    r = c.post("/api/chat", json={
        "conversation_id": conv_id,
        "user_message": "你好",
    }, headers=H)
    # SSE 或错误都算可用（关键是不 500 崩溃）
    check("POST /api/chat 不崩溃", r.status_code in (200, 400, 401, 422, 500) and r.status_code != 500,
          f"status={r.status_code}, body={r.text[:120]}")

print()
print("=" * 60)
print("【9】登出 logout")
print("=" * 60)
r = c.post("/api/logout", headers=H)
check("POST /api/logout", r.json().get("ok") is True)
# 登出后 token 应失效
r = c.get("/api/me", headers=auth_headers(admin_token))
check("登出后旧 token -> 401", r.status_code == 401)

print()
print("=" * 60)
print("【10】v4 image_api_key 独立配置（每位用户两份 key 独立）")
print("=" * 60)
# 重新登录 admin（前面的测试在 section 9 已经 logout）
r = c.post("/api/login", json={"username": "admin", "password": "nxb03070"})
admin_token = r.json().get("token", "")
H = auth_headers(admin_token)

# 创建临时用户
r = c.post("/api/users", json={"username": "imgtester", "password": "test1234", "role": "user"}, headers=H)
img_uid = r.json().get("id") if r.status_code in (200, 201) else None
check("创建测试用户 imgtester", bool(img_uid))

if img_uid:
    # 分别设置对话 key 与图像 key（不同值）
    c.put(f"/api/users/{img_uid}/api-key", json={"api_key": "sk-chat-key"}, headers=H)
    c.put(f"/api/users/{img_uid}/image-api-key", json={"image_api_key": "sk-image-key"}, headers=H)

    # GET /api/users 列表应同时返回两个字段（明文）
    r = c.get("/api/users", headers=H)
    tu = next((u for u in r.json() if u.get("id") == img_uid), None)
    check("GET users 列表返回 api_key", tu and tu.get("api_key") == "sk-chat-key")
    check("GET users 列表返回 image_api_key", tu and tu.get("image_api_key") == "sk-image-key")

    # 用 imgtester 登录，验证 GET /api/config 两份 key 独立返回
    r = c.post("/api/login", json={"username": "imgtester", "password": "test1234"})
    img_token = r.json().get("token", "")
    IH = auth_headers(img_token)
    r = c.get("/api/config", headers=IH)
    cfg = r.json()
    check("imgtester GET /api/config 含 api_key", cfg.get("api_key") == "sk-chat-key")
    check("imgtester GET /api/config 含独立 image_api_key", cfg.get("image_api_key") == "sk-image-key")

    # PUT /api/config 同时改两份 key
    r = c.put("/api/config", json={
        "api_key": "sk-new-chat",
        "image_api_key": "sk-new-image",
    }, headers=IH)
    check("PUT /api/config 同时改两份 key",
          r.json().get("api_key") == "sk-new-chat" and r.json().get("image_api_key") == "sk-new-image",
          r.text)
    check("PUT 响应无 ignored_keys", "ignored_keys" not in r.json())

    # 单独清空 image_api_key 应回退到 api_key
    r = c.put("/api/config", json={"image_api_key": ""}, headers=IH)
    check("image_api_key 清空 → 回退到 api_key", r.json().get("image_api_key") == "sk-new-chat")

    # 单独清空 api_key：image_api_key 已是空（之前清空过），应回退到 chat key（现在也变空）
    r = c.put("/api/config", json={"api_key": ""}, headers=IH)
    check("两份 key 都清空 → 均为空串",
          r.json().get("api_key") == "" and r.json().get("image_api_key") == "")

    # 用 admin 给 imgtester 分配 image_api_key
    r = c.put(f"/api/users/{img_uid}/image-api-key", json={"image_api_key": "sk-admin-image"}, headers=H)
    check("管理员分配 image_api_key", r.json().get("user", {}).get("image_api_key") == "sk-admin-image")

    # 非管理员调 image-api-key 应 403
    r = c.put(f"/api/users/{img_uid}/image-api-key", json={"image_api_key": "evil"}, headers=IH)
    check("非管理员分配 image_api_key → 403", r.status_code == 403)

    # 清理
    c.delete(f"/api/users/{img_uid}", headers=H)

print()
print("=" * 60)
print(f"汇总：PASS={PASS}  FAIL={FAIL}  SKIP={SKIP}")
print("=" * 60)
c.close()
