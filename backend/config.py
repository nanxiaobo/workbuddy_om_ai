"""
config.py —— 全局配置（API 地址 / 密钥 / 模型 / 主题等）
-----------------------------------------------------------------
设计原则：
  1. 不写死任何 API 密钥，全部由前端「设置面板」写入，后端持久化到 config.json。
  2. 配置文件位于 backend/config.json，与代码分离，方便迁移与备份。
  3. 默认给出阿里云灵积 DashScope 示例值，用户可在设置面板切换为本地 Ollama 等。
"""
import json
import os

# 配置文件路径（与本文件同目录）
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

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
