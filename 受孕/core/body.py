"""处女膜、避孕、排出与吸收。

- 处女膜：初夜/阴道内射/阴道玩具可能破裂；破裂有额外快感和提示词。
- 避孕：避孕药（按时效）和避孕套（一次性）；都按配置的有效率压低受孕概率。
- 排出：把子宫里的精液清空；怀孕时禁止（不能把胎儿排出去）。
- 吸收：默认按 uterus_leak_per_hour，魅魔开启时乘 absorption_multiplier。
"""

from __future__ import annotations

import random

from . import prompts, succubus, tuning, util
from .settings import Settings

HYMEN_DEFAULT = {"intact": True, "ruptured_at": 0.0, "cause": "",
                "pain": "", "relief": 0.0, "damage": 0.0}
CONTRACEPTION_DEFAULT = {"pill_until": 0.0, "pill_at": 0.0, "condom": False,
                         "condom_at": 0.0}


def hymen_of(state: dict) -> dict:
    value = state.get("hymen")
    if not isinstance(value, dict):
        value = dict(HYMEN_DEFAULT)
        state["hymen"] = value
    for key, default in HYMEN_DEFAULT.items():
        value.setdefault(key, default)
    return value


def hymen_intact(state: dict) -> bool:
    return bool(hymen_of(state).get("intact", True))


def damage_max(state: dict, settings: Settings) -> float:
    return max(1.0, settings.float("hymen.damage_max", 1.0, 1000.0))


def add_hymen_damage(state: dict, settings: Settings, amount: float,
                     now: float | None = None, *, blood_key: str = "") -> dict:
    """累积处女膜损伤；到阈值会直接破裂并触发对应破处情节。"""
    if not hymen_intact(state) or amount <= 0:
        return {}
    now = now or util.now_ts()
    value = hymen_of(state)
    top = damage_max(state, settings)
    damage = min(top, max(0.0, util.safe_float(value.get("damage"), 0.0)) + amount)
    value["damage"] = round(damage, 2)
    if damage >= top:
        info = rupture_hymen(state, settings, "处女膜完全损伤", now=now,
                             force=True, blood_key=blood_key)
        return {"damage": round(damage, 2), "ruptured": bool(info), **(info or {})}
    return {"damage": round(damage, 2), "ruptured": False}


def hymen_payload(state: dict, settings: Settings) -> dict:
    value = hymen_of(state)
    intact = bool(value.get("intact", True))
    ruptured_at = util.safe_float(value.get("ruptured_at"), 0.0)
    return {
        "intact": intact,
        "ruptured_at": ruptured_at,
        "cause": str(value.get("cause") or ""),
        "pain": str(value.get("pain") or ""),
        "relief": round(util.safe_float(value.get("relief"), 0.0), 2),
        "recent": bool(not intact and ruptured_at and util.now_ts() - ruptured_at < 86400),
        "label": "完整" if intact else "已破裂",
        "damage": round(util.safe_float(value.get("damage"), 0.0), 1),
        "damage_max": round(damage_max(state, settings), 1),
    }


def hymen_blood_enabled(state: dict, settings: Settings) -> bool:
    override = state.get("hymen_blood_enabled")
    if isinstance(override, bool):
        return override
    return settings.bool("hymen.blood_enabled")


def rupture_hymen(state: dict, settings: Settings, cause: str,
                  now: float | None = None, *, force: bool = False,
                  relief: float = 0.0, blood_key: str = "") -> dict | None:
    """按概率破处；relief 是湿润度/快感带来的减痛比例（0–1）。

    返回 {first_time, pleasure, cause, relief, pain} 或 None（没破/已破/关闭）。
    """
    if not settings.bool("hymen.enabled"):
        return None
    value = hymen_of(state)
    if not value.get("intact", True):
        return None
    chance = settings.float("hymen.rupture_chance", 0.0, 100.0)
    if not force and chance > 0 and random.random() * 100 >= chance:
        return None
    now = now or util.now_ts()
    value["intact"] = False
    value["ruptured_at"] = now
    value["cause"] = str(cause or "")
    ratio = util.clamp(util.safe_float(relief, 0.0), 0.0, 1.0)
    value["relief"] = round(ratio, 2)
    label = "none" if ratio >= 0.9 else ("slight" if ratio >= 0.45 else "normal")
    value["pain"] = label
    value["damage"] = round(damage_max(state, settings), 2)
    result = {
        "first_time": True,
        "pleasure": round(settings.float("hymen.first_night_pleasure", 0.0, 100.0), 1),
        "cause": str(cause or ""),
        "relief": round(ratio, 2),
        "pain": label,
    }
    if hymen_blood_enabled(state, settings):
        key = str(blood_key or "penis")
        line = prompts.text(state, "hymen_blood", key)
        if line:
            state["hymen_blood_note"] = {"at": now, "line": line, "key": key}
            result["blood"] = line
    return result


def restore_hymen(state: dict) -> None:
    state["hymen"] = dict(HYMEN_DEFAULT)


# ---------------------------------------------------------------- 避孕

def contraception_of(state: dict) -> dict:
    value = state.get("contraception")
    if not isinstance(value, dict):
        value = dict(CONTRACEPTION_DEFAULT)
        state["contraception"] = value
    for key, default in CONTRACEPTION_DEFAULT.items():
        value.setdefault(key, default)
    return value


def pill_active(state: dict, now: float | None = None) -> bool:
    now = now or util.now_ts()
    return util.safe_float(contraception_of(state).get("pill_until"), 0.0) > now


def pill_remaining_hours(state: dict, now: float | None = None) -> float:
    now = now or util.now_ts()
    return max(0.0, (util.safe_float(contraception_of(state).get("pill_until"), 0.0) - now) / 3600.0)


def take_pill(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    hours = max(0.0, settings.float("contraception.pill_hours", 0.0, 240.0))
    row = contraception_of(state)
    row["pill_until"] = now + hours * 3600.0
    row["pill_at"] = now
    return {"until": row["pill_until"], "hours": hours}


def stop_pill(state: dict) -> None:
    row = contraception_of(state)
    row["pill_until"] = 0.0
    row["pill_at"] = 0.0


def condom_on(state: dict) -> bool:
    return bool(contraception_of(state).get("condom"))


def set_condom(state: dict, used: bool, now: float | None = None) -> bool:
    row = contraception_of(state)
    row["condom"] = bool(used)
    row["condom_at"] = (now or util.now_ts()) if used else 0.0
    return bool(used)


def contraception_multiplier(state: dict, settings: Settings) -> tuple[float, list[str]]:
    """返回概率倍率和说明（药/套同时用会叠乘）；面板调过的值优先。"""
    factor = 1.0
    notes = []
    if settings.bool("contraception.pill_enabled") and pill_active(state):
        eff = tuning.get(state, "contraception", "pill_effectiveness",
                         settings.float("contraception.pill_effectiveness", 0.0, 100.0)) / 100.0
        factor *= max(0.0, 1.0 - eff)
        notes.append(f"避孕药（有效 {eff * 100:.0f}%）")
    if settings.bool("contraception.condom_enabled") and condom_on(state):
        eff = tuning.get(state, "contraception", "condom_effectiveness",
                         settings.float("contraception.condom_effectiveness", 0.0, 100.0)) / 100.0
        factor *= max(0.0, 1.0 - eff)
        notes.append(f"避孕套（有效 {eff * 100:.0f}%）")
    return round(factor, 4), notes


def contraception_payload(state: dict, settings: Settings) -> dict:
    factor, notes = contraception_multiplier(state, settings)
    return {
        "pill_enabled": bool(settings.bool("contraception.pill_enabled")),
        "pill_active": pill_active(state),
        "pill_hours_left": round(pill_remaining_hours(state), 1),
        "condom_enabled": bool(settings.bool("contraception.condom_enabled")),
        "condom": condom_on(state),
        "multiplier": factor,
        "notes": notes,
    }


def condom_breaks(settings: Settings, state: dict | None = None) -> bool:
    chance = tuning.get(state, "contraception", "condom_break_chance",
                        settings.float("contraception.condom_break_chance", 0.0, 100.0)) if state else settings.float("contraception.condom_break_chance", 0.0, 100.0)
    return chance > 0 and random.random() * 100 < chance


# ---------------------------------------------------------------- 排出 / 吸收

def expel_uterus(state: dict) -> dict:
    before = util.safe_float(state.get("uterus_ml"), 0.0)
    state["uterus_ml"] = 0.0
    state["uterus_updated_at"] = util.now_ts()
    return {"before": round(before, 2), "after": 0.0}


def pleasure_scale(settings: Settings, state: dict | None = None) -> float:
    """魅魔开启时快感收益倍率。"""
    if state is None or not succubus.enabled(state, settings):
        return 1.0
    return max(1.0, settings.float("succubus.pleasure_scale", 1.0, 10.0))


def absorption_multiplier(settings: Settings, state: dict | None = None) -> float:
    if state is None or not succubus.enabled(state, settings):
        return 1.0
    return max(1.0, tuning.get(
        state, "succubus", "absorption_multiplier",
        settings.float("succubus.absorption_multiplier", 1.0, 100.0)))
