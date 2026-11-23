"""判断当前人格的性别，决定这个插件要不要生效。

只做一件事：读人设文本 → 打分 → female / male / other / unknown。
不打模型、不联网；读不到人设时按 unknown 处理，交给配置决定。

为什么读人格而不是读聊天里的 system prompt：
private_companion 会把大量生活材料追加进 system prompt，里面「他」指的是主人，
按整段 system prompt 统计代词会把女性人设判成男性。所以优先读 AstrBot
人格库里的原始人设文本。
"""

from __future__ import annotations

import re

# 明确写出来的性别：权重最高
# 兼容「性别为：女」「性别：女」「性别女」「性别是 女性」这些写法
_EXPLICIT_FEMALE = (
    re.compile(r"性别\s*[:：]?\s*(?:为|是)?\s*[:：]?\s*女"),
    re.compile(r"是\s*(?:一|个)?\s*(?:女性|女生|女孩|女孩子)"),
    re.compile(r"(?:女性|女)\s*角色"),
)
_EXPLICIT_MALE = (
    re.compile(r"性别\s*[:：]?\s*(?:为|是)?\s*[:：]?\s*男"),
    re.compile(r"是\s*(?:一|个)?\s*(?:男性|男生|男孩|男孩子)"),
    re.compile(r"(?:男性|男)\s*角色"),
)
# 只有明确写"没有性别/性别为无"才算其他；不能因为出现"程序""AI助手"就判，
# 人设里常见的"你不是一个普通的AI助手"会把女性人设误判成非人类。
_EXPLICIT_OTHER = (
    re.compile(r"性别\s*[:：]?\s*(?:为|是)?\s*[:：]?\s*(?:无|无性别|其他|未知|不适用)"),
    re.compile(r"(?:无性别|没有性别|不分性别)"),
)

_FEMALE_WORDS = (
    "女生", "女孩", "女孩子", "少女", "女仆", "女性", "女人", "姐姐", "妹妹",
    "姑娘", "妹子", "少女感", "女儿", "妈妈", "娘", "萝莉", "御姐", "人妻",
)
_MALE_WORDS = (
    "男生", "男孩", "男孩子", "少年", "男性", "男人", "哥哥", "弟弟",
    "小伙子", "大叔", "父亲", "爸爸", "正太", "男仆", "少爷",
)
# 代词只做弱信号：中文里「他」常被当通用代词
_FEMALE_PRONOUN = "她"
_MALE_PRONOUN = "他"

_MAX_SCAN = 20000


def _count(text: str, words) -> int:
    return sum(text.count(word) for word in words)


def score_gender(text: str) -> dict:
    """给一段人设文本打分。

    返回 {"female": float, "male": float, "other": bool, "evidence": [...]}。
    """
    body = (text or "")[:_MAX_SCAN]
    female = 0.0
    male = 0.0
    evidence: list[str] = []

    for pattern in _EXPLICIT_FEMALE:
        if pattern.search(body):
            female += 10.0
            evidence.append("明确写了女性")
            break
    for pattern in _EXPLICIT_MALE:
        if pattern.search(body):
            male += 10.0
            evidence.append("明确写了男性")
            break

    words_f = _count(body, _FEMALE_WORDS)
    words_m = _count(body, _MALE_WORDS)
    if words_f:
        female += min(6.0, words_f * 1.5)
        evidence.append(f"女性词 {words_f} 处")
    if words_m:
        male += min(6.0, words_m * 1.5)
        evidence.append(f"男性词 {words_m} 处")

    pronouns_f = body.count(_FEMALE_PRONOUN)
    pronouns_m = body.count(_MALE_PRONOUN)
    if pronouns_f or pronouns_m:
        female += min(4.0, pronouns_f * 0.4)
        male += min(2.0, pronouns_m * 0.2)   # 通用代词，只算一半
        evidence.append(f"她 {pronouns_f} / 他 {pronouns_m}")

    other = any(pattern.search(body) for pattern in _EXPLICIT_OTHER)

    return {"female": female, "male": male, "other": other, "evidence": evidence}


def verdict_from_scores(scores: dict) -> str:
    """female / male / other / unknown。要求有明显差距，避免模棱两可。"""
    if scores.get("other"):
        return "other"
    female = float(scores.get("female") or 0.0)
    male = float(scores.get("male") or 0.0)
    if female <= 0 and male <= 0:
        return "unknown"
    if female >= male * 1.25 and female > 0:
        return "female"
    if male >= female * 1.25 and male > 0:
        return "male"
    return "unknown"


def classify(persona_text: str) -> dict:
    scores = score_gender(persona_text)
    return {
        "gender": verdict_from_scores(scores),
        "scores": scores,
        "evidence": "；".join(scores.get("evidence") or []) or "人设里没有性别线索",
        "chars": len(persona_text or ""),
    }


def persona_text(context, name_hint: str = "") -> tuple[str, str]:
    """从 AstrBot 人格库里取人设原文。

    返回 (文本, 来源说明)。取不到返回 ("", 原因)。
    """
    persona_name = (name_hint or "").strip()
    manager = getattr(context, "persona_manager", None) if context is not None else None
    if manager is not None:
        personas = getattr(manager, "personas_v3", None) or []
        for item in personas:
            try:
                if persona_name and item.get("name") == persona_name:
                    return str(item.get("prompt") or ""), f"人格 {persona_name}"
            except (AttributeError, TypeError):
                continue
        if not persona_name:
            default = getattr(manager, "selected_default_persona_v3", None) or {}
            try:
                text = str(default.get("prompt") or "")
            except (AttributeError, TypeError):
                text = ""
            if text:
                return text, "默认人格"
        # 指定了人格名但没找到：列出可用名字方便排错
        names = []
        for item in personas:
            try:
                names.append(str(item.get("name") or ""))
            except (AttributeError, TypeError):
                continue
        return "", f"人格库里没有 {persona_name or '默认人格'}（现有：{', '.join(n for n in names if n) or '空'}）"

    return "", "取不到人格管理器"


def resolve(context, settings, name: str | None = None) -> dict:
    """综合配置和人格，给出最终判断。

    配置 gender_mode：
      auto  → 读人格判断
      female/male/other → 直接指定（跳过判断）
      off   → 直接判定为不适合
    配置 unknown_gender_policy：人格判不出来时 allow / deny。
    name 用来覆盖 settings 里的 persona_name（比如按当前会话实际人格）。
    """
    mode = settings.str("gender_mode").lower() or "auto"
    persona_name = (name if name is not None else settings.str("persona_name")).strip()
    result = {
        "mode": mode,
        "suitable": True,
        "gender": "unknown",
        "source": "config",
        "evidence": "",
        "policy": settings.str("unknown_gender_policy").lower() or "allow",
        "persona_name": persona_name,
    }

    if not settings.bool("enabled"):
        result.update(suitable=False, gender="unknown", source="总开关", evidence="插件总开关关闭")
        return result

    if mode == "off":
        result.update(suitable=False, gender="disabled", source="config",
                      evidence="gender_mode=off，人工关闭")
        return result
    if mode in ("female", "male", "other"):
        result.update(gender=mode, source="config", evidence=f"配置指定 {mode}")
        result["suitable"] = mode == "female"
        return result

    text, source = persona_text(context, persona_name)
    if not text:
        result.update(gender="unknown", source=source, evidence=source)
        result["suitable"] = result["policy"] != "deny"
        return result

    verdict = classify(text)
    result.update(
        gender=verdict["gender"],
        source=source,
        evidence=verdict["evidence"],
        scores=verdict["scores"],
    )
    if verdict["gender"] == "female":
        result["suitable"] = True
    elif verdict["gender"] == "unknown":
        result["suitable"] = result["policy"] != "deny"
    else:
        result["suitable"] = False
    return result


def describe(result: dict) -> str:
    label = {
        "female": "女", "male": "男", "other": "其他/非人类",
        "unknown": "判不出来", "disabled": "已关闭",
    }.get(result.get("gender"), result.get("gender") or "?")
    state = "适合" if result.get("suitable") else "不适合（插件不生效）"
    lines = [
        f"人格性别：{label} → {state}",
        f"来源：{result.get('source') or '—'}",
        f"依据：{result.get('evidence') or '—'}",
    ]
    if result.get("gender") == "unknown":
        lines.append(f"判不出来时的策略：{result.get('policy')}（allow=照常生效 / deny=不生效）")
    return "｜".join(lines)
