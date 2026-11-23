"""淫乱度：场景/日常积累，闲着会退，越高越会自己发烫。

不触发任何事件：只慢慢推高欲望和湿润度，并把淫乱度本身消耗掉。
所有数值都是懒结算，没有定时器。
"""

from __future__ import annotations

from . import mood, util, wetness
from .settings import Settings

DEFAULT = {"value": 0.0, "at": 0.0, "last_gain_at": 0.0,
           "last_tick_at": 0.0, "last_settle_at": 0.0}


def data(state: dict) -> dict:
    row = state.get("lewd")
    if not isinstance(row, dict):
        row = dict(DEFAULT)
        state["lewd"] = row
    for key, default in DEFAULT.items():
        row.setdefault(key, default)
    return row


def enabled(settings: Settings) -> bool:
    return settings.bool("lewd.enabled")


def _num(state: dict, settings: Settings, key: str, lo: float, hi: float) -> float:
    from . import tuning
    return float(tuning.get(state, "lewd", key,
                            settings.float(f"lewd.{key}", lo, hi)))


def add(state: dict, settings: Settings, amount: float,
        now: float | None = None) -> dict:
    """场景/日常开始：加淫乱度，并把它记成“最近一次增长”。"""
    if not enabled(settings) or amount <= 0:
        return payload(state, settings, now=now)
    now = now or util.now_ts()
    row = data(state)
    settle(state, settings, now=now)
    top = max(1.0, _num(state, settings, "max", 1.0, 1000.0))
    row["value"] = round(util.clamp(util.safe_float(row.get("value"), 0.0) + amount,
                                    0.0, top), 2)
    row["last_gain_at"] = now
    row["last_tick_at"] = now
    row["at"] = now
    return payload(state, settings, now=now)


def settle(state: dict, settings: Settings, now: float | None = None) -> dict:
    """到点让欲望/湿润涨一点；太久没涨则慢慢回退。"""
    now = now or util.now_ts()
    row = data(state)
    if not enabled(settings):
        return payload(state, settings, now=now, _settled=True)
    top = max(1.0, _num(state, settings, "max", 1.0, 1000.0))
    value = util.clamp(util.safe_float(row.get("value"), 0.0), 0.0, top)
    last_tick = util.safe_float(row.get("last_tick_at"), 0.0) or now
    last_gain = util.safe_float(row.get("last_gain_at"), 0.0) or now
    last_settle = util.safe_float(row.get("last_settle_at"), 0.0) or now
    interval = max(1, int(_num(state, settings, "tick_minutes", 1, 1440))) * 60
    minimum = _num(state, settings, "tick_min", 0.0, 100.0)
    cost = _num(state, settings, "cost_per_tick", 0.0, 100.0)
    desire_gain = _num(state, settings, "desire_per_tick", 0.0, 100.0)
    wet_gain = _num(state, settings, "wet_per_tick", 0.0, 100.0)
    ticks = 0
    while value >= minimum and now - last_tick >= interval and ticks < 24:
        scale = 0.5 + (value / top) * 0.5
        if desire_gain > 0:
            mood.adjust(state, settings, "desire", delta=desire_gain * scale, now=now)
        if wet_gain > 0:
            wetness.gain(state, settings, extra=wet_gain * scale, now=now)
        value = max(0.0, value - cost)
        last_tick += interval
        last_gain = last_tick
        ticks += 1
    if value <= 0:
        value = 0.0
        last_gain = now
        last_tick = now
    start = max(last_settle, last_gain + max(
        0.0, _num(state, settings, "decay_after_minutes", 0.0, 10080.0)) * 60.0)
    if now > start and value > 0:
        rate = _num(state, settings, "decay_per_hour", 0.0, 100.0)
        value = max(0.0, value - rate * (now - start) / 3600.0)
    row["value"] = round(value, 2)
    row["at"] = now
    row["last_tick_at"] = last_tick
    row["last_gain_at"] = last_gain
    row["last_settle_at"] = now
    if ticks:
        row["last_tick_count"] = ticks
    return payload(state, settings, now=now, _settled=True)


def level_key(state: dict, settings: Settings, percent: float) -> str:
    value = util.safe_float(percent, 0.0)
    at2 = _num(state, settings, "level_at_2", 0.0, 100.0)
    at3 = max(at2, _num(state, settings, "level_at_3", 0.0, 100.0))
    at4 = max(at3, _num(state, settings, "level_at_4", 0.0, 100.0))
    if value < at2:
        return "level1"
    if value < at3:
        return "level2"
    if value < at4:
        return "level3"
    return "level4"


def payload(state: dict, settings: Settings, now: float | None = None,
            *, _settled: bool = False) -> dict:
    now = now or util.now_ts()
    if not _settled:
        settle(state, settings, now=now)
    row = data(state)
    top = max(1.0, _num(state, settings, "max", 1.0, 1000.0))
    value = util.clamp(util.safe_float(row.get("value"), 0.0), 0.0, top)
    return {
        "enabled": enabled(settings),
        "value": round(value, 1),
        "max": round(top, 1),
        "percent": round(value / top * 100, 1) if top else 0.0,
        "tick_minutes": int(_num(state, settings, "tick_minutes", 1, 1440)),
        "tick_min": round(_num(state, settings, "tick_min", 0.0, 100.0), 1),
        "cost_per_tick": round(_num(state, settings, "cost_per_tick", 0.0, 100.0), 1),
        "decay_after_minutes": int(_num(state, settings, "decay_after_minutes", 0, 10080)),
        "decay_per_hour": round(_num(state, settings, "decay_per_hour", 0.0, 100.0), 1),
        "last_tick_count": util.safe_int(row.get("last_tick_count"), 0),
    }
