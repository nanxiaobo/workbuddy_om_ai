"""
core/models.py —— Pydantic 数据模型（请求体 / 响应体 schema）
-----------------------------------------------------------------
所有 router 共享的数据模型集中在这里，避免散落。
"""
from typing import Optional
from pydantic import BaseModel


# ----- 鉴权 -----
class LoginIn(BaseModel):
    username: str
    password: str


# ----- 用户管理 -----
class UserCreateIn(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"


class UserUpdateIn(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None


class PasswordIn(BaseModel):
    old_password: Optional[str] = None
    new_password: str


# ----- 配置 -----
class ConfigPatch(BaseModel):
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    context_rounds: Optional[int] = None
    theme: Optional[str] = None
    stream: Optional[bool] = None
    system_note: Optional[str] = None
    image_api_base: Optional[str] = None
    image_api_key: Optional[str] = None   # 兼容旧请求；后端会忽略
    image_model: Optional[str] = None
    image_size: Optional[str] = None


class TestIn(BaseModel):
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    image_api_base: Optional[str] = None
    image_api_key: Optional[str] = None
    image_model: Optional[str] = None
    type: Optional[str] = "all"   # all | chat | image


# ----- 角色卡 -----
class CharacterIn(BaseModel):
    id: Optional[str] = None
    name: str = "未命名角色"
    avatar: str = ""
    persona: str = ""
    personality: str = ""
    speaking_style: str = ""
    example_dialogues: str = ""
    world_setting: str = ""
    greeting: str = ""
    tags: str = ""
    refs: Optional[list] = None
    personality_traits: Optional[dict] = None   # 角色系统 V1：结构化人格参数


# ----- 记忆 -----
class MemoryIn(BaseModel):
    content: str


# ----- 会话 -----
class ConversationIn(BaseModel):
    character_id: str
    title: Optional[str] = "新对话"


class BackgroundIn(BaseModel):
    background: str = ""   # 图片 URL / dataURL / CSS 渐变字符串


class SummarizeIn(BaseModel):
    rounds: Optional[int] = 20   # 取最近多少轮对话用于总结


# ----- 聊天 -----
class ChatIn(BaseModel):
    conversation_id: str
    user_message: str
