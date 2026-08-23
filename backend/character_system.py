"""
character_system.py —— 角色系统 V1：人格 / 情绪 / 关系 / Character Brain
-----------------------------------------------------------------
设计原则：
  1. 人格长期稳定，不受单次对话影响。
  2. 情绪渐进变化，不会因一句话剧变。
  3. 关系通过长期互动缓慢演变，有阶段晋升。
  4. Character Brain 是纯代码规则，不调用 LLM。
  5. 每轮聊天只增加一次主 LLM 调用，情绪/关系更新全部用代码完成。

数据结构：
  personality: {温柔, 共情, 自信, 内向, 理性, 幽默, 独立, 好奇,
               耐心, 诚实, 调皮, 敏感, 嫉妒, 占有}  各 0~100
  emotion:     {开心, 悲伤, 生气, 焦虑, 孤独, 兴奋, 害羞, 嫉妒, 好感, 精力}  各 0~100
  relation:    {熟悉度, 信任, 好感, 依赖, 尊重, 嫉妒, 矛盾, 亲密度}  各 0~100
               + stage: 0~7
"""
import json
import re
import random
from datetime import datetime, timezone

# =====================================================================
# 默认值
# =====================================================================

PERSONALITY_TRAITS = [
    "温柔", "共情", "自信", "内向", "理性", "幽默", "独立", "好奇",
    "耐心", "诚实", "调皮", "敏感", "嫉妒", "占有",
]

EMOTION_KEYS = [
    "开心", "悲伤", "生气", "焦虑", "孤独", "兴奋", "害羞", "嫉妒", "好感", "精力",
]

RELATION_KEYS = [
    "熟悉度", "信任", "好感", "依赖", "尊重", "嫉妒", "矛盾", "亲密度",
]

RELATION_STAGES = [
    "陌生", "认识", "熟悉", "朋友", "亲密朋友", "暧昧", "恋爱", "深度关系",
]

DEFAULT_PERSONALITY = {k: 50 for k in PERSONALITY_TRAITS}
DEFAULT_EMOTION = {
    "开心": 30, "悲伤": 10, "生气": 5, "焦虑": 10, "孤独": 15,
    "兴奋": 20, "害羞": 20, "嫉妒": 5, "好感": 30, "精力": 60,
}
DEFAULT_RELATION = {k: 0 for k in RELATION_KEYS}
DEFAULT_RELATION["stage"] = 0


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# =====================================================================
# 解析 / 持久化辅助（与 db.py 配合）
# =====================================================================

def parse_personality(raw) -> dict:
    """从 characters.personality_json 解析；空或损坏返回默认值。"""
    if not raw:
        return dict(DEFAULT_PERSONALITY)
    if isinstance(raw, dict):
        base = dict(DEFAULT_PERSONALITY)
        base.update({k: _clamp(int(v)) for k, v in raw.items() if k in PERSONALITY_TRAITS})
        return base
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
        base = dict(DEFAULT_PERSONALITY)
        base.update({k: _clamp(int(v)) for k, v in d.items() if k in PERSONALITY_TRAITS})
        return base
    except Exception:
        return dict(DEFAULT_PERSONALITY)


def parse_emotion(raw) -> dict:
    """从 characters.emotion_json 解析；空或损坏返回默认值。"""
    if not raw:
        return dict(DEFAULT_EMOTION)
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
        base = dict(DEFAULT_EMOTION)
        base.update({k: _clamp(int(v)) for k, v in d.items() if k in EMOTION_KEYS})
        return base
    except Exception:
        return dict(DEFAULT_EMOTION)


def parse_relation(raw) -> dict:
    """从 character_relations 行解析；空或损坏返回默认值。"""
    if not raw:
        return dict(DEFAULT_RELATION)
    try:
        if isinstance(raw, dict):
            d = raw
        else:
            d = json.loads(raw)
        base = dict(DEFAULT_RELATION)
        base.update({k: _clamp(int(v)) for k, v in d.items() if k in RELATION_KEYS})
        base["stage"] = int(d.get("stage", 0))
        return base
    except Exception:
        return dict(DEFAULT_RELATION)


def personality_to_json(p: dict) -> str:
    return json.dumps(p, ensure_ascii=False)


def emotion_to_json(e: dict) -> str:
    return json.dumps(e, ensure_ascii=False)


def relation_to_json(r: dict) -> str:
    return json.dumps(r, ensure_ascii=False)


# =====================================================================
# 消息分析（纯代码，不调 LLM）
# =====================================================================

# 关键词分类（匹配后给对应信号）
_POSITIVE_KEYWORDS = [
    "喜欢", "爱", "想你", "想念", "关心", "照顾", "心疼", "加油", "支持",
    "谢谢", "感谢", "真好", "好棒", "厉害", "可爱", "漂亮", "帅", "温柔",
    "陪我", "在一起", "别走", "回来", "等你", "记住", "记得",
    "生日快乐", "礼物", "惊喜", "开心", "高兴", "笑",
]
_NEGATIVE_KEYWORDS = [
    "讨厌", "烦", "滚", "闭嘴", "傻", "蠢", "笨", "丑", "胖",
    "骂", "打", "死", "杀", "滚开", "别理我", "分手", "结束",
    "无聊", "没用", "废物", "恶心", "嫌弃", "不喜欢", "滚蛋",
]
_APOLOGY_KEYWORDS = ["对不起", "抱歉", "错了", "我的错", "道歉", "不该", "原谅"]
_QUESTION_KEYWORDS = ["?", "？", "吗", "呢", "怎么", "为什么", "什么", "哪里", "谁", "哪个", "如何"]
_ARGUMENT_KEYWORDS = ["不对", "错了", "不是", "不同意", "反驳", "但是", "可是", "然而", "胡说"]
_CARING_KEYWORDS = [
    "累不累", "饿不饿", "还好吗", "没事吧", "怎么了", "开心吗",
    "早点睡", "注意身体", "别太累", "休息", "喝水", "吃饭了吗",
]
_INTIMATE_KEYWORDS = ["亲", "抱", "牵手", "依靠", "宝贝", "亲爱的", "老婆", "老公", "恋人"]


def analyze_message(user_message: str) -> dict:
    """分析用户消息，返回信号字典。纯代码规则。"""
    msg = user_message.lower()
    return {
        "positive": sum(1 for kw in _POSITIVE_KEYWORDS if kw in msg),
        "negative": sum(1 for kw in _NEGATIVE_KEYWORDS if kw in msg),
        "apology": sum(1 for kw in _APOLOGY_KEYWORDS if kw in msg),
        "question": sum(1 for kw in _QUESTION_KEYWORDS if kw in msg),
        "argument": sum(1 for kw in _ARGUMENT_KEYWORDS if kw in msg),
        "caring": sum(1 for kw in _CARING_KEYWORDS if kw in msg),
        "intimate": sum(1 for kw in _INTIMATE_KEYWORDS if kw in msg),
        "length": len(user_message.strip()),
    }


# =====================================================================
# Character Brain —— 角色决策层（纯代码规则）
# =====================================================================

_EMOTION_LABELS = [
    (70, "非常开心"), (55, "开心"), (40, "平静"),
    (25, "低落"), (10, "难过"), (0, "非常难过"),
]


def _dominant_emotion_label(emotion: dict) -> str:
    """根据情绪数值，返回一个人类可读的情绪标签。"""
    happy = emotion.get("开心", 30)
    sad = emotion.get("悲伤", 10)
    angry = emotion.get("生气", 5)
    anxious = emotion.get("焦虑", 10)
    if angry > 60:
        return "生气"
    if anxious > 65:
        return "焦虑"
    if sad > 55:
        return "难过"
    for threshold, label in _EMOTION_LABELS:
        if happy >= threshold:
            return label
    return "平静"


def character_brain(
    character: dict,
    personality: dict,
    emotion: dict,
    relation: dict,
    user_message: str,
) -> dict:
    """
    Character Brain：在调用 LLM 前做角色决策。
    返回 {emotion_label, attitude, intent, style, hints}
    纯代码规则，不调用 LLM。
    """
    signals = analyze_message(user_message)

    # --- 态度：基于关系好感 + 当前情绪 ---
    affection = relation.get("好感", 0)
    trust = relation.get("信任", 0)
    happy = emotion.get("开心", 30)
    angry = emotion.get("生气", 5)

    if affection > 70 and trust > 60:
        attitude = "深情"
    elif affection > 50:
        attitude = "温暖" if happy > 30 else "关切"
    elif affection > 25:
        attitude = "友善" if angry < 30 else "有点不高兴"
    elif affection > 0:
        attitude = "客气"
    else:
        attitude = "疏离"

    # 内向人格降低态度的张扬程度
    if personality.get("内向", 50) > 70:
        attitude = "内敛" if "温暖" in attitude or "深情" in attitude else attitude

    # --- 意图：基于用户消息类型 ---
    if signals["negative"] > 0:
        intent = "defend_or_hurt"        # 被攻击/被伤害
    elif signals["apology"] > 0:
        intent = "consider_forgiveness"  # 考虑是否原谅
    elif signals["argument"] > 0:
        intent = "express_own_view"      # 表达自己的观点
    elif signals["caring"] > 0:
        intent = "accept_care"           # 接受关心
    elif signals["intimate"] > 0:
        intent = "respond_to_intimacy"   # 回应亲密
    elif signals["question"] > 0:
        intent = "answer"                 # 回答问题
    elif signals["positive"] > 0:
        intent = "reciprocate_warmth"     # 回应温暖
    else:
        intent = "continue_conversation"  # 正常聊天

    # --- 风格：基于人格 ---
    style_parts = []
    if personality.get("幽默", 50) > 65:
        style_parts.append("幽默")
    if personality.get("温柔", 50) > 65:
        style_parts.append("温柔")
    if personality.get("调皮", 50) > 65:
        style_parts.append("调皮")
    if personality.get("内向", 50) > 65:
        style_parts.append("含蓄")
    if personality.get("理性", 50) > 65:
        style_parts.append("理性")
    if personality.get("独立", 50) > 65:
        style_parts.append("独立")
    if not style_parts:
        style_parts.append("自然")
    style = "、".join(style_parts[:2])

    # --- 是否表现情绪 ---
    show_emotion = (
        personality.get("敏感", 50) > 50
        or emotion.get("开心", 0) > 60
        or emotion.get("悲伤", 0) > 40
        or emotion.get("生气", 0) > 40
    )

    # --- 回复提示（注入 prompt 的指令） ---
    hints = []
    # 反对盲目同意：用户提出观点时，根据自信/独立/诚实人格决定是否表达不同意见
    if signals["argument"] > 0 and personality.get("独立", 50) > 50:
        hints.append("用户在表达不同意见时，你也有自己的立场，不必一味附和，可以自然地表达你的看法")
    # 不要过度温柔
    if personality.get("温柔", 50) < 40 and signals["caring"] > 0:
        hints.append("你不太擅长回应关心，可能会有些别扭或不自在，不必每次都温柔接受")
    # 被伤害时不要立刻原谅
    if signals["negative"] > 0 and emotion.get("生气", 0) > 40:
        hints.append("你现在还在生气，不要立刻原谅或表现得太宽容")
    # 道歉后根据信任决定原谅速度
    if signals["apology"] > 0:
        if trust < 30:
            hints.append("你对用户的信任不够，即使对方道歉也不会马上原谅，需要时间")
        elif trust > 60 and emotion.get("生气", 0) < 40:
            hints.append("你信任用户，愿意给出缓和的态度，但不必立刻完全原谅")

    emotion_label = _dominant_emotion_label(emotion)

    return {
        "emotion_label": emotion_label,
        "attitude": attitude,
        "intent": intent,
        "style": style,
        "show_emotion": show_emotion,
        "hints": hints,
    }


# =====================================================================
# 情绪更新（纯代码，渐进变化）
# =====================================================================

def update_emotion(
    emotion: dict,
    personality: dict,
    signals: dict,
    brain: dict,
) -> dict:
    """
    根据本轮用户消息信号 + Character Brain 决策，渐进更新情绪。
    每项变化幅度 1~8 点，不会剧变。
    """
    e = dict(emotion)
    sensitive = personality.get("敏感", 50) / 50.0   # 敏感度高→情绪变化幅度大
    dampener = 0.6 if personality.get("理性", 50) > 60 else 1.0  # 理性高→情绪变化幅度小

    def adj(key, delta):
        e[key] = _clamp(e.get(key, 0) + round(delta * sensitive * dampener))

    pos = signals["positive"]
    neg = signals["negative"]
    apo = signals["apology"]
    car = signals["caring"]
    arg = signals["argument"]
    intm = signals["intimate"]

    # 正面互动：开心↑ 好感↑ 孤独↓
    if pos:
        adj("开心", +pos * 3)
        adj("好感", +pos * 2)
        adj("孤独", -pos * 2)
        adj("生气", -pos * 1.5)

    # 关心：开心↑ 好感↑ 焦虑↓
    if car:
        adj("开心", +car * 2.5)
        adj("好感", +car * 2)
        adj("焦虑", -car * 2)
        adj("孤独", -car * 3)

    # 亲密：害羞↑ 兴奋↑ 好感↑
    if intm:
        adj("害羞", +intm * 4)
        adj("兴奋", +intm * 2)
        adj("好感", +intm * 2)

    # 负面：生气↑ 悲伤↑ 好感↓
    if neg:
        adj("生气", +neg * 5)
        adj("悲伤", +neg * 2)
        adj("好感", -neg * 3)
        adj("开心", -neg * 3)

    # 争论：生气小幅↑
    if arg:
        adj("生气", +arg * 1.5)

    # 道歉：生气↓ 但不立刻归零
    if apo:
        adj("生气", -apo * 3)
        adj("好感", +apo * 1)

    # 精力自然衰减（每轮 -1~2）
    adj("精力", -1.5)

    # 情绪自然回归中性（开心/悲伤/生气都缓慢趋向中间值）
    for key, neutral in [("开心", 35), ("悲伤", 10), ("生气", 5), ("焦虑", 10), ("兴奋", 20), ("害羞", 15)]:
        cur = e.get(key, neutral)
        if cur > neutral:
            e[key] = _clamp(cur - 1)
        elif cur < neutral:
            e[key] = _clamp(cur + 0.5)

    return e


# =====================================================================
# 关系更新（纯代码，缓慢演变）
# =====================================================================

def update_relation(
    relation: dict,
    emotion: dict,
    signals: dict,
    brain: dict,
) -> dict:
    """
    根据本轮互动，缓慢更新关系指标 + 自动阶段晋升。
    变化幅度比情绪更小（0.5~3 点），需要长期积累。
    """
    r = dict(relation)

    def adj(key, delta):
        r[key] = _clamp(r.get(key, 0) + delta)

    pos = signals["positive"]
    neg = signals["negative"]
    apo = signals["apology"]
    car = signals["caring"]
    arg = signals["argument"]
    intm = signals["intimate"]

    # 任何有效互动都微增熟悉度
    if signals["length"] > 2:
        adj("熟悉度", +0.5)

    if pos:
        adj("好感", +pos * 1.5)
        adj("信任", +pos * 0.8)
        adj("亲密度", +pos * 1)
        adj("矛盾", -pos * 0.5)

    if car:
        adj("好感", +car * 1.5)
        adj("信任", +car * 1)
        adj("尊重", +car * 0.8)

    if intm:
        adj("亲密度", +intm * 2)
        adj("好感", +intm * 1)
        adj("依赖", +intm * 0.5)

    if neg:
        adj("矛盾", +neg * 3)
        adj("好感", -neg * 2)
        adj("尊重", -neg * 1.5)
        adj("信任", -neg * 1)

    if arg:
        adj("矛盾", +arg * 0.8)

    if apo:
        adj("矛盾", -apo * 2)
        adj("好感", +apo * 0.5)

    # 嫉妒/占有：如果用户提到其他角色或表现出疏远，可能微升（此处简化）
    # 留作扩展位，V1 不做复杂逻辑

    # 阶段自动晋升（需要好感 + 熟悉度 + 信任同时达标）
    _auto_promote_stage(r)

    return r


def _auto_promote_stage(r: dict):
    """根据好感/熟悉度/信任/亲密度自动晋升关系阶段。"""
    affection = r.get("好感", 0)
    familiarity = r.get("熟悉度", 0)
    trust = r.get("信任", 0)
    intimacy = r.get("亲密度", 0)
    tension = r.get("矛盾", 0)

    # 阶段门槛（好感, 熟悉度, 信任, 亲密度）
    thresholds = [
        (0, 0, 0, 0),         # 0 陌生
        (5, 5, 3, 0),          # 1 认识
        (15, 15, 10, 5),       # 2 熟悉
        (30, 30, 20, 15),      # 3 朋友
        (45, 45, 35, 30),      # 4 亲密朋友
        (60, 55, 50, 45),       # 5 暧昧
        (75, 70, 65, 65),      # 6 恋爱
        (90, 85, 80, 85),      # 7 深度关系
    ]

    best = 0
    for i, (a, f, t, im) in enumerate(thresholds):
        if affection >= a and familiarity >= f and trust >= t and intimacy >= im:
            best = i

    # 矛盾过高时降一级（但不低于 0）
    if tension > 60 and best > 0:
        best = max(0, best - 1)

    r["stage"] = best


def stage_name(stage: int) -> str:
    """返回阶段中文名。"""
    if 0 <= stage < len(RELATION_STAGES):
        return RELATION_STAGES[stage]
    return RELATION_STAGES[0]


# =====================================================================
# Prompt 构造辅助（注入到 build_system_prompt）
# =====================================================================

def build_personality_context(personality: dict) -> str:
    """把结构化人格参数格式化为 prompt 文本。"""
    lines = []
    for trait in PERSONALITY_TRAITS:
        v = personality.get(trait, 50)
        if v >= 75:
            lines.append(f"{trait}（很强）")
        elif v >= 60:
            lines.append(f"{trait}（偏强）")
        elif v <= 25:
            lines.append(f"{trait}（很弱）")
        elif v <= 40:
            lines.append(f"{trait}（偏弱）")
    if not lines:
        return ""
    return "、".join(lines)


def build_emotion_context(emotion: dict) -> str:
    """把当前情绪格式化为 prompt 文本。"""
    parts = []
    for key in EMOTION_KEYS:
        v = emotion.get(key, 0)
        if v >= 60:
            parts.append(f"{key}({int(v)})")
    if not parts:
        return "情绪平稳"
    return "、".join(parts)


def build_relation_context(relation: dict) -> str:
    """把当前关系格式化为 prompt 文本。"""
    sn = stage_name(relation.get("stage", 0))
    affection = relation.get("好感", 0)
    trust = relation.get("信任", 0)
    intimacy = relation.get("亲密度", 0)
    tension = relation.get("矛盾", 0)
    parts = [f"关系阶段：{sn}"]
    if affection > 0:
        parts.append(f"好感{int(affection)}")
    if trust > 0:
        parts.append(f"信任{int(trust)}")
    if intimacy > 0:
        parts.append(f"亲密度{int(intimacy)}")
    if tension > 30:
        parts.append(f"矛盾{int(tension)}")
    return "，".join(parts)


def build_brain_directives(brain: dict) -> str:
    """把 Character Brain 的决策转化为给 LLM 的指令文本。"""
    lines = []
    lines.append(f"当前情绪：{brain['emotion_label']}")
    lines.append(f"对用户的态度：{brain['attitude']}")
    lines.append(f"回复意图：{_INTENT_LABELS.get(brain['intent'], brain['intent'])}")
    lines.append(f"回复风格：{brain['style']}")
    if not brain["show_emotion"]:
        lines.append("（当前不需要强烈表现情绪，保持自然即可）")
    for h in brain["hints"]:
        lines.append(f"· {h}")
    return "\n".join(lines)


_INTENT_LABELS = {
    "defend_or_hurt": "被冒犯，需要表达不满",
    "consider_forgiveness": "对方在道歉，考虑是否原谅",
    "express_own_view": "表达自己的观点（可以不同意用户）",
    "accept_care": "接受用户的关心",
    "respond_to_intimacy": "回应亲密举动",
    "answer": "回答用户的问题",
    "reciprocate_warmth": "回应用户的善意",
    "continue_conversation": "自然延续对话",
}


# =====================================================================
# 降 AI 味指令（注入 system prompt 底部）
# =====================================================================

ANTI_AI_RULES = """【自然度要求（降低 AI 味）】
· 不要每轮都说"我理解你的感受""谢谢你和我分享""我会一直陪着你"这类客服腔。
· 不要每轮都总结用户说的话。
· 不要每轮都加动作描写（*动作*），只在情绪波动或需要画面感时自然融入。
· 不要每轮都用昵称称呼用户。
· 不要机械重复角色设定或自我介绍。
· 不要用户说什么都同意——你有自己的偏好和立场。
· 不要用户一道歉就立刻原谅——情绪需要时间消化。
· 不要每次都表现温柔——根据你的人格和当前情绪自然反应。
· 回复长短自然变化：简单问题简短回，复杂话题才多说。
· 像真人发消息一样，有时一句话就够，不必每次都长篇大论。"""
