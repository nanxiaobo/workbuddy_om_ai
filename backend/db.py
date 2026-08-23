"""
db.py —— SQLite 持久化层
-----------------------------------------------------------------
表结构：
  users         账户（默认管理员 + 管理员创建的其他用户）
  tokens        登录令牌（Bearer Token 持久化）
  characters    角色卡（含创建者 user）
  memories      角色记忆要点
  conversations 会话（含创建者 user、自定义聊天背景）
  messages      消息
  activity_log  用户操作日志（用于管理员审计）
  config_kv     预留键值表

所有函数均为同步实现；在 FastAPI 中通过 run_in_threadpool 调用，避免阻塞事件循环。

数据持久化保证：
  - 数据库位于 backend/data/app.db（绝对路径，与启动目录无关）。
  - 初始化时自动备份到 backend/data/backups/app.bak（使用 os.replace 覆盖，保留最近 1 份）。
  - 所有表结构变更均为「新增列/新增表」，不会 DROP 已有数据。
"""
import os
import shutil
import sqlite3
import uuid
import secrets
import hashlib
import glob
import json
from datetime import datetime, timezone

# 路径：项目根 → backend/data/。无论从哪里启动，db.py 都在 backend/，取它的兄弟目录 data/。
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(_DATA_DIR, "app.db")
BACKUP_DIR = os.path.join(_DATA_DIR, "backups")

# 默认管理员账户（仅用于首次初始化，可在数据库或后台用户管理页改密码）
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "nxb03070"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex


def _hash_pw(password: str, salt: str) -> str:
    """使用 PBKDF2-HMAC-SHA256 进行密码哈希（无需第三方依赖）。"""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    ).hex()


def _backup_db() -> None:
    """
    启动时备份数据库到 backend/backups/app.bak。
    使用 os.replace 覆盖旧备份，避免在 Windows 沙箱中因回收站不可用而失败。
    """
    if not os.path.exists(DB_PATH):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dst = os.path.join(BACKUP_DIR, "app.bak")
    tmp = dst + ".tmp"
    try:
        shutil.copy2(DB_PATH, tmp)
        os.replace(tmp, dst)
    except Exception:
        pass
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str, index: str = None) -> None:
    """兼容老库：若列不存在则新增，避免重建表丢数据；可选创建索引。"""
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        cols = [r["name"] for r in cur.fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        if index:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {index} ON {table}({column})")
    except Exception:
        pass


def init_db() -> None:
    """初始化数据库表结构（幂等、不丢数据）。"""
    _backup_db()
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id          TEXT PRIMARY KEY,
                username    TEXT NOT NULL UNIQUE,
                pw_hash     TEXT NOT NULL,
                salt        TEXT NOT NULL,
                role        TEXT DEFAULT 'user',
                created_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS tokens (
                token       TEXT PRIMARY KEY,
                username    TEXT NOT NULL,
                created_at  TEXT,
                last_seen_at TEXT,
                expires_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS characters (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                avatar          TEXT DEFAULT '',
                persona         TEXT DEFAULT '',
                personality     TEXT DEFAULT '',
                speaking_style  TEXT DEFAULT '',
                example_dialogues TEXT DEFAULT '',
                world_setting   TEXT DEFAULT '',
                greeting        TEXT DEFAULT '',
                tags            TEXT DEFAULT '',
                user            TEXT DEFAULT '',
                created_at      TEXT,
                updated_at      TEXT
            );
            CREATE TABLE IF NOT EXISTS memories (
                id            TEXT PRIMARY KEY,
                character_id  TEXT NOT NULL,
                content       TEXT NOT NULL,
                created_at    TEXT
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id            TEXT PRIMARY KEY,
                character_id  TEXT NOT NULL,
                title         TEXT DEFAULT '新对话',
                background    TEXT DEFAULT '',
                user          TEXT DEFAULT '',
                created_at    TEXT,
                updated_at    TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                created_at      TEXT
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id          TEXT PRIMARY KEY,
                username    TEXT NOT NULL,
                action      TEXT NOT NULL,
                detail      TEXT DEFAULT '',
                target_id   TEXT DEFAULT '',
                created_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS config_kv (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_mem_char ON memories(character_id);
            CREATE INDEX IF NOT EXISTS idx_conv_char ON conversations(character_id);
            CREATE INDEX IF NOT EXISTS idx_act_user ON activity_log(username);
            """
        )
        # 老库兼容：新增列与索引（不会丢数据）
        _ensure_column(conn, "conversations", "background", "background TEXT DEFAULT ''")
        _ensure_column(conn, "conversations", "user", "user TEXT DEFAULT ''", "idx_conv_user")
        _ensure_column(conn, "characters", "user", "user TEXT DEFAULT ''", "idx_char_user")
        _ensure_column(conn, "characters", "refs", "refs TEXT DEFAULT ''")
        _ensure_column(conn, "messages", "image", "image TEXT DEFAULT ''")
        _ensure_column(conn, "users", "role", "role TEXT DEFAULT 'user'")
        # 单用户独立 API Key（管理员可在用户管理页分配/清空；普通用户不能读取或修改）
        _ensure_column(conn, "users", "api_key", "api_key TEXT DEFAULT ''")
        _ensure_column(conn, "users", "image_api_key", "image_api_key TEXT DEFAULT ''")   # 每位用户独立图像 key（v4 起，留空回退到 api_key）
        # 登录令牌：到期时间 + 最近活跃时间（用于自动续期 + 离线清理）
        _ensure_column(conn, "tokens", "expires_at", "expires_at TEXT")
        _ensure_column(conn, "tokens", "last_seen_at", "last_seen_at TEXT")
        conn.commit()
    finally:
        conn.close()
    init_users()


def init_users() -> None:
    """首次启动时写入默认管理员账户（admin / nxb03070），并确保其角色为 admin。"""
    conn = get_conn()
    try:
        cnt = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if cnt == 0:
            salt = secrets.token_hex(16)
            pw = _hash_pw(DEFAULT_ADMIN_PASS, salt)
            conn.execute(
                "INSERT INTO users (id,username,pw_hash,salt,role,created_at) VALUES (?,?,?,?,?,?)",
                (_uid(), DEFAULT_ADMIN_USER, pw, salt, "admin", _now()),
            )
            conn.commit()
        else:
            # 兼容老库：若默认管理员角色不是 admin，则修正
            conn.execute(
                "UPDATE users SET role='admin' WHERE username=? AND (role IS NULL OR role='' OR role='user')",
                (DEFAULT_ADMIN_USER,),
            )
            conn.commit()
    finally:
        conn.close()


# ------------------------- 账户 / 鉴权 -------------------------
def verify_user(username: str, password: str) -> bool:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        if not row:
            return False
        return _hash_pw(password, row["salt"]) == row["pw_hash"]
    finally:
        conn.close()


def list_users() -> list:
    """列出所有用户（仅用于管理员管理）。api_key / image_api_key 字段直接返回明文，方便管理员在用户管理页
    查看 / 修改（不做隐私掩码；管理员本身的界面就是特权入口）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, username, role, created_at, api_key, image_api_key FROM users ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_by_id(uid: str) -> dict:
    """按 id 取用户；返回明文 api_key / image_api_key 供管理员查看 / 修改。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, username, role, created_at, api_key, image_api_key FROM users WHERE id=?",
            (uid,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict:
    """按用户名取用户；返回明文 api_key / image_api_key 供后端 LLM 调用使用。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, username, role, created_at, api_key, image_api_key FROM users WHERE username=?",
            (username,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_api_key(username: str) -> str:
    """读取某用户的对话 API Key（明文，仅内部调用，勿对外暴露）。不存在返回空串。"""
    if not username:
        return ""
    conn = get_conn()
    try:
        row = conn.execute("SELECT api_key FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            return ""
        return (row["api_key"] or "").strip()
    finally:
        conn.close()


def get_user_image_api_key(username: str) -> str:
    """读取某用户的图像生成 API Key（明文，仅内部调用）。不存在或为空返回空串（调用方回退到 api_key）。"""
    if not username:
        return ""
    conn = get_conn()
    try:
        row = conn.execute("SELECT image_api_key FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            return ""
        return (row["image_api_key"] or "").strip()
    finally:
        conn.close()


def set_user_api_key(uid: str, api_key: str) -> dict:
    """管理员给指定用户写入 / 清空对话 API Key。传空字符串等同于清空。"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise ValueError("用户不存在")
        conn.execute("UPDATE users SET api_key=? WHERE id=?", (api_key or "", uid))
        conn.commit()
        return get_user_by_id(uid)
    finally:
        conn.close()


def set_user_image_api_key(uid: str, image_api_key: str) -> dict:
    """管理员给指定用户写入 / 清空图像 API Key。传空字符串等同于清空（调用时回退到 api_key）。"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise ValueError("用户不存在")
        conn.execute("UPDATE users SET image_api_key=? WHERE id=?", (image_api_key or "", uid))
        conn.commit()
        return get_user_by_id(uid)
    finally:
        conn.close()


def create_user(username: str, password: str, role: str = "user") -> dict:
    """管理员创建新用户。"""
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise ValueError("用户名已存在")
        salt = secrets.token_hex(16)
        pw = _hash_pw(password, salt)
        uid = _uid()
        now = _now()
        conn.execute(
            "INSERT INTO users (id,username,pw_hash,salt,role,created_at) VALUES (?,?,?,?,?,?)",
            (uid, username, pw, salt, role or "user", now),
        )
        conn.commit()
        return {"id": uid, "username": username, "role": role or "user", "created_at": now}
    finally:
        conn.close()


def update_user(uid: str, data: dict) -> dict:
    """管理员修改用户信息（用户名、角色、密码）。"""
    conn = get_conn()
    try:
        user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not user:
            raise ValueError("用户不存在")
        if user["username"] == DEFAULT_ADMIN_USER and data.get("role") and data["role"] != "admin":
            raise ValueError("不能撤销默认管理员的管理员权限")

        fields = []
        vals = []
        if "username" in data and data["username"]:
            # 检查新用户名是否冲突
            if data["username"] != user["username"]:
                if conn.execute("SELECT 1 FROM users WHERE username=?", (data["username"],)).fetchone():
                    raise ValueError("用户名已存在")
            fields.append("username=?")
            vals.append(data["username"])
        if "role" in data and data["role"]:
            fields.append("role=?")
            vals.append(data["role"])
        if "password" in data and data["password"]:
            salt = secrets.token_hex(16)
            pw = _hash_pw(data["password"], salt)
            fields.append("pw_hash=?")
            vals.append(pw)
            fields.append("salt=?")
            vals.append(salt)
        if fields:
            vals.append(uid)
            conn.execute(f"UPDATE users SET {','.join(fields)} WHERE id=?", vals)
            conn.commit()
        return get_user_by_id(uid)
    finally:
        conn.close()


def delete_user(uid: str) -> None:
    """删除用户；禁止删除默认管理员。"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        if row and row["username"] == DEFAULT_ADMIN_USER:
            raise ValueError("不能删除默认管理员")
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
    finally:
        conn.close()


def change_password(username: str, new_password: str) -> None:
    """修改指定用户密码。"""
    conn = get_conn()
    try:
        salt = secrets.token_hex(16)
        pw = _hash_pw(new_password, salt)
        conn.execute(
            "UPDATE users SET pw_hash=?, salt=? WHERE username=?",
            (pw, salt, username),
        )
        conn.commit()
    finally:
        conn.close()


# 登录 token 的默认有效期（秒）：7 天。每次校验成功会按此值自动续期到当前时间 + 7 天。
# 这意味着只要用户在 7 天内有任意活动（登录 / 调用接口 / 心跳），会话就一直保持有效。
DEFAULT_TOKEN_TTL_SECONDS = 7 * 24 * 3600


def _now_plus(seconds: int) -> str:
    return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + seconds, timezone.utc).isoformat()


def create_token(username: str, ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS) -> str:
    """签发新的登录令牌，同时写入 expires_at = now + ttl_seconds。
    - ttl_seconds <= 0 表示长期 token（基本不会过期）。
    - 老库中没有 expires_at 的旧 token 仍能继续工作（validate_token 自动按需续期）。"""
    token = secrets.token_hex(32)
    conn = get_conn()
    try:
        if ttl_seconds and ttl_seconds > 0:
            expires_at = _now_plus(ttl_seconds)
        else:
            expires_at = None
        conn.execute(
            "INSERT INTO tokens (token,username,created_at,last_seen_at,expires_at) "
            "VALUES (?,?,?,?,?)",
            (token, username, _now(), _now(), expires_at),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def validate_token(token: str, auto_extend: bool = True):
    """校验令牌。

    返回值：
        命中且有效 → 字符串用户名。
        不存在或已过期 → None（让上层拒绝请求）。

    自动续期策略（auto_extend=True）：
        - 仅当 expires_at 有值时才续期；过期才续期没有意义。
        - 续期方式：若距离到期时间 < 1 天，立刻把 expires_at 重新拉满到 now + DEFAULT_TOKEN_TTL_SECONDS，
          避免每次接口都写库。
        - 每次成功都会更新 last_seen_at，方便后续清理/审计。
    """
    if not token:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT username, expires_at FROM tokens WHERE token=?", (token,)
        ).fetchone()
        if not row:
            return None
        expires_at = row["expires_at"]
        username = row["username"]
        # 检查是否过期（仅当 expires_at 有值时才检查；老库空值视为永久有效）
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if datetime.now(timezone.utc) >= exp_dt:
                    # 已过期，立刻从库中清除（便于下次请求快速失败）
                    conn.execute("DELETE FROM tokens WHERE token=?", (token,))
                    conn.commit()
                    return None
            except Exception:
                # 解析失败按永久有效处理，避免锁用户
                pass
        if auto_extend:
            # 仅在 expires_at 临近过期时（<= 1 天）才刷库续期，省 IO
            needs_write = False
            new_expires = None
            if expires_at:
                try:
                    exp_dt = datetime.fromisoformat(expires_at)
                    remaining = (exp_dt - datetime.now(timezone.utc)).total_seconds()
                    if remaining < 24 * 3600:
                        needs_write = True
                        new_expires = _now_plus(DEFAULT_TOKEN_TTL_SECONDS)
                except Exception:
                    pass
            else:
                # 老 token：写入 expires_at，相当于"首次激活"
                needs_write = True
                new_expires = _now_plus(DEFAULT_TOKEN_TTL_SECONDS)
            if needs_write:
                conn.execute(
                    "UPDATE tokens SET last_seen_at=?, expires_at=? WHERE token=?",
                    (_now(), new_expires, token),
                )
            else:
                conn.execute(
                    "UPDATE tokens SET last_seen_at=? WHERE token=?",
                    (_now(), token),
                )
            conn.commit()
        return username
    finally:
        conn.close()


def extend_token(token: str) -> bool:
    """轻量级 token 续期接口：把 last_seen_at 与 expires_at 都更新到当前 + TTL。
    主要用于前端心跳，确保"活跃用户"的登录态始终滚动有效。返回 False 表示 token 已失效。"""
    if not token:
        return False
    conn = get_conn()
    try:
        row = conn.execute("SELECT expires_at FROM tokens WHERE token=?", (token,)).fetchone()
        if not row:
            return False
        new_expires = _now_plus(DEFAULT_TOKEN_TTL_SECONDS)
        conn.execute(
            "UPDATE tokens SET last_seen_at=?, expires_at=? WHERE token=?",
            (_now(), new_expires, token),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def purge_expired_tokens() -> int:
    """清理已经过期的 token（多数情况由 validate_token 顺便完成；这里用于后台定期清理）。
    返回删除条数。"""
    conn = get_conn()
    try:
        now_iso = _now()
        cur = conn.execute(
            "DELETE FROM tokens WHERE expires_at IS NOT NULL AND expires_at <> '' AND expires_at < ?",
            (now_iso,),
        )
        n = cur.rowcount or 0
        conn.commit()
        return n
    finally:
        conn.close()


def delete_token(token: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM tokens WHERE token=?", (token,))
        conn.commit()
    finally:
        conn.close()


# ------------------------- 操作日志 -------------------------
def log_activity(username: str, action: str, detail: str = "", target_id: str = "") -> None:
    """记录用户关键操作，供管理员审计。"""
    if not username:
        return
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO activity_log (id,username,action,detail,target_id,created_at) VALUES (?,?,?,?,?,?)",
            (_uid(), username, action, detail, target_id, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def list_activity(username: str = None, limit: int = 100) -> list:
    conn = get_conn()
    try:
        if username:
            rows = conn.execute(
                "SELECT * FROM activity_log WHERE username=? ORDER BY created_at DESC LIMIT ?",
                (username, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ------------------------- 角色卡 -------------------------
def _serialize_refs(refs):
    """参考图统一存为 JSON 字符串；接受 list 或已序列化的字符串。"""
    if refs is None:
        return ""
    if isinstance(refs, (list, tuple)):
        items = [r for r in refs if r]
        return json.dumps(items, ensure_ascii=False)
    return refs or ""


def create_character(data: dict, user: str = "") -> dict:
    cid = data.get("id") or _uid()
    now = _now()
    refs = _serialize_refs(data.get("refs"))
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO characters
               (id,name,avatar,persona,personality,speaking_style,example_dialogues,world_setting,greeting,tags,user,refs,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid,
                data.get("name", "未命名角色"),
                data.get("avatar", ""),
                data.get("persona", ""),
                data.get("personality", ""),
                data.get("speaking_style", ""),
                data.get("example_dialogues", ""),
                data.get("world_setting", ""),
                data.get("greeting", ""),
                data.get("tags", ""),
                user or data.get("user", ""),
                refs,
                now,
                now,
            ),
        )
        conn.commit()
        return get_character(cid)
    finally:
        conn.close()


def get_character(cid: str) -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        # 参考图反序列化为列表，便于前端使用
        try:
            d["refs"] = json.loads(d.get("refs") or "[]")
        except Exception:
            d["refs"] = []
        return d
    finally:
        conn.close()


def list_characters(user: str = None) -> list:
    conn = get_conn()
    try:
        if user:
            rows = conn.execute(
                "SELECT * FROM characters WHERE user=? ORDER BY updated_at DESC", (user,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM characters ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_character(cid: str, data: dict) -> dict:
    conn = get_conn()
    try:
        fields = []
        vals = []
        for k in (
            "name",
            "avatar",
            "persona",
            "personality",
            "speaking_style",
            "example_dialogues",
            "world_setting",
            "greeting",
            "tags",
        ):
            if k in data:
                fields.append(f"{k}=?")
                vals.append(data[k])
        # refs 单独处理（list -> JSON 字符串）
        if "refs" in data:
            fields.append("refs=?")
            vals.append(_serialize_refs(data["refs"]))
        if fields:
            fields.append("updated_at=?")
            vals.append(_now())
            vals.append(cid)
            conn.execute(
                f"UPDATE characters SET {','.join(fields)} WHERE id=?", vals
            )
            conn.commit()
        return get_character(cid)
    finally:
        conn.close()


def delete_character(cid: str) -> None:
    conn = get_conn()
    try:
        # 级联删除该角色的记忆与会话及其消息
        conv_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM conversations WHERE character_id=?", (cid,)
            ).fetchall()
        ]
        for vid in conv_ids:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (vid,))
        conn.execute("DELETE FROM conversations WHERE character_id=?", (cid,))
        conn.execute("DELETE FROM memories WHERE character_id=?", (cid,))
        conn.execute("DELETE FROM characters WHERE id=?", (cid,))
        conn.commit()
    finally:
        conn.close()


# ------------------------- 记忆 -------------------------
def list_memories(character_id: str) -> list:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM memories WHERE character_id=? ORDER BY created_at ASC",
            (character_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_memory(character_id: str, content: str) -> dict:
    mid = _uid()
    now = _now()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO memories (id,character_id,content,created_at) VALUES (?,?,?,?)",
            (mid, character_id, content, now),
        )
        conn.commit()
        return {"id": mid, "character_id": character_id, "content": content, "created_at": now}
    finally:
        conn.close()


def update_memory(mid: str, content: str) -> dict:
    conn = get_conn()
    try:
        conn.execute("UPDATE memories SET content=? WHERE id=?", (content, mid))
        conn.commit()
        row = conn.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_memory(mid: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM memories WHERE id=?", (mid,))
        conn.commit()
    finally:
        conn.close()


# ------------------------- 会话 -------------------------
def create_conversation(character_id: str, title: str = "新对话", user: str = "") -> dict:
    vid = _uid()
    now = _now()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO conversations (id,character_id,title,background,user,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (vid, character_id, title, "", user, now, now),
        )
        conn.commit()
        return get_conversation(vid)
    finally:
        conn.close()


def get_conversation(vid: str) -> dict:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id=?", (vid,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_conversations(character_id: str = None, user: str = None) -> list:
    conn = get_conn()
    try:
        params = []
        where = []
        if character_id:
            where.append("character_id=?")
            params.append(character_id)
        if user:
            where.append("user=?")
            params.append(user)
        sql = "SELECT * FROM conversations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC"
        rows = conn.execute(sql, params).fetchall()
        result = []
        # 用 IN 子查询一次取出所有候选会话的最新一条消息，避免 N+1
        ids = [r["id"] for r in rows]
        last_msg_map = {}
        if ids:
            placeholders = ",".join("?" for _ in ids)
            lm_rows = conn.execute(
                f"""SELECT m.conversation_id AS cid, m.content AS content, m.role AS role, m.created_at AS created_at
                    FROM messages m
                    INNER JOIN (
                        SELECT conversation_id, MAX(created_at) AS max_at
                        FROM messages GROUP BY conversation_id
                    ) latest ON latest.conversation_id = m.conversation_id AND latest.max_at = m.created_at
                    WHERE m.conversation_id IN ({placeholders})""",
                ids,
            ).fetchall()
            for r in lm_rows:
                last_msg_map[r["cid"]] = {
                    "content": r["content"], "role": r["role"], "created_at": r["created_at"]
                }
        for r in rows:
            d = dict(r)
            cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE conversation_id=?",
                (d["id"],),
            ).fetchone()["c"]
            d["message_count"] = cnt
            lm = last_msg_map.get(d["id"])
            d["last_message"] = lm["content"] if lm else ""
            d["last_message_role"] = lm["role"] if lm else ""
            d["last_message_at"] = lm["created_at"] if lm else d.get("updated_at", "")
            result.append(d)
        return result
    finally:
        conn.close()


def list_conversations_by_character(character_id: str) -> list:
    return list_conversations(character_id=character_id)


def delete_conversation(vid: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (vid,))
        conn.execute("DELETE FROM conversations WHERE id=?", (vid,))
        conn.commit()
    finally:
        conn.close()


def clear_conversation(vid: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (vid,))
        conn.commit()
    finally:
        conn.close()


def touch_conversation(vid: str, title: str = None) -> None:
    conn = get_conn()
    try:
        if title:
            conn.execute(
                "UPDATE conversations SET updated_at=?, title=? WHERE id=?",
                (_now(), title, vid),
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (_now(), vid)
            )
        conn.commit()
    finally:
        conn.close()


def update_conversation_background(vid: str, background: str) -> None:
    """设置会话的自定义聊天背景（图片 URL / dataURL / CSS 渐变字符串）。"""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE conversations SET background=? WHERE id=?", (background, vid)
        )
        conn.commit()
    finally:
        conn.close()


def count_messages(conversation_id: str) -> int:
    """统计会话消息总数（用于超长记忆自动总结）。"""
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()["c"]
    finally:
        conn.close()


# ------------------------- 消息 -------------------------
def add_message(conversation_id: str, role: str, content: str, image: str = "") -> dict:
    mid = _uid()
    now = _now()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO messages (id,conversation_id,role,content,image,created_at) VALUES (?,?,?,?,?,?)",
            (mid, conversation_id, role, content, image, now),
        )
        conn.commit()
        return {
            "id": mid,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "image": image,
            "created_at": now,
        }
    finally:
        conn.close()


def get_message(mid: str) -> dict:
    """获取单条消息（含生成的图片）。"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_message_image(mid: str, image: str) -> None:
    """更新某条消息生成的图片（dataURL 或外链）。"""
    conn = get_conn()
    try:
        conn.execute("UPDATE messages SET image=? WHERE id=?", (image, mid))
        conn.commit()
    finally:
        conn.close()


def list_messages(conversation_id: str, limit: int = None) -> list:
    conn = get_conn()
    try:
        if limit:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_messages(conversation_id: str, rounds: int) -> list:
    """取最近 rounds 轮（即最多 rounds*2 条）消息，按时间正序返回。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
            (conversation_id, rounds * 2),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


# ------------------------- 用户统计（管理员用） -------------------------
def get_user_stats(username: str) -> dict:
    """汇总某用户的数据：角色数、会话数、消息数、记忆数。"""
    conn = get_conn()
    try:
        chars = conn.execute(
            "SELECT COUNT(*) AS c FROM characters WHERE user=?", (username,)
        ).fetchone()["c"]
        convs = conn.execute(
            "SELECT COUNT(*) AS c FROM conversations WHERE user=?", (username,)
        ).fetchone()["c"]
        msgs = conn.execute(
            "SELECT COUNT(*) AS c FROM messages m JOIN conversations c ON m.conversation_id=c.id WHERE c.user=?",
            (username,),
        ).fetchone()["c"]
        # 记忆数：通过该用户创建的角色所持有的记忆
        mems = conn.execute(
            "SELECT COUNT(*) AS c FROM memories mem JOIN characters ch ON mem.character_id=ch.id WHERE ch.user=?",
            (username,),
        ).fetchone()["c"]
        return {"characters": chars, "conversations": convs, "messages": msgs, "memories": mems}
    finally:
        conn.close()
