"""吞精：外射后可以收集、也可以选择射在嘴里再吞下去。

- `collect()`：收集起来（可选射在嘴里），加一点快感/欲望/湿润；
- `swallow()`：吞下去，加得更多；
- 都有独立提示词，面板两个按钮 + 工具 `swallow`。
"""

from __future__ import annotations

import random

from . import endurance, lewd, mood, prompts, tuning, util, wetness
from .settings import Settings

DEFAULT = {"at": 0.0, "count": 0, "collected": 0, "mouth": False}


def enabled(settings: Settings) -> bool:
    return settings.bool("swallow.enabled")


def data(state: dict) -> dict:
    value = state.get("swallow")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["swallow"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def _num(state: dict, settings: Settings, key: str) -> float:
    return tuning.get(state, "swallow", key, settings.float(f"swallow.{key}", 0.0, 100.0))


def _gain(state: dict, settings: Settings, key: str, now: float) -> float:
    amount = _num(state, settings, key)
    if amount:
        state["pleasure"] = util.safe_float(state.get("pleasure"), 0.0) + amount
    return amount


def collect(state: dict, settings: Settings, *, in_mouth: bool = False,
            now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings):
        return {"ok": False, "reason": "吞精玩法没开"}
    row = data(state)
    row.update({"at": now, "collected": util.safe_int(row.get("collected"), 0) + 1,
                "mouth": bool(in_mouth)})
    pleasure = _gain(state, settings, "collect_pleasure", now)
    desire = _num(state, settings, "desire_gain")
    wet = _num(state, settings, "wet_gain")
    mood.adjust(state, settings, "desire", delta=desire, now=now)
    wetness.gain(state, settings, extra=wet, now=now)
    end_gain = _num(state, settings, "endurance_gain")
    if end_gain:
        endurance.add_extra(state, settings, end_gain, now=now)
    return {"ok": True, "in_mouth": bool(in_mouth), "pleasure": pleasure,
            "desire": desire, "wet": round(wet, 2), "endurance": end_gain,
            "line": prompts.text(state, "swallow", "mouth" if in_mouth else "collect")}


def swallow(state: dict, settings: Settings, *, now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings):
        return {"ok": False, "reason": "吞精玩法没开"}
    row = data(state)
    if util.safe_int(row.get("collected"), 0) <= 0:
        return {"ok": False, "reason": "还没收集"}
    row.update({"at": now, "collected": 0, "count": util.safe_int(row.get("count"), 0) + 1})
    pleasure = _gain(state, settings, "swallow_pleasure", now)
    desire = _num(state, settings, "swallow_desire")
    wet = _num(state, settings, "swallow_wet")
    lewd_gain = _num(state, settings, "swallow_lewd")
    mood.adjust(state, settings, "desire", delta=desire, now=now)
    wetness.gain(state, settings, extra=wet, now=now)
    if lewd_gain:
        lewd.add(state, settings, lewd_gain, now=now)
    end_gain = _num(state, settings, "endurance_gain")
    if end_gain:
        endurance.add_extra(state, settings, end_gain, now=now)
    return {"ok": True, "count": row["count"], "pleasure": pleasure,
            "desire": desire, "wet": round(wet, 2), "lewd": lewd_gain,
            "endurance": end_gain,
            "line": prompts.text(state, "swallow", "swallow")}


def auto_enabled(state: dict, settings: Settings) -> bool:
    override = state.get("swallow_auto_enabled")
    if isinstance(override, bool):
        return override
    return settings.bool("swallow.auto_enabled")


def auto_after_ejaculation(state: dict, settings: Settings, *, mode: str,
                           now: float | None = None) -> dict:
    """外射/射在嘴里之后，她自己决定要不要收集、要不要吞。"""
    if not enabled(settings) or not auto_enabled(state, settings):
        return {}
    if mode not in ("outside", "throat"):
        return {}
    chance = _num(state, settings, "auto_chance")
    if chance <= 0 or random.random() * 100.0 >= chance:
        return {}
    info = collect(state, settings, in_mouth=(mode == "throat"), now=now)
    if not info.get("ok"):
        return {}
    result = {"collected": True, "in_mouth": bool(mode == "throat"),
              "line": info.get("line")}
    swallow_chance = _num(state, settings, "auto_swallow_chance")
    if swallow_chance > 0 and random.random() * 100.0 < swallow_chance:
        done = swallow(state, settings, now=now)
        if done.get("ok"):
            result.update({"swallowed": True, "swallow_line": done.get("line")})
    return result


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    row = data(state)
    return {
        "enabled": enabled(settings),
        "collected": util.safe_int(row.get("collected"), 0),
        "count": util.safe_int(row.get("count"), 0),
        "mouth": bool(row.get("mouth")),
        "pleasure": _num(state, settings, "collect_pleasure"),
        "swallow_pleasure": _num(state, settings, "swallow_pleasure"),
        "desire_gain": _num(state, settings, "desire_gain"),
        "wet_gain": _num(state, settings, "wet_gain"),
        "swallow_desire": _num(state, settings, "swallow_desire"),
        "swallow_wet": _num(state, settings, "swallow_wet"),
        "auto_enabled": auto_enabled(state, settings),
        "auto_chance": _num(state, settings, "auto_chance"),
        "auto_swallow_chance": _num(state, settings, "auto_swallow_chance"),
    }


def block(state: dict, settings: Settings, now: float | None = None) -> str:
    row = data(state)
    if not enabled(settings) or util.safe_int(row.get("collected"), 0) <= 0:
        return ""
    if row.get("mouth"):
        return "【嘴里】\n- 嘴里还含着，热热的，她不敢咽也不敢吐。"
    return "【精液】\n- 已经收集在手里，她低头看着，脸有点红。"


def clear(state: dict) -> None:
    state["swallow"] = dict(DEFAULT)
