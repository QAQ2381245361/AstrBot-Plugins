"""潮吹喷水：水量条、回充、概率、加成与提示词。

- 水量条 `squirt.water_max`（默认 100），随时间按 `squirt.regen_per_minute` 回充；
- 高潮时按概率触发：基础概率 + 快感/忍耐加成 + 上次刚潮吹 + 连续高潮加成；
- 触发后消耗水量（`cost_ratio` × 喷量），按喷量加 快感/湿润/忍耐（有上限）；
- 水量低于 `squirt.min_water` 时不触发，只出"想潮吹但没水"的提示词；
- 连续触发（`combo_window_minutes` 内）概率更高、喷得更多、加成更多。
"""

from __future__ import annotations

import random

from . import clothing, endurance, menstrual, prompts, tuning, util, wetness
from .settings import Settings

DEFAULT = {"value": 60.0, "at": 0.0, "last_at": 0.0, "last_amount": 0.0, "count": 0}


def data(state: dict) -> dict:
    value = state.get("water")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        value["value"] = float(DEFAULT["value"])
        state["water"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def enabled(settings: Settings) -> bool:
    return settings.bool("squirt.enabled")


def _num(state: dict, settings: Settings, key: str, lo: float = 0.0,
         hi: float = 100.0) -> float:
    return tuning.get(state, "squirt", key, settings.float(f"squirt.{key}", lo, hi))


def water_max(state: dict, settings: Settings) -> float:
    return max(1.0, _num(state, settings, "water_max", 1.0, 1000.0))


def _settle(state: dict, settings: Settings, now: float) -> dict:
    row = data(state)
    if not util.safe_float(row.get("at"), 0.0):
        row["value"] = settings.float("squirt.start", 0.0, 1000.0)
    at = util.safe_float(row.get("at"), 0.0) or now
    rate = _num(state, settings, "regen_per_minute", 0.0, 100.0)
    value = util.safe_float(row.get("value"), 0.0)
    minutes = max(0.0, (now - at) / 60.0)
    if rate > 0 and minutes > 0:
        value = min(water_max(state, settings), value + rate * minutes)
    row["value"] = round(max(0.0, value), 2)
    row["at"] = max(at, now)
    return row


def value_of(state: dict, settings: Settings, now: float | None = None) -> float:
    now = now or util.now_ts()
    return round(util.safe_float(_settle(state, settings, now).get("value"), 0.0), 2)


def consume(state: dict, settings: Settings, amount: float, *, now: float | None = None) -> float:
    now = now or util.now_ts()
    row = _settle(state, settings, now)
    cost = max(0.0, amount * _num(state, settings, "cost_ratio", 0.0, 10.0))
    value = util.safe_float(row.get("value"), 0.0)
    cost = min(cost, value)
    row["value"] = round(max(0.0, value - cost), 2)
    return round(cost, 2)


def chance(state: dict, settings: Settings, *, pleasure: float, endurance_percent: float,
           combo: int, now: float | None = None) -> float:
    now = now or util.now_ts()
    row = data(state)
    base = _num(state, settings, "chance", 0.0, 100.0)
    base += max(0.0, pleasure) / 100.0 * _num(state, settings, "pleasure_bonus", 0.0, 100.0)
    base += max(0.0, endurance_percent) / 100.0 * _num(
        state, settings, "endurance_bonus", 0.0, 100.0)
    base += max(0, int(combo)) * _num(state, settings, "combo_bonus", 0.0, 100.0)
    last = util.safe_float(row.get("last_at"), 0.0)
    window = settings.int("squirt.combo_window_minutes", 1, 240) * 60
    if last and now - last <= window:
        base += _num(state, settings, "after_bonus", 0.0, 100.0)
    return round(min(100.0, max(0.0, base)), 1)


def roll(state: dict, settings: Settings, *, pleasure: float, endurance_percent: float,
         combo: int, now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings):
        return {}
    water = value_of(state, settings, now=now)
    if water < _num(state, settings, "min_water", 0.0, 1000.0):
        return {"fired": False, "dry": True, "water": water,
                "line": prompts.text(state, "squirt", "dry")}
    rate = chance(state, settings, pleasure=pleasure, endurance_percent=endurance_percent,
                  combo=combo, now=now)
    if random.random() * 100.0 >= rate:
        return {"fired": False, "chance": rate, "water": water}
    row = data(state)
    last = util.safe_float(row.get("last_at"), 0.0)
    window = settings.int("squirt.combo_window_minutes", 1, 240) * 60
    count = int(row.get("count") or 0)
    if last and now - last <= window:
        count += 1
    else:
        count = 1
    amount = _num(state, settings, "volume", 0.0, 1000.0) * (
        0.6 + max(0.0, pleasure) / 100.0 * _num(state, settings, "volume_pleasure", 0.0, 10.0)
        + max(0.0, endurance_percent) / 100.0 * _num(state, settings, "volume_endurance", 0.0, 10.0)
    ) * (1.0 + (count - 1) * _num(state, settings, "combo_volume", 0.0, 10.0))
    amount = round(max(0.0, amount), 1)
    cost = consume(state, settings, amount, now=now)
    ratio = amount / max(1.0, _num(state, settings, "volume", 1.0, 1000.0))
    gain_p = min(_num(state, settings, "pleasure_cap", 0.0, 100.0),
                 _num(state, settings, "pleasure_gain", 0.0, 100.0) * ratio)
    gain_e = _num(state, settings, "endurance_gain", 0.0, 100.0) * ratio
    gain_w = _num(state, settings, "wet_gain", 0.0, 100.0) * ratio
    state["pleasure"] = util.safe_float(state.get("pleasure"), 0.0) + gain_p
    endurance.add_extra(state, settings, gain_e)
    wetness.gain(state, settings, extra=gain_w, now=now)
    if clothing.worn_key(state, settings, "pad"):
        ratio = max(0.0, _num(state, settings, "pad_absorb_ratio"))
        absorbed = menstrual.add_pad_fluid(
            state, settings, "潮吹", amount * ratio, now=now)
        overflow = max(0.0, amount * ratio - absorbed)
        if overflow > 0:
            if clothing.worn_key(state, settings, "underwear"):
                clothing.mark_panties_wet(state, "squirt", now=now)
            elif clothing.worn_key(state, settings, "bottom"):
                clothing.mark_bottom_wet(state, "squirt", now=now)
    elif clothing.worn_key(state, settings, "underwear"):
        clothing.mark_panties_wet(state, "squirt", now=now)
    elif clothing.worn_key(state, settings, "bottom"):
        clothing.mark_bottom_wet(state, "squirt", now=now)
    row.update({"last_at": now, "last_amount": amount, "count": count})
    line = prompts.text(state, "squirt", "combo" if count > 1 else "wet",
                        amount=amount, count=count)
    return {"fired": True, "amount": amount, "cost": cost, "chance": rate,
            "count": count, "pleasure": round(gain_p, 1),
            "endurance": round(gain_e, 1), "wetness": round(gain_w, 1),
            "water": value_of(state, settings, now=now), "line": line}


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    value = value_of(state, settings, now=now)
    row = data(state)
    last = util.safe_float(row.get("last_at"), 0.0)
    return {
        "enabled": enabled(settings),
        "value": value,
        "max": water_max(state, settings),
        "percent": round(value / water_max(state, settings) * 100, 1),
        "regen_per_minute": _num(state, settings, "regen_per_minute", 0.0, 100.0),
        "min_water": _num(state, settings, "min_water", 0.0, 1000.0),
        "last_at": last,
        "last_amount": round(util.safe_float(row.get("last_amount"), 0.0), 1),
        "count": int(row.get("count") or 0),
        "combo_recent": bool(last and now - last
                             <= settings.int("squirt.combo_window_minutes", 1, 240) * 60),
    }


def block(state: dict, settings: Settings, now: float | None = None) -> str:
    if not enabled(settings):
        return ""
    now = now or util.now_ts()
    row = data(state)
    last = util.safe_float(row.get("last_at"), 0.0)
    minutes = max(1, settings.int("squirt.prompt_minutes", 1, 240))
    if not last or now - last > minutes * 60:
        return ""
    count = int(row.get("count") or 0)
    line = prompts.text(state, "squirt", "combo" if count > 1 else "wet",
                        amount=round(util.safe_float(row.get("last_amount"), 0.0), 1),
                        count=count)
    return f"【潮吹】\n- {line}" if line else ""


def clear(state: dict) -> None:
    state["water"] = {"value": float(DEFAULT["value"]), "at": 0.0, "last_at": 0.0,
                      "last_amount": 0.0, "count": 0}
