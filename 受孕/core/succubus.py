"""魅魔：淫纹等级、每日榨取上限、每次活动的加成与受孕难度。"""

from __future__ import annotations

import time
from datetime import datetime

from . import tuning, util
from .settings import Settings

DEFAULT = {"date": "", "count": 0, "tattoo_level": None, "willing": None,
           "last_desire_scene": 0.0, "exp": 0, "enabled_override": None,
           "tail_override": None}


def data(state: dict) -> dict:
    value = state.get("succubus")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["succubus"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def enabled(state: dict, settings: Settings) -> bool:
    value = data(state).get("enabled_override")
    if isinstance(value, bool):
        return value
    return bool(settings.bool("succubus.enabled"))


def set_enabled(state: dict, settings: Settings, value: bool | None) -> bool:
    data(state)["enabled_override"] = value
    return enabled(state, settings)


def tail_enabled(state: dict, settings: Settings) -> bool:
    """魅魔尾巴的开关：开着的话，就算「敏感点·尾巴」关着，尾巴也能用，
    而且她这条尾巴按魅魔尾巴算（敏感度 × tail_sensitivity_scale）。"""
    value = data(state).get("tail_override")
    if isinstance(value, bool):
        return value
    return bool(settings.bool("succubus.tail_enabled"))


def set_tail(state: dict, settings: Settings, value: bool | None) -> bool:
    data(state)["tail_override"] = value
    return tail_enabled(state, settings)


def tail_active(state: dict, settings: Settings) -> bool:
    """这条尾巴算不算魅魔尾巴：魅魔模式开着，或者魅魔尾巴开关开着。"""
    return enabled(state, settings) or tail_enabled(state, settings)


def today(now: float | None = None) -> str:
    return datetime.fromtimestamp(now or util.now_ts()).strftime("%Y-%m-%d")


def _reset_day(state: dict, now: float | None = None) -> dict:
    value = data(state)
    day = today(now)
    if value.get("date") != day:
        value["date"] = day
        value["count"] = 0
    return value


def level(state: dict, settings: Settings) -> int:
    value = data(state)
    if value.get("tattoo_level") is None:
        value["tattoo_level"] = settings.int("succubus.tattoo_level", 0, 5)
    return max(0, min(5, util.safe_int(value.get("tattoo_level"), 0)))


def set_level(state: dict, settings: Settings, level_value: int) -> int:
    value = data(state)
    value["tattoo_level"] = max(0, min(5, int(level_value)))
    return value["tattoo_level"]


def gain_scale(state: dict, settings: Settings) -> float:
    """淫纹等级给所有加成的倍率。"""
    per = settings.float("succubus.tattoo_gain_per_level", 0.0, 2.0)
    return 1.0 + level(state, settings) * per


def exp_need(state: dict, settings: Settings) -> int:
    return max(1, int(tuning.get(state, "succubus", "exp_per_level",
                                 settings.int("succubus.exp_per_level", 1, 10000))))


def exp_of(state: dict) -> int:
    return max(0, util.safe_int(data(state).get("exp"), 0))


def add_exp(state: dict, settings: Settings, amount: int) -> dict:
    """榨取涨经验；经验满自动升级（最多 5 级）。"""
    value = data(state)
    need = exp_need(state, settings)
    gained = max(0, int(amount))
    value["exp"] = exp_of(state) + gained
    leveled = 0
    while exp_of(state) >= need and level(state, settings) < 5:
        value["exp"] = exp_of(state) - need
        value["tattoo_level"] = level(state, settings) + 1
        leveled += 1
    if level(state, settings) >= 5:
        value["exp"] = min(exp_of(state), need)
    return {"gained": gained, "exp": exp_of(state), "need": need,
            "level": level(state, settings), "leveled": leveled}


def limit(state: dict, settings: Settings) -> int:
    return max(0, int(tuning.get(state, "succubus", "daily_limit",
                                settings.int("succubus.daily_limit", 0, 100))))
    return max(0, settings.int("succubus.daily_limit", 0, 100))


def used(state: dict, now: float | None = None) -> int:
    return max(0, util.safe_int(_reset_day(state, now).get("count"), 0))


def remaining(state: dict, settings: Settings, now: float | None = None) -> int:
    cap = limit(state, settings)
    return -1 if cap <= 0 else max(0, cap - used(state, now))


def can_boost(state: dict, settings: Settings, now: float | None = None) -> bool:
    if not enabled(state, settings):
        return False
    cap = limit(state, settings)
    return cap <= 0 or used(state, now) < cap


def consume(state: dict, settings: Settings, now: float | None = None) -> bool:
    """占用一次今日榨取；到上限返回 False。"""
    if not can_boost(state, settings, now):
        return False
    value = _reset_day(state, now)
    value["count"] = util.safe_int(value.get("count"), 0) + 1
    return True


def willing(state: dict) -> bool | None:
    value = data(state).get("willing")
    return value if isinstance(value, bool) else None


def set_willing(state: dict, value: bool | None) -> None:
    data(state)["willing"] = value


def desire_gain(state: dict, settings: Settings) -> float:
    base = tuning.get(state, "succubus", "desire_base_gain",
                      settings.float("succubus.desire_base_gain", 0.0, 100.0))
    per = tuning.get(state, "succubus", "desire_gain_per_level",
                     settings.float("succubus.desire_gain_per_level", 0.0, 100.0))
    return round(base + level(state, settings) * per, 2)


def ejaculation_gains(state: dict, settings: Settings) -> dict:
    scale = gain_scale(state, settings)
    return {
        "energy": round(tuning.get(state, "succubus", "ejaculation_energy_gain",
                                   settings.int("succubus.ejaculation_energy_gain", 0, 100)) * scale),
        "attachment": round(tuning.get(state, "succubus", "ejaculation_attachment_gain",
                                       settings.float("succubus.ejaculation_attachment_gain", 0.0, 100.0)) * scale, 2),
        "intimacy": round(tuning.get(state, "succubus", "ejaculation_intimacy_gain",
                                     settings.float("succubus.ejaculation_intimacy_gain", 0.0, 100.0)) * scale, 2),
    }


def orgasm_gains(state: dict, settings: Settings) -> dict:
    scale = gain_scale(state, settings)
    return {
        "energy": round(tuning.get(state, "succubus", "pc_energy_gain",
                                   settings.int("succubus.pc_energy_gain", 0, 100)) * scale),
        "attachment": round(tuning.get(state, "succubus", "fish_attachment_gain",
                                       settings.float("succubus.fish_attachment_gain", 0.0, 100.0)) * scale, 2),
        "intimacy": round(tuning.get(state, "succubus", "fish_intimacy_gain",
                                     settings.float("succubus.fish_intimacy_gain", 0.0, 100.0)) * scale, 2),
        "desire": round(tuning.get(state, "succubus", "fish_desire_gain",
                                   settings.float("succubus.fish_desire_gain", 0.0, 100.0)) * scale, 2),
    }


def desire_once(state: dict) -> bool:
    """每次活动只加一次欲：按场景开始时间判断。"""
    scene = state.get("scene") if isinstance(state.get("scene"), dict) else {}
    key = util.safe_float(scene.get("started_at"), 0.0)
    if key <= 0:
        key = round(time.time() / 1800.0)  # 没有场景时按半小时一档
    value = data(state)
    if util.safe_float(value.get("last_desire_scene"), 0.0) == key:
        return False
    value["last_desire_scene"] = key
    return True


def conception_factor(state: dict, settings: Settings) -> tuple[float, str]:
    if not enabled(state, settings):
        return 1.0, ""
    factor = settings.float("succubus.hard_to_conceive", 0.0, 1.0)
    if willing(state) is True:
        factor *= settings.float("succubus.willing_bonus", 1.0, 20.0)
        note = "魅魔·愿意怀（受孕加成）"
    elif willing(state) is False:
        factor *= settings.float("succubus.unwilling_factor", 0.0, 1.0)
        note = "魅魔·不愿意怀（几乎不会中）"
    else:
        note = "魅魔·难孕体质"
    return round(factor, 4), note


def payload(state: dict, settings: Settings) -> dict:
    cap = limit(state, settings)
    return {
        "enabled": enabled(state, settings),
        "tail_enabled": tail_enabled(state, settings),
        "tail_active": tail_active(state, settings),
        "level": level(state, settings),
        "max_level": 5,
        "gain_scale": round(gain_scale(state, settings), 2),
        "desire_gain": desire_gain(state, settings),
        "daily_limit": cap,
        "used": used(state),
        "remaining": remaining(state, settings),
        "unlimited": cap <= 0,
        "willing": willing(state),
        "conception_note": conception_factor(state, settings)[1],
        "absorption_multiplier": tuning.get(
            state, "succubus", "absorption_multiplier",
            settings.float("succubus.absorption_multiplier", 1.0, 100.0)),
        "exp": exp_of(state),
        "exp_need": exp_need(state, settings),
        "exp_gain": int(tuning.get(state, "succubus", "exp_gain",
                                   settings.int("succubus.exp_gain", 0, 1000))),
    }
