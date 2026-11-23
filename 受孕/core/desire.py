"""欲望来源策略：每个功能自己选读哪条欲望，或取最高。"""

from __future__ import annotations

from . import mood, tuning, util
from .settings import Settings

FEATURES = ("night_raid", "daily_scene", "wetness", "conception")
LABELS = {
    "night_raid": "夜袭",
    "daily_scene": "日常小场景",
    "wetness": "湿润度",
    "conception": "受孕概率",
}
STRATEGIES = ("mood", "fish", "dark", "max", "both")
STRATEGY_LABELS = {
    "mood": "日常情绪",
    "fish": "鱼之心",
    "dark": "暗涌",
    "max": "取最高",
    "both": "鱼之心 + 暗涌",
}
DEFAULTS = {
    "night_raid": "max",
    "daily_scene": "mood",
    "wetness": "fish",
    "conception": "both",
}


def strategy(state: dict, settings: Settings, feature: str) -> str:
    row = state.get("desire_strategy") if isinstance(
        state.get("desire_strategy"), dict) else {}
    value = str(row.get(feature) or settings.str(f"desire.{feature}") or
                DEFAULTS.get(feature, "max")).strip().lower()
    if value not in STRATEGIES:
        value = DEFAULTS.get(feature, "max")
    if feature != "conception" and value == "both":
        value = "max"
    return value


def values(state: dict, settings: Settings, *, fish=None, dark=None) -> dict:
    out = {"mood": round(util.clamp(
        mood.value_of(state, settings, "desire"), 0.0, 100.0), 2)}
    if fish is not None:
        out["fish"] = round(util.clamp(float(fish), 0.0, 100.0), 2)
    if dark is not None:
        out["dark"] = round(util.clamp(float(dark), 0.0, 100.0), 2)
    return out


def pick(state: dict, settings: Settings, feature: str, *,
         fish=None, dark=None) -> tuple[float, str, dict]:
    """返回 (值, 来源, 所有来源)，取最高时只在可用的里面取。"""
    rows = values(state, settings, fish=fish, dark=dark)
    choice = strategy(state, settings, feature)
    if choice == "max":
        if not rows:
            return 0.0, "无", rows
        source = max(rows, key=rows.get)
        return float(rows[source]), source, rows
    if choice in rows:
        return float(rows[choice]), choice, rows
    # 明确选了某条来源但它不可用：按 0 算，不偷偷换成别的来源
    return 0.0, choice, rows


def payload(state: dict, settings: Settings) -> dict:
    return {
        "features": [
            {"key": key, "label": LABELS[key],
             "value": strategy(state, settings, key),
             "options": [{"key": option, "label": STRATEGY_LABELS[option]}
                         for option in STRATEGIES
                         if key == "conception" or option != "both"]}
            for key in FEATURES
        ]
    }


def set_strategy(state: dict, feature: str, value: str) -> str:
    if feature not in FEATURES:
        raise ValueError("没有这个功能")
    value = str(value or "").strip().lower()
    if value not in STRATEGIES or (feature != "conception" and value == "both"):
        raise ValueError("没有这个来源")
    row = state.get("desire_strategy")
    if not isinstance(row, dict):
        row = {}
        state["desire_strategy"] = row
    row[feature] = value
    return value
