"""避孕套：活动中破裂、有没有感觉到、换新的、她帮忙戴。

- 戴着套做的时候，每次动作按 `condom.break_per_action` 概率破；
- 破的那一下她有没有感觉：快感/忍耐很高时可能没察觉（`unfelt_*`）；
- 感觉到以后按 `condom.change_ask_chance` 可能会想让换个新的；
- 戴的时候按 `condom.ask_chance` 有概率害羞地问"要不要我帮你戴"，
  她帮戴加欲望/湿润/羞耻（都可调），文案在 prompts 的 condom 组。
"""

from __future__ import annotations

import random

from . import body, mood, prompts, tuning, util, wetness
from .settings import Settings

DEFAULT = {"at": 0.0, "broken_at": 0.0, "felt": "", "ask_at": 0.0,
           "help_at": 0.0, "change_ask": False, "wear_at": 0.0,
           "remove_ask_at": 0.0, "remove_cool_at": 0.0, "remove_helped": False}


def data(state: dict) -> dict:
    value = state.get("condom_extra")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["condom_extra"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def enabled(settings: Settings) -> bool:
    return settings.bool("contraception.condom_enabled")


def worn(state: dict) -> bool:
    return body.condom_on(state)


def minutes(settings: Settings) -> int:
    return max(1, settings.int("condom.prompt_minutes", 1, 240))


def _num(state: dict, settings: Settings, key: str, lo: float = 0.0,
         hi: float = 100.0) -> float:
    return tuning.get(state, "condom", key, settings.float(f"condom.{key}", lo, hi))


def wear(state: dict, settings: Settings, *, now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings):
        return {"ok": False, "reason": "避孕套功能关着"}
    body.set_condom(state, True, now=now)
    row = data(state)
    row.update({"at": now, "broken_at": 0.0, "felt": "", "change_ask": False,
                "wear_at": now, "remove_ask_at": 0.0, "remove_cool_at": 0.0})
    asked = random.random() * 100.0 < _num(state, settings, "ask_chance")
    if asked:
        row["ask_at"] = now
    return {"ok": True, "asked": asked,
            "line": prompts.text(state, "condom", "ask") if asked else "",
            "payload": payload(state, settings, now=now)}


def renew(state: dict, settings: Settings, *, now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings):
        return {"ok": False, "reason": "避孕套功能关着"}
    body.set_condom(state, False)
    body.set_condom(state, True, now=now)
    row = data(state)
    row.update({"at": now, "broken_at": 0.0, "felt": "", "change_ask": False,
                "ask_at": 0.0, "wear_at": now,
                "remove_ask_at": 0.0, "remove_cool_at": 0.0})
    asked = random.random() * 100.0 < _num(state, settings, "renew_ask_chance")
    if asked:
        row["ask_at"] = now
    line = prompts.text(state, "condom", "renew")
    if asked:
        line = (line + "\n" + prompts.text(state, "condom", "ask")).strip()
    return {"ok": True, "asked": asked, "line": line,
            "payload": payload(state, settings, now=now)}


def maybe_ask_remove(state: dict, settings: Settings, *,
                     now: float | None = None) -> dict:
    """戴了一段时间后，她可能主动想让他脱掉；可以自己帮忙脱。"""
    now = now or util.now_ts()
    if not enabled(settings) or not worn(state):
        return {}
    row = data(state)
    wear_at = util.safe_float(row.get("wear_at"), 0.0)
    if not wear_at or now - wear_at < _num(
            state, settings, "remove_min_minutes", 1, 240) * 60:
        return {}
    cool = util.safe_float(row.get("remove_cool_at"), 0.0)
    if cool and now < cool:
        return {}
    asked = util.safe_float(row.get("remove_ask_at"), 0.0)
    if asked and now - asked < _num(
            state, settings, "remove_cooldown_minutes", 1, 1440) * 60:
        return {}
    if random.random() * 100.0 >= _num(state, settings, "remove_ask_chance"):
        return {}
    help_remove = random.random() * 100.0 < _num(
        state, settings, "remove_help_chance")
    row["remove_ask_at"] = now
    row["remove_helped"] = bool(help_remove)
    if help_remove:
        body.set_condom(state, False)
        row.update({"at": 0.0, "broken_at": 0.0, "felt": "", "change_ask": False,
                    "remove_cool_at": now + _num(
                        state, settings, "remove_cooldown_minutes", 1, 1440) * 60})
        return {"ask": True, "helped": True,
                "line": prompts.text(state, "condom", "ask_remove"),
                "help_line": prompts.text(state, "condom", "help_remove")}
    return {"ask": True, "helped": False,
            "line": prompts.text(state, "condom", "ask_remove")}


def remove(state: dict, settings: Settings, *, now: float | None = None) -> dict:
    if not enabled(settings):
        return {"ok": False, "reason": "避孕套功能关着"}
    if not worn(state):
        return {"ok": False, "reason": "现在没戴"}
    body.set_condom(state, False)
    row = data(state)
    row.update({"at": 0.0, "broken_at": 0.0, "felt": "", "change_ask": False,
                "ask_at": 0.0, "remove_ask_at": 0.0, "remove_helped": False})
    return {"ok": True, "line": prompts.text(state, "condom", "remove")}


def help_wear(state: dict, settings: Settings, *, now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings):
        return {"ok": False, "reason": "避孕套功能关着"}
    row = data(state)
    body.set_condom(state, True, now=now)
    row.update({"at": now, "help_at": now, "ask_at": 0.0, "broken_at": 0.0,
                "change_ask": False, "felt": ""})
    desire = _num(state, settings, "help_desire")
    shame = _num(state, settings, "help_shame")
    wet = _num(state, settings, "help_wet")
    mood.adjust(state, settings, "desire", delta=desire, now=now)
    mood.adjust(state, settings, "shame", delta=shame, now=now)
    added = wetness.gain(state, settings, extra=wet, now=now)
    return {"ok": True, "desire": desire, "shame": shame, "wet": round(wet, 2),
            "line": prompts.text(state, "condom", "help"),
            "payload": payload(state, settings, now=now)}


def help_remove(state: dict, settings: Settings, *,
                now: float | None = None) -> dict:
    """她主动动手把避孕套脱下来。"""
    if not enabled(settings):
        return {"ok": False, "reason": "避孕套功能关着"}
    if not worn(state):
        return {"ok": False, "reason": "现在没戴"}
    body.set_condom(state, False)
    row = data(state)
    row.update({"at": 0.0, "broken_at": 0.0, "felt": "", "change_ask": False,
                "ask_at": 0.0, "remove_ask_at": 0.0, "remove_helped": True})
    return {"ok": True, "line": prompts.text(state, "condom", "help_remove")}


def break_roll(state: dict, settings: Settings, *, pleasure: float, endurance_percent: float,
               at_ejaculation: bool = False, now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not worn(state):
        return {}
    chance = _num(state, settings, "break_per_action")
    if chance <= 0 or random.random() * 100.0 >= chance:
        return {}
    body.set_condom(state, False)
    row = data(state)
    row.update({"broken_at": now, "change_ask": False})
    high = (pleasure >= _num(state, settings, "unfelt_pleasure")
            or endurance_percent >= _num(state, settings, "unfelt_endurance"))
    felt = not (high and random.random() * 100.0 < _num(state, settings, "unfelt_chance"))
    row["felt"] = "felt" if felt else "unfelt"
    if at_ejaculation and felt:
        # 射的时候才发现破：已经来不及了，不会再问要不要换新的，只剩惊一下
        row["felt"] = "felt_late"
        row["change_ask"] = False
        line = prompts.text(state, "condom", "felt_late")
        return {"broke": True, "felt": True, "late": True, "change_ask": False,
                "line": line, "payload": payload(state, settings, now=now)}
    ask = felt and random.random() * 100.0 < _num(state, settings, "change_ask_chance")
    row["change_ask"] = bool(ask)
    line = prompts.text(state, "condom", "felt" if felt else "unfelt")
    return {"broke": True, "felt": felt, "change_ask": ask, "line": line,
            "payload": payload(state, settings, now=now)}


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    broken_at = util.safe_float(row.get("broken_at"), 0.0)
    ask_at = util.safe_float(row.get("ask_at"), 0.0)
    return {
        "enabled": enabled(settings),
        "worn": worn(state),
        "broken": bool(broken_at and now - broken_at <= minutes(settings) * 60),
        "broken_felt": str(row.get("felt") or ""),
        "change_ask": bool(row.get("change_ask")),
        "ask_pending": bool(ask_at and now - ask_at <= minutes(settings) * 60),
        "help_at": round(util.safe_float(row.get("help_at"), 0.0), 0),
        "break_per_action": _num(state, settings, "break_per_action"),
        "ask_chance": _num(state, settings, "ask_chance"),
        "renew_ask_chance": _num(state, settings, "renew_ask_chance"),
        "unfelt_pleasure": _num(state, settings, "unfelt_pleasure"),
        "unfelt_endurance": _num(state, settings, "unfelt_endurance"),
        "unfelt_chance": _num(state, settings, "unfelt_chance"),
        "change_ask_chance": _num(state, settings, "change_ask_chance"),
        "help_desire": _num(state, settings, "help_desire"),
        "help_shame": _num(state, settings, "help_shame"),
        "help_wet": _num(state, settings, "help_wet"),
        "prompt_minutes": minutes(settings),
        "remove_ask_chance": _num(state, settings, "remove_ask_chance"),
        "remove_help_chance": _num(state, settings, "remove_help_chance"),
        "remove_min_minutes": int(_num(state, settings, "remove_min_minutes", 1, 240)),
        "remove_cooldown_minutes": int(_num(
            state, settings, "remove_cooldown_minutes", 1, 1440)),
        "remove_ask_pending": bool(util.safe_float(row.get("remove_ask_at"), 0.0)
                                   and not row.get("remove_helped")),
    }


def block(state: dict, settings: Settings, now: float | None = None) -> str:
    now = now or util.now_ts()
    row = data(state)
    broken_at = util.safe_float(row.get("broken_at"), 0.0)
    if not broken_at or now - broken_at > minutes(settings) * 60:
        ask_at = util.safe_float(row.get("remove_ask_at"), 0.0)
        if worn(state) and ask_at and not row.get("remove_helped") and \
                now - ask_at <= minutes(settings) * 60:
            line = prompts.text(state, "condom", "ask_remove")
            return f"【避孕套】\n- {line}" if line else ""
        return ""
    felt = str(row.get("felt") or "felt")
    key = felt if felt in ("felt", "felt_late") else "unfelt"
    line = prompts.text(state, "condom", key)
    if not line:
        return ""
    hint = "；她感觉到了，正想让他换个新的" if row.get("change_ask") else ""
    return f"【避孕套】\\n- {line}{hint}"


def clear(state: dict) -> None:
    state["condom_extra"] = dict(DEFAULT)
