"""小玩具：跳蛋、振动棒、吸吮器、按摩棒、肛塞、乳夹。

每个玩具有固定部位和基础快感，强度 1–3 倍率不同；
用一次只涨快感、不判定受孕，会在身体上留一段"还在用"的状态，
状态栏和提示词都能感知。
"""

from __future__ import annotations

from . import body, util
from .settings import Settings

TOY_ORDER = ("bullet", "vibrator", "sucker", "wand", "plug", "clamp",
             "massage_gun")

TOY_CATALOG = {
    "bullet": {"label": "跳蛋", "zone": "vulva", "pleasure": 8.0,
               "keywords": ("跳蛋", "小跳蛋", "震动蛋")},
    "vibrator": {"label": "振动棒", "zone": "vagina", "pleasure": 12.0,
                 "keywords": ("振动棒", "按摩棒插", "棒子插")},
    "sucker": {"label": "吸吮器", "zone": "vulva", "pleasure": 10.0,
               "keywords": ("吸吮器", "吮吸器", "吸阴")},
    "wand": {"label": "按摩棒", "zone": "vulva", "pleasure": 9.0,
             "keywords": ("按摩棒", "魔杖")},
    "plug": {"label": "肛塞", "zone": "anus", "pleasure": 7.0,
             "keywords": ("肛塞", "后庭塞")},
    "clamp": {"label": "乳夹", "zone": "nipple", "pleasure": 6.0,
              "keywords": ("乳夹", "乳头夹")},
    "massage_gun": {"label": "筋膜枪", "zone": "belly", "pleasure": 10.0,
                    "keywords": ("筋膜枪", "按摩枪", "冲击枪")},
}

TOY_PLACES = {
    "bullet": ("vulva", "vagina", "anus"),
    "vibrator": ("vagina", "anus"),
    "sucker": ("vulva",),
    "wand": ("vulva",),
    "plug": ("anus",),
    "clamp": ("nipple",),
    "massage_gun": ("belly", "breast", "foot", "hand", "leg", "vulva", "clitoris",
                    "vagina", "anus"),
}

PLACE_LABELS = {"vulva": "外阴", "vagina": "阴道", "anus": "肛", "nipple": "乳头",
                "belly": "小腹", "breast": "乳房", "clitoris": "阴蒂", "foot": "脚",
                "hand": "手", "leg": "腿"}
PLACE_ALIASES = {
    "外": "vulva", "外阴": "vulva", "外面": "vulva", "外部": "vulva",
    "内": "vagina", "内部": "vagina", "阴道": "vagina", "里面": "vagina",
    "肛": "anus", "后": "anus", "后庭": "anus", "肛门": "anus",
    "乳头": "nipple",
    "小腹": "belly", "肚子": "belly", "腹部": "belly",
    "乳房": "breast", "胸": "breast",
    "阴蒂": "clitoris", "clit": "clitoris",
    "脚": "foot", "足": "foot", "手": "hand", "腿": "leg",
}

INTENSITY_LABELS = {1: "轻柔", 2: "中等", 3: "强烈"}
INTENSITY_SCALE = {1: 0.8, 2: 1.15, 3: 1.6}


def normalize_toy(value: str) -> str:
    key = str(value or "").strip().lower()
    if key in TOY_CATALOG:
        return key
    aliases = {"跳蛋": "bullet", "振动棒": "vibrator", "吸吮器": "sucker",
               "吮吸器": "sucker", "按摩棒": "wand", "肛塞": "plug",
               "乳夹": "clamp", "乳头夹": "clamp"}
    return aliases.get(key, aliases.get(str(value or "").strip(), ""))


def toy_places(toy: str) -> tuple[str, ...]:
    return TOY_PLACES.get(toy, (TOY_CATALOG[toy]["zone"],))


def normalize_place(toy: str, value: str) -> str:
    """把"内部/阴道/肛/外阴"等说法换成这个玩具支持的部位。"""
    key = PLACE_ALIASES.get(str(value or "").strip().lower(), "")
    if key and key in toy_places(toy):
        return key
    if str(value or "").strip() in ("内", "内部", "里面") and "vagina" in toy_places(toy):
        return "vagina"
    return TOY_CATALOG[toy]["zone"]


def toy_enabled(settings: Settings, toy: str) -> bool:
    if not settings.bool("toys.enabled"):
        return False
    if toy == "massage_gun":  # 筋膜枪一直可用
        return True
    return settings.bool(f"toys.{toy}_enabled")


def toy_outside(settings: Settings, toy: str) -> bool:
    """不在受孕活动（亲密场景）里时，这个玩具能不能用。"""
    if toy == "massage_gun":  # 一直可以用
        return True
    return settings.bool(f"toys.{toy}_outside")


def toy_pleasure(settings: Settings, toy: str) -> float:
    override = settings.float(f"toys.{toy}_pleasure", 0.0, 100.0)
    return round(override if override > 0 else TOY_CATALOG[toy]["pleasure"], 2)


def toy_gain(settings: Settings, toy: str, intensity: int = 2) -> float:
    intensity = min(3, max(1, int(intensity or 2)))
    scale = settings.float("toys.intensity_scale", 0.0, 5.0) or 1.0
    return round(toy_pleasure(settings, toy) * INTENSITY_SCALE[intensity] * scale, 2)


def _active_span(settings: Settings) -> float:
    return max(1, settings.int("toys.active_minutes", 1, 240)) * 60


def active_toy(state: dict, settings: Settings, now: float | None = None) -> dict | None:
    now = now or util.now_ts()
    toy = state.get("toy")
    if not isinstance(toy, dict) or not toy.get("key"):
        return None
    at = util.safe_float(toy.get("at"), 0.0)
    if not at or now - at > _active_span(settings):
        return None
    return toy


def toys_payload(settings: Settings, state: dict | None = None,
                 now: float | None = None) -> list[dict]:
    active = active_toy(state, settings, now) if isinstance(state, dict) else None
    rows = []
    for toy in TOY_ORDER:
        info = TOY_CATALOG[toy]
        rows.append({
            "key": toy,
            "label": info["label"],
            "zone": info["zone"],
            "places": [{"key": place, "label": PLACE_LABELS[place]}
                       for place in toy_places(toy)],
            "enabled": toy_enabled(settings, toy),
            "outside": toy_outside(settings, toy),
            "pleasure": toy_pleasure(settings, toy),
            "gain": toy_gain(settings, toy, 2) if toy_enabled(settings, toy) else 0.0,
            "gains": {level: (toy_gain(settings, toy, level)
                              if toy_enabled(settings, toy) else 0.0)
                      for level in (1, 2, 3)},
            "active": bool(active and active.get("key") == toy),
            "intensity": util.safe_int((active or {}).get("intensity"), 0),
            "place": ((active or {}).get("place") or info["zone"])
                     if (active and active.get("key") == toy) else "",
        })
    return rows


def apply_toy(state: dict, settings: Settings, toy: str, intensity: int = 2,
              now: float | None = None, place: str = "") -> dict:
    """用一次玩具：涨快感，并记下"还在用"的状态。"""
    from . import state as state_mod  # 避免循环导入

    now = now or util.now_ts()
    intensity = min(3, max(1, int(intensity or 2)))
    craving = state_mod.edge_gain_multiplier(state, settings, now)
    gain = round(toy_gain(settings, toy, intensity) * craving * body.pleasure_scale(settings, state), 2)
    before = util.safe_float(state.get("pleasure"), 0.0)
    value = state_mod.add_pleasure(state, settings, gain, now=now)
    place_key = normalize_place(toy, place)
    state["toy"] = {"key": toy, "intensity": intensity, "at": now,
                    "place": place_key}
    counts = state.setdefault("toys_used", {})
    counts[toy] = util.safe_int(counts.get(toy), 0) + 1
    return {
        "key": toy,
        "label": TOY_CATALOG[toy]["label"],
        "zone": place_key,
        "place": place_key,
        "place_label": PLACE_LABELS.get(place_key, ""),
        "intensity": intensity,
        "intensity_label": INTENSITY_LABELS[intensity],
        "gain": gain,
        "before": before,
        "value": value,
    }


def clear_toy(state: dict) -> None:
    state["toy"] = None


def detect_toy(text: str, settings: Settings) -> str:
    body = (text or "").lower()
    if not body:
        return ""
    for toy in TOY_ORDER:
        if not toy_enabled(settings, toy):
            continue
        if any(word.lower() in body for word in TOY_CATALOG[toy]["keywords"]):
            return toy
    return ""


def describe(settings: Settings, toy: str, intensity: int) -> str:
    label = TOY_CATALOG.get(toy, {}).get("label", toy)
    return f"{label}（{INTENSITY_LABELS.get(intensity, intensity)}）"
