"""允许插入一起入睡 / Unbirth 体内过夜。"""

from __future__ import annotations

import random
from datetime import datetime

from . import endurance, menstrual, mood, prompts, sleepy, state as state_mod, unbirth, util, wetness
from .settings import Settings

MODES = {
    "vagina": "阴道里",
    "anus": "后面",
    "tail": "尾巴里",
    "unbirth": "子宫里",
}
DEFAULT = {
    "mode": "", "asked_at": 0.0, "started_at": 0.0, "until": 0.0,
    "slight": 0, "wake_note": "", "uncertain": False,
}


def keywords(state: dict, settings: Settings) -> dict:
    stored = state.get("sleep_inside_keywords")
    if isinstance(stored, dict) and stored:
        return stored
    raw = settings.config.get("sleep_inside", {}).get("keywords")
    if not isinstance(raw, dict):
        raw = {}
    return {mode: [str(w).strip() for w in (raw.get(mode) or []) if str(w).strip()]
            for mode in MODES}


def detect_mode(text: str, state: dict, settings: Settings) -> str:
    body = str(text or "")
    words = keywords(state, settings)
    for mode in ("unbirth", "anus", "tail", "vagina"):
        if any(word in body for word in words.get(mode, [])):
            return mode
    return ""


def data(state: dict) -> dict:
    row = state.get("sleep_inside")
    if not isinstance(row, dict):
        row = dict(DEFAULT)
        state["sleep_inside"] = row
    for key, value in DEFAULT.items():
        row.setdefault(key, value)
    return row


def active(state: dict, now: float | None = None) -> bool:
    row = data(state)
    until = util.safe_float(row.get("until"), 0.0)
    if row.get("mode") and (not until or until > (now or util.now_ts())):
        return True
    if row.get("mode") and until and until <= (now or util.now_ts()):
        row.update({"mode": "", "started_at": 0.0, "until": 0.0})
    return False


def _text(state: dict, key: str, **fmt) -> str:
    if state.get("menstrual_active"):
        line = prompts.text(state, "sleep_inside", f"{key}_period", **fmt)
        if line:
            return line
    return prompts.text(state, "sleep_inside", key, **fmt)


def _night(settings: Settings, now: float) -> bool:
    hour = datetime.fromtimestamp(now).hour
    start = settings.int("sleep_inside.ask_night_start_hour", 0, 23)
    end = settings.int("sleep_inside.ask_night_end_hour", 0, 23)
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def _ask_allowed(state: dict, settings: Settings, now: float) -> bool:
    sleep = sleepy.sleeping(settings, now=now)
    asleep = bool(sleep.get("sleeping", sleep.get("asleep")))
    return (asleep or _night(settings, now)
            or state_mod.scene_active(state, settings, now=now))


def _ask_key(state: dict, settings: Settings, now: float) -> str:
    sleep = sleepy.sleeping(settings, now=now)
    if sleep.get("sleeping", sleep.get("asleep")):
        return "ask"
    if state_mod.scene_active(state, settings, now=now):
        return "ask_scene"
    if util.safe_float(state.get("sleep_awake_until"), 0.0) > now:
        return "ask_wake"
    return "ask_awake"


def ask(state: dict, settings: Settings, mode: str, now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not settings.bool("sleep_inside.enabled"):
        return {"ok": False, "reason": "插入入睡没开"}
    mode = str(mode or "").lower()
    if mode not in MODES:
        return {"ok": False, "reason": "没有这个部位"}
    if active(state, now):
        return {"ok": False, "reason": "已经在里面睡着了"}
    if menstrual.changing(state, now):
        return {"ok": False, "reason": "她正在换卫生巾，现在不方便"}
    if not _ask_allowed(state, settings, now):
        return {"ok": False, "reason": "现在不是睡前，也不在活动里"}
    if mode == "unbirth":
        if not settings.bool("unbirth.enabled"):
            return {"ok": False, "reason": "Unbirth 没开"}
        if not unbirth.data(state).get("inside"):
            return {"ok": False, "reason": "得先真正待在子宫里，才能这样过夜"}
    row = data(state)
    row.update({"mode": "", "asked_at": now, "pending": mode})
    line = _text(state, _ask_key(state, settings, now), place=MODES[mode])
    state["sleep_inside_ask"] = {"at": now, "mode": mode, "line": line}
    return {"ok": True, "mode": mode, "line": line}


def accept(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    mode = str(row.get("pending") or "")
    if mode not in MODES:
        return {"ok": False, "reason": "现在没有待答应的请求"}
    if menstrual.changing(state, now):
        return {"ok": False, "reason": "她正在换卫生巾，现在不方便"}
    asked = util.safe_float(row.get("asked_at"), 0.0)
    wait = max(1, settings.int("sleep_inside.ask_wait_minutes", 1, 120)) * 60
    if asked and now - asked > wait:
        row["pending"] = ""
        return {"ok": False, "reason": "已经等太久了，她重新睡过去了"}
    if not _ask_allowed(state, settings, now):
        return {"ok": False, "reason": "现在不是睡前，活动也已经结束了"}
    row.update({"mode": mode, "pending": "", "started_at": now,
                "until": now + 8 * 3600, "slight": 0,
                "wake_note": "", "uncertain": False})
    line = _text(state, f"accept_{mode}", place=MODES[mode])
    state["sleep_inside_note"] = {"at": now, "line": line}
    return {"ok": True, "mode": mode, "line": line}


def end(state: dict, settings: Settings, *, wake: bool = True,
        reason: str = "end", now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    mode = str(row.get("mode") or "")
    if not mode:
        return {"ok": False, "reason": "现在没有在插入入睡"}
    row.update({"mode": "", "started_at": 0.0, "until": 0.0, "pending": ""})
    if mode == "unbirth":
        row["uncertain"] = True
    line = _text(state,
                 f"{reason}_{mode}" if reason in ("wake", "orgasm") else "end",
                 place=MODES.get(mode, ""))
    state["sleep_inside_note"] = {"at": now, "line": line}
    return {"ok": True, "mode": mode, "line": line,
            "uncertain": bool(row.get("uncertain"))}


def move(state: dict, settings: Settings, *, deep: bool = False,
         now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not active(state, now):
        return {"ok": False, "reason": "现在没有在插入入睡"}
    row = data(state)
    mode = str(row.get("mode") or "")
    if deep:
        return end(state, settings, wake=True, reason="wake", now=now)
    row["slight"] = util.safe_int(row.get("slight"), 0) + 1
    pleasure = settings.float("sleep_inside.slight_pleasure", 0.0, 100.0)
    wet = settings.float("sleep_inside.slight_wet", 0.0, 100.0)
    endurance_gain = settings.float("sleep_inside.slight_endurance", 0.0, 100.0)
    desire = settings.float("sleep_inside.slight_desire", 0.0, 100.0)
    state_mod.add_pleasure(state, settings, pleasure)
    endurance.add_extra(state, settings, endurance_gain)
    mood.adjust(state, settings, "desire", delta=desire, now=now)
    if wet:
        wetness.gain(state, settings, extra=wet, now=now)
    threshold = state_mod.effective_threshold(state, settings, now=now)
    if util.safe_float(state.get("pleasure"), 0.0) >= threshold:
        return end(state, settings, wake=True, reason="orgasm", now=now)
    line = _text(state, f"slight_{mode}", place=MODES.get(mode, ""))
    state["sleep_inside_note"] = {"at": now, "line": line}
    return {"ok": True, "mode": mode, "line": line,
            "slight": row["slight"], "pleasure": round(pleasure, 1)}


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    is_active = active(state, now)
    return {
        "enabled": settings.bool("sleep_inside.enabled"),
        "active": is_active,
        "mode": str(row.get("mode") or "") if is_active else "",
        "place": MODES.get(str(row.get("mode") or ""), ""),
        "pending": str(row.get("pending") or ""),
        "slight": util.safe_int(row.get("slight"), 0),
        "uncertain": bool(row.get("uncertain")),
        "modes": [{"key": key, "label": label} for key, label in MODES.items()],
        "mode_hint": str(state.get("sleep_inside_mode_hint") or ""),
        "keywords": keywords(state, settings),
    }
