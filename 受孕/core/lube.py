"""润滑油：加湿润、能管一阵子；也用于手部润滑。

- 面板阴道湿润度旁边有「用润滑油」按钮；日常小活动也能用；
- 用了之后 `lube.minutes` 分钟内算「润滑状态」，干燥惩罚不生效；
- `lube.wet_gain` 是润滑本身加的湿润（会额外多一点）；
- 也能润滑手（`lube.hand_*`），手淫/手部动作的提示词走 prompts 的 lube 组；
- 模型可以用工具主动用（AstrBot 可主动提出/主动使用）。
"""

from __future__ import annotations

from . import clothing, prompts, util, wetness
from .settings import Settings

DEFAULT = {"until": 0.0, "hand_until": 0.0, "breast_until": 0.0,
           "nipple_until": 0.0, "penis_until": 0.0, "at": 0.0, "wet": 0.0}


def data(state: dict) -> dict:
    value = state.get("lube")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["lube"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def enabled(settings: Settings) -> bool:
    return settings.bool("lube.enabled")


def minutes(settings: Settings) -> int:
    return max(1, settings.int("lube.minutes", 1, 720))


def hand_minutes(settings: Settings) -> int:
    return max(1, settings.int("lube.hand_minutes", 1, 720))


def active(state: dict, settings: Settings, now: float | None = None) -> bool:
    now = now or util.now_ts()
    if not enabled(settings):
        return False
    return util.safe_float(data(state).get("until"), 0.0) > now


def hand_active(state: dict, settings: Settings, now: float | None = None) -> bool:
    now = now or util.now_ts()
    if not enabled(settings):
        return False
    return util.safe_float(data(state).get("hand_until"), 0.0) > now


def apply(state: dict, settings: Settings, *, hand: bool = False,
          part: str = "", now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings):
        return {"ok": False, "reason": "润滑油没开"}
    row = data(state)
    row["at"] = now
    added = 0.0
    if part in ("breast", "nipple", "penis"):
        row[f"{part}_until"] = now + minutes(settings) * 60
        gain = settings.float(f"lube.{part}_wet_gain", 0.0, 100.0)
        added = wetness.gain(state, settings, extra=gain, now=now)
        line = prompts.text(state, "lube", part)
        return {"ok": True, "part": part, "added": round(added, 2),
                "minutes": minutes(settings), "line": line,
                "payload": payload(state, settings, now=now)}
    if hand:
        row["hand_until"] = now + hand_minutes(settings) * 60
        if clothing.worn_key(state, settings, "underwear"):
            clothing.mark_panties_wet(state, "lube", now=now)
        added = wetness.gain(state, settings, extra=settings.float("lube.hand_wet_gain", 0.0, 100.0),
                             now=now)
        line = prompts.text(state, "lube", "hand")
    else:
        row["until"] = now + minutes(settings) * 60
        if clothing.worn_key(state, settings, "underwear"):
            clothing.mark_panties_wet(state, "lube", now=now)
        added = wetness.gain(state, settings, extra=settings.float("lube.wet_gain", 0.0, 100.0),
                             now=now)
        row["wet"] = round(util.safe_float(row.get("wet"), 0.0) + util.safe_float(
            settings.float("lube.wet_gain", 0.0, 100.0), 0.0), 1)
        line = prompts.text(state, "lube", "vagina")
    return {"ok": True, "hand": bool(hand), "added": round(added, 2),
            "minutes": hand_minutes(settings) if hand else minutes(settings),
            "line": line, "payload": payload(state, settings, now=now)}


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    until = util.safe_float(row.get("until"), 0.0)
    hand_until = util.safe_float(row.get("hand_until"), 0.0)
    return {
        "enabled": enabled(settings),
        "active": active(state, settings, now=now),
        "hand_active": hand_active(state, settings, now=now),
        "left_minutes": max(0, int((until - now) // 60)) if until > now else 0,
        "hand_left_minutes": max(0, int((hand_until - now) // 60)) if hand_until > now else 0,
        "wet_gain": settings.float("lube.wet_gain", 0.0, 100.0),
        "minutes": minutes(settings),
        "hand_wet_gain": settings.float("lube.hand_wet_gain", 0.0, 100.0),
        "hand_minutes": hand_minutes(settings),
        "breast_active": util.safe_float(row.get("breast_until"), 0.0) > now,
        "nipple_active": util.safe_float(row.get("nipple_until"), 0.0) > now,
        "penis_active": util.safe_float(row.get("penis_until"), 0.0) > now,
    }


def natural_wetness(state: dict, settings: Settings,
                    now: float | None = None) -> float:
    """夜袭判定用：扣掉润滑油加的那部分，只看她自己的湿润。"""
    now = now or util.now_ts()
    value = wetness.value_of(state, settings, now)
    if active(state, settings, now=now):
        value -= settings.float("lube.wet_gain", 0.0, 100.0)
    if hand_active(state, settings, now=now):
        value -= settings.float("lube.hand_wet_gain", 0.0, 100.0)
    if util.safe_float(data(state).get("breast_until"), 0.0) > now:
        value -= settings.float("lube.breast_wet_gain", 0.0, 100.0)
    if util.safe_float(data(state).get("nipple_until"), 0.0) > now:
        value -= settings.float("lube.nipple_wet_gain", 0.0, 100.0)
    if util.safe_float(data(state).get("penis_until"), 0.0) > now:
        value -= settings.float("lube.penis_wet_gain", 0.0, 100.0)
    return max(0.0, min(100.0, value))


def block(state: dict, settings: Settings, *, now: float | None = None) -> str:
    info = payload(state, settings, now=now)
    if not info.get("active"):
        return ""
    line = prompts.text(state, "lube", "vagina")
    return f"【润滑】\n- {line}\n（已经抹过润滑油了，湿润是外来的，别写成她自己动情。）"


def clear(state: dict) -> None:
    state["lube"] = dict(DEFAULT)
