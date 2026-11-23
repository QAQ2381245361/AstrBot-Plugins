"""ASMR 助眠：夜间给她/被他做耳朵助眠，计时、道具、提示词、收益与 PC 睡眠压力。

设计：
- 所有数值都可调（配置 + 面板 tune）；
- 助眠是「一次会话」：开始后计时，可续时间，到点自动结束；
- 助眠中的动作（哈热气/捂耳/含耳/舔耳道 + 助眠道具）走独立提示词；
- 单次会话里耳朵敏感、快感、羞耻、亲密/依恋都有上限；
- 结束时写一份 `asmr_sleep_relief.json`，PC 侧补丁读它、降低睡眠压力。
"""

from __future__ import annotations

import json
import random

from . import intimacy, mood, prompts, tuning, util, wetness
from .settings import PLUGIN_DATA_DIR, Settings

RELIEF_FILE = PLUGIN_DATA_DIR / "asmr_sleep_boost.json"

PROPS = {
    "ear_pick": ("耳搔", "asmr_prop"),
    "feather": ("鹅毛棒", "asmr_prop"),
    "brahma": ("梵天", "asmr_prop"),
    "fluffy": ("绒毛棒", "asmr_prop"),
    "whisper": ("耳边低语", "asmr_prop"),
    "music": ("助眠音", "asmr_prop"),
}
ACTIONS = {
    "blow": ("哈热气", "asmr_action"),
    "cover": ("捂耳", "asmr_action"),
    "cover_rub": ("捂耳轻揉", "asmr_action"),
    "suck": ("含耳", "asmr_action"),
    "lick": ("舔耳道", "asmr_action"),
}
DAILY_ACTIONS = ("cover", "cover_rub", "suck")

DEFAULT = {
    "active": False, "started_at": 0.0, "until": 0.0,
    "prop": "", "action": "", "sessions": 0,
    "ear_gain": 0.0, "pleasure_gain": 0.0, "shame_gain": 0.0,
    "wet_gain_sum": 0.0, "endurance_gain_sum": 0.0,
    "intimacy_gain": 0.0, "attachment_gain": 0.0,
    "relief": 0.0, "relief_since": 0.0, "last_action_at": 0.0, "pc_noted": False,
    "request_at": 0.0, "request_until": 0.0, "cool_at": 0.0,
}


def data(state: dict) -> dict:
    row = state.get("asmr")
    if not isinstance(row, dict):
        row = dict(DEFAULT)
        state["asmr"] = row
    for key, default in DEFAULT.items():
        row.setdefault(key, default)
    return row


def _num(state: dict, settings: Settings, key: str) -> float:
    return float(tuning.get(state, "asmr", key,
                            settings.float(f"asmr.{key}", 0.0, 1000.0)))


def enabled(state: dict, settings: Settings) -> bool:
    override = state.get("asmr_enabled")
    if isinstance(override, bool):
        return override
    return settings.bool("asmr.enabled")


def active(state: dict, settings: Settings, now: float | None = None) -> bool:
    now = now or util.now_ts()
    row = data(state)
    if not row.get("active"):
        return False
    if util.safe_float(row.get("until"), 0.0) <= now:
        return False
    return True


def duration(state: dict, settings: Settings) -> int:
    return max(1, int(tuning.get(
        state, "asmr", "default_minutes",
        settings.int("asmr.default_minutes", 1, 240))))


def start(state: dict, settings: Settings, *, minutes: int | None = None,
          now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(state, settings):
        return {"ok": False, "reason": "ASMR 助眠关着"}
    row = data(state)
    if row.get("active") and util.safe_float(row.get("until"), 0.0) > now:
        return {"ok": False, "reason": "已经在助眠中"}
    span = max(1, int(minutes if minutes is not None else duration(state, settings)))
    span = min(span, max(1, int(_num(state, settings, "max_minutes"))))
    first = util.safe_int(row.get("sessions"), 0) <= 0
    state.pop("asmr_asleep", None)
    row.update({"active": True, "started_at": now, "until": now + span * 60,
                "sessions": util.safe_int(row.get("sessions"), 0) + 1,
                "ear_gain": 0.0, "pleasure_gain": 0.0, "shame_gain": 0.0,
    "wet_gain_sum": 0.0, "endurance_gain_sum": 0.0,
                "intimacy_gain": 0.0, "attachment_gain": 0.0, "relief": 0.0,
                "relief_since": now,
                "last_action_at": 0.0, "pc_noted": False})
    return {"ok": True, "minutes": span, "until": row["until"],
            "line": prompts.text(state, "asmr", "start_first" if first else "start")}


def extend(state: dict, settings: Settings, *, minutes: int | None = None,
           now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    if not active(state, settings, now):
        return {"ok": False, "reason": "现在没有在助眠"}
    step = max(1, int(minutes if minutes is not None else _num(state, settings, "extend_minutes")))
    max_until = util.safe_float(row.get("started_at"), now) + \
        max(1, int(_num(state, settings, "max_minutes"))) * 60
    row["until"] = min(max_until, util.safe_float(row.get("until"), now) + step * 60)
    return {"ok": True, "minutes": step, "until": row["until"],
            "line": prompts.text(state, "asmr", "extend")}


def finish(state: dict, settings: Settings, *, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    if not row.get("active"):
        return {"ok": False, "reason": "现在没有在助眠"}
    row["active"] = False
    row["until"] = 0.0
    row["cool_at"] = now
    write_relief(state, now=now)
    line = prompts.text(state, "asmr", "end")
    slept = False
    chance = max(0.0, _num(state, settings, "sleep_chance"))
    if chance > 0 and random.random() * 100 < chance:
        slept = True
        state["asmr_asleep"] = {"at": now, "until": now + 8 * 3600}
        line = prompts.text(state, "asmr", "sleep") or line
    return {"ok": True, "line": line, "slept": slept}


def _daily_pressure(state: dict, now: float | None = None) -> float:
    now = now or util.now_ts()
    log = state.get("asmr_pressure_log")
    if not isinstance(log, list):
        log = []
        state["asmr_pressure_log"] = log
    log[:] = [item for item in log if isinstance(item, dict)
              and util.safe_float(item.get("at"), 0.0) > now - 86400]
    return round(sum(util.safe_float(item.get("amount"), 0.0) for item in log), 2)


def clear_session_relief(state: dict, *, now: float | None = None) -> dict:
    """高潮后清掉本次助眠高潮前攒的睡眠压力，别把清醒的高潮算成助眠。"""
    now = now or util.now_ts()
    row = data(state)
    since = max(util.safe_float(row.get("started_at"), 0.0),
                util.safe_float(row.get("relief_since"), 0.0))
    log = state.get("asmr_pressure_log")
    if not isinstance(log, list):
        log = []
        state["asmr_pressure_log"] = log
    before = len(log)
    log[:] = [item for item in log if not (
        isinstance(item, dict) and util.safe_float(item.get("at"), 0.0) >= since)]
    row["relief"] = 0.0
    row["relief_since"] = now
    result = write_relief(state, now=now)
    return {"removed": before - len(log), "write": result}


def write_relief(state: dict, *, now: float | None = None) -> dict:
    now = now or util.now_ts()
    amount = max(0.0, _daily_pressure(state, now))
    if amount <= 0:
        try:
            RELIEF_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        return {"ok": False, "amount": 0.0}
    try:
        RELIEF_FILE.parent.mkdir(parents=True, exist_ok=True)
        RELIEF_FILE.write_text(json.dumps({
            "amount": round(amount, 2),
            "at": now,
            "until": now + 12 * 3600,
        }, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "amount": round(amount, 2)}
    except Exception as error:
        return {"ok": False, "reason": str(error)}


def action(state: dict, settings: Settings, key: str, *,
           now: float | None = None) -> dict:
    """助眠动作/道具：给提示词、加数值；返回 line 让上层注入。"""
    now = now or util.now_ts()
    if not enabled(state, settings):
        return {"ok": False, "reason": "ASMR 助眠关着"}
    row = data(state)
    is_prop = key in PROPS
    is_action = key in ACTIONS
    if not is_prop and not is_action:
        return {"ok": False, "reason": "没有这个助眠动作"}
    in_session = active(state, settings, now)
    if not in_session and key not in DAILY_ACTIONS:
        return {"ok": False, "reason": "现在没有在助眠（捂耳/含耳日常可用）"}
    if is_prop:
        row["prop"] = key
        prompt_key = f"prop_{key}"
    else:
        row["action"] = key
        prompt_key = f"action_{key}"
    line = prompts.text(state, "asmr", prompt_key)
    if in_session:
        ear_gain = min(
            max(0.0, _num(state, settings, "ear_sens_gain")),
            max(0.0, _num(state, settings, "ear_sens_cap") - util.safe_float(
                row.get("ear_gain"), 0.0)))
        if ear_gain > 0:
            intimacy.add_zone_bonus(state, settings, "ear", sens=ear_gain)
            row["ear_gain"] = round(util.safe_float(row.get("ear_gain"), 0.0) + ear_gain, 3)
        pleasure = min(
            max(0.0, _num(state, settings, "pleasure_gain")),
            max(0.0, _num(state, settings, "pleasure_cap") - util.safe_float(
                row.get("pleasure_gain"), 0.0)))
        if pleasure > 0:
            cap = settings.float("pleasure.max", 1.0, 1000.0)
            state["pleasure"] = round(min(
                cap, util.safe_float(state.get("pleasure"), 0.0) + pleasure), 2)
            row["pleasure_gain"] = round(
                util.safe_float(row.get("pleasure_gain"), 0.0) + pleasure, 2)
        from . import endurance
        end_cap = max(0.0, _num(state, settings, "endurance_cap"))
        end_left = max(0.0, end_cap - util.safe_float(
            row.get("endurance_gain_sum"), 0.0))
        end_add = min(max(0.0, _num(state, settings, "endurance_gain")), end_left)
        if end_add > 0:
            before_end = endurance.value_of(state, settings, now=now)
            endurance.add_extra(state, settings, end_add, now=now)
            after_end = endurance.value_of(state, settings, now=now)
            row["endurance_gain_sum"] = round(
                util.safe_float(row.get("endurance_gain_sum"), 0.0)
                + max(0.0, after_end - before_end), 2)
        intimacy_gain = min(
            max(0.0, _num(state, settings, "intimacy_gain")),
            max(0.0, _num(state, settings, "intimacy_cap") - util.safe_float(
                row.get("intimacy_gain"), 0.0)))
        attach_gain = min(
            max(0.0, _num(state, settings, "attachment_gain")),
            max(0.0, _num(state, settings, "attachment_cap") - util.safe_float(
                row.get("attachment_gain"), 0.0)))
        row["intimacy_gain"] = round(
            util.safe_float(row.get("intimacy_gain"), 0.0) + intimacy_gain, 2)
        row["attachment_gain"] = round(
            util.safe_float(row.get("attachment_gain"), 0.0) + attach_gain, 2)
        sessions = max(1, util.safe_int(row.get("sessions"), 1))
        decay = max(0.0, _num(state, settings, "shame_decay_per_session"))
        shame_base = max(
            max(0.0, _num(state, settings, "shame_floor")),
            max(0.0, _num(state, settings, "shame_gain")) - decay * (sessions - 1))
        shame_cap = max(0.0, _num(state, settings, "shame_cap"))
        shame = min(shame_base, max(0.0, shame_cap - util.safe_float(
            row.get("shame_gain"), 0.0)))
        if shame > 0:
            mood.adjust(state, settings, "shame", delta=shame, now=now)
            row["shame_gain"] = round(
                util.safe_float(row.get("shame_gain"), 0.0) + shame, 2)
        daily_left = max(
            0.0, _num(state, settings, "sleep_relief_daily_cap") -
            _daily_pressure(state, now))
        relief = min(
            max(0.0, _num(state, settings, "sleep_relief")),
            max(0.0, _num(state, settings, "sleep_relief_cap") - util.safe_float(
                row.get("relief"), 0.0)),
            daily_left)
        if relief > 0:
            row["relief"] = round(util.safe_float(row.get("relief"), 0.0) + relief, 2)
            log = state.setdefault("asmr_pressure_log", [])
            log.append({"at": now, "amount": round(relief, 2)})
            write_relief(state, now=now)
        wet_cap = max(0.0, _num(state, settings, "wet_cap"))
        wet_left = max(0.0, wet_cap - util.safe_float(row.get("wet_gain_sum"), 0.0))
        wet_add = min(max(0.0, _num(state, settings, "wet_gain")), wet_left)
        if wet_add > 0:
            wetness.gain(state, settings, extra=wet_add, now=now)
            row["wet_gain_sum"] = round(
                util.safe_float(row.get("wet_gain_sum"), 0.0) + wet_add, 3)
        row["last_action_at"] = now
        if state.get("pregnancy"):
            relief = min(
                max(0.0, _num(state, settings, "pregnancy_relief")),
                max(0.0, _num(state, settings, "pregnancy_relief_cap") -
                    util.safe_float(state.get("asmr_pregnancy_relief"), 0.0)))
            if relief > 0:
                state["asmr_pregnancy_relief"] = round(
                    util.safe_float(state.get("asmr_pregnancy_relief"), 0.0) + relief, 2)
    return {"ok": True, "line": line, "in_session": in_session,
            "relief": round(util.safe_float(row.get("relief"), 0.0), 2),
        "relief_daily": _daily_pressure(state, now),
            "intimacy": intimacy_gain if in_session else 0.0,
            "attachment": attach_gain if in_session else 0.0,
            "ear_gain": row.get("ear_gain", 0.0)}


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    left = max(0, int((util.safe_float(row.get("until"), 0.0) - now) // 60)) \
        if active(state, settings, now) else 0
    return {
        "enabled": enabled(state, settings),
        "request_enabled": settings.bool("asmr.request_enabled"),
        "active": active(state, settings, now),
        "left_minutes": left,
        "until": row.get("until") if active(state, settings, now) else 0.0,
        "duration": duration(state, settings),
        "sessions": util.safe_int(row.get("sessions"), 0),
        "ear_gain": round(util.safe_float(row.get("ear_gain"), 0.0), 3),
        "pleasure_gain": round(util.safe_float(row.get("pleasure_gain"), 0.0), 2),
        "endurance_gain": round(util.safe_float(
            row.get("endurance_gain_sum"), 0.0), 2),
        "shame_gain": round(util.safe_float(row.get("shame_gain"), 0.0), 2),
        "intimacy_gain": round(util.safe_float(row.get("intimacy_gain"), 0.0), 2),
        "attachment_gain": round(util.safe_float(row.get("attachment_gain"), 0.0), 2),
        "relief": round(util.safe_float(row.get("relief"), 0.0), 2),
        "wet_gain_sum": round(util.safe_float(row.get("wet_gain_sum"), 0.0), 2),
        "wet_cap": round(max(0.0, _num(state, settings, "wet_cap")), 2),
        "prop": row.get("prop") or "",
        "action": row.get("action") or "",
        "request_pending": bool(row.get("request_until") and
                                util.safe_float(row.get("request_until"), 0.0) > now),
        "request_until": row.get("request_until") or 0.0,
        "asleep": bool(state.get("asmr_asleep")),
    }
