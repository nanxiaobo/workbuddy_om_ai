"""
config.py —— 全局配置（API 地址 / 密钥 / 模型 / 主题等）
-----------------------------------------------------------------
设计原则：
  1. 不写死任何 API 密钥，全部由用户在「设置面板」或「用户管理」写入，存到 db.users.api_key。
  2. 配置文件位于 backend/config.json，仅保存非密钥字段（api_base / model / temperature 等）。
  3. 默认给出阿里云灵积 DashScope 示例值，用户可在设置面板切换为本地 Ollama 等。

多用户密钥隔离（v4）：
  - 不再有「系统共享 key」概念。每个用户（含 admin）的对话 Key 存 db.users.api_key，
    图像 Key 存 db.users.image_api_key；两者完全独立，可不同。
  - LLM 调用时调 get_effective_config(username)：仅取该用户的两份 key。
  - 图像生成调用 (llm.py / chat.py) 优先用 image_api_key，空串则回退到 api_key。
"""
import json
import os

from typing import Optional

# 配置文件路径：backend/data/config.json
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(_DATA_DIR, "config.json")# 配置文件路径：backend/data/config.json
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(_DATA_DIR, "config.json")

# 默认配置：示例使用阿里云灵积 DashScope 的 OpenAI 兼容接口
# 用户可在设置面板自由切换为本地 Ollama 或其他兼容服务
DEFAULT_CONFIG = {
    "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",  # 灵积 OpenAI 兼容接口
    "api_key": "",                                                   # 填写你的 DashScope API Key
    "model": "qwen-turbo",                                           # DashScope 常见模型：qwen-turbo / qwen-plus / qwen-max / qwen2.5-7b-instruct 等
    "temperature": 0.9,                       # 温度：越高越发散/有创意
    "max_tokens": 512,                        # AI 单次回复最大长度（回复长度滑杆）
    "context_rounds": 30,                    # 上下文记忆轮数（记住最近 N 轮）
    "theme": "dark",                          # 主题：dark / light
    "stream": True,                           # 是否流式输出
    "system_note": "",                        # 全局追加提示（可选）
    # 图像生成（根据最近聊天生成人物当前状态图，可选；留空则只返回文字描述）
    "image_api_base": "",                     # OpenAI 兼容图像接口，如 https://api.openai.com/v1
    "image_api_key": "",                      # 不填则复用上方 api_key
    "image_model": "dall-e-3",                # 图像模型名
    "image_size": "1024x1024",                # 生成尺寸
}


def load_config() -> dict:
    """读取配置；文件不存在时写入默认配置。"""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 补齐缺失字段，避免老配置缺键
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> dict:
    """写入配置到磁盘，自动补齐默认字段。"""
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg or {})
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged


def get_config() -> dict:
    """对外获取配置的入口。"""
    return load_config()


def update_config(patch: dict) -> dict:
    """局部更新配置。"""
    current = load_config()
    current.update(patch)
    return save_config(current)


def get_effective_config(username: Optional[str] = None) -> dict:
    """
    返回指定用户「应当使用」的配置副本：
      - api_base / model / temperature 等非密钥字段：取 config.json（系统默认）。
      - api_key：仅从 db.users.api_key 读取该用户自己的 key。空串表示「该用户尚未配置」。
      - image_api_key：从 db.users.image_api_key 独立读取；空串表示「沿用 api_key」。

    不会修改 config.json，仅返回内存对象。
    """
    # 延迟导入避免循环依赖
    import db

    cfg = load_config()
    user_key = db.get_user_api_key(username) if username else ""
    user_image_key = db.get_user_image_api_key(username) if username else ""
    cfg["api_key"] = user_key or ""
    # image_api_key 独立：用户有就用自己的，没有就回退到对话 key
    cfg["image_api_key"] = user_image_key or user_key or ""
    return cfg


def mask_config_for_non_admin(cfg: dict) -> dict:
    """
    兼容占位：v3 之后每位用户都用自己独立的 key，前端展示时不再做隐私掩码。
    保留这个函数仅为不破坏旧 import；行为是「原样返回」。
    """
    return dict(cfg)
