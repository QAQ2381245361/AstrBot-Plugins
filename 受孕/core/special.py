"""特别敏感点：活动进行中，她身上有一处"这时候特别敏感"的地方，会自己换。

- 每 `every_minutes` 分钟换一个（在已启用的部位里轮流换）；
- 碰到它时：快感多涨一点（`pleasure_bonus`）、忍耐条也多攒一点（`endurance_bonus`）；
- 日常小玩具：每次用有 `daily_chance` 的概率也撞上"特别敏感档位"，
  额外涨 `daily_pleasure` 快感、`daily_endurance` 忍耐（数值都可调）。
"""

from __future__ import annotations

import random

from . import intimacy, toys, util
from .settings import Settings

DEFAULT = {"zone": "", "at": 0.0, "round": 0, "hits": 0, "next_at": 0.0,
           "toy": "", "toy_at": 0.0, "toy_next_at": 0.0, "toy_round": 0}


def data(state: dict) -> dict:
    value = state.get("special")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["special"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def enabled(settings: Settings) -> bool:
    return bool(settings.bool("special.enabled"))


def every_minutes(settings: Settings) -> int:
    return max(1, settings.int("special.every_minutes", 1, 720))


def rotate_on_timer(state: dict | None, settings: Settings) -> bool:
    """到点会不会自己换（关掉就只在被碰到 / 手动「换一个」时才换）。"""
    override = (state or {}).get("special", {}).get("rotate_override") \
        if isinstance((state or {}).get("special"), dict) else None
    if isinstance(override, bool):
        return override
    return bool(settings.bool("special.rotate_on_timer"))


def set_rotate(state: dict, settings: Settings, value: bool | None) -> bool:
    row = data(state)
    row["rotate_override"] = value
    return rotate_on_timer(state, settings)


def jitter_percent(settings: Settings) -> float:
    """到点时间的浮动范围（%）：0 = 每次都准时。"""
    return util.clamp(settings.float("special.jitter_percent", 0.0, 100.0), 0.0, 100.0)


def candidates(state: dict, settings: Settings) -> list[str]:
    """能当特别敏感点的部位：配置里点了就用那些，否则用所有启用的部位。"""
    configured = settings.list("special.zones")
    deep_only = {"hymen", "tube", "ovary"}
    zones = [key for key in configured
             if key not in deep_only and intent_zone_ok(state, settings, key)]
    if zones:
        return zones
    return [row["key"] for row in intimacy.zones_payload(settings, state)
            if row["enabled"] and row["key"] not in deep_only]


def intent_zone_ok(state: dict, settings: Settings, zone: str) -> bool:
    try:
        return intimacy.zone_enabled_effective(state, settings, zone)
    except Exception:
        return False


def _pick(pool: list[str], exclude: str = "") -> str:
    """随机挑一处；尽量别和刚才是同一处（只有一处时只能它）。"""
    options = [key for key in pool if key != exclude] or list(pool)
    try:
        return random.choice(options)
    except IndexError:
        return ""


def current(state: dict, settings: Settings, now: float | None = None) -> dict:
    """现在她是哪处特别敏感（到点会随机换一处，被碰过也会换）。"""
    now = now or util.now_ts()
    if not enabled(settings):
        return {"enabled": False}
    pool = candidates(state, settings)
    if not pool:
        return {"enabled": True, "zone": "", "label": "", "remaining": 0}
    row = data(state)
    every = every_minutes(settings) * 60
    timed = rotate_on_timer(state, settings)
    jitter = jitter_percent(settings) / 100.0
    zone = str(row.get("zone") or "")
    at = util.safe_float(row.get("at"), 0.0)
    next_at = util.safe_float(row.get("next_at"), 0.0)
    # 第一次、换到不可用的部位、或者（开着到点换且）到点了：随机换一处
    due = timed and next_at and now >= next_at
    if zone not in pool or not at or due:
        zone = _pick(pool, exclude=zone)
        row["zone"] = zone
        row["at"] = now
        row["round"] = util.safe_int(row.get("round"), 0) + 1
        row["hits"] = 0
        span = every * (1.0 + random.uniform(-jitter, jitter)) if jitter else every
        next_at = now + max(60.0, span)
        row["next_at"] = next_at
    left = max(0, int(next_at - now) // 60) + 1 if timed else 0
    return {
        "enabled": True,
        "zone": zone,
        "label": intimacy.ZONE_LABELS.get(zone, zone),
        "remaining": min(every_minutes(settings), left) if timed else 0,
        "timed": timed,
        "hits": util.safe_int(row.get("hits"), 0),
        "every_minutes": every_minutes(settings),
        "jitter_percent": jitter_percent(settings),
    }


def hit(state: dict, settings: Settings, zone: str, now: float | None = None) -> dict | None:
    """碰到的正好是特别敏感点：返回加成（加完之后这一处就换掉）。"""
    now = now or util.now_ts()
    info = current(state, settings, now)
    if not info.get("enabled") or not zone or info.get("zone") != zone:
        return None
    row = data(state)
    row["hits"] = util.safe_int(row.get("hits"), 0) + 1
    # 碰过一次就换到下一处（不是等计时器，是"被碰了就变"）；只有一处时还是它
    pool = candidates(state, settings)
    if len(pool) > 1:
        row["zone"] = _pick(pool, exclude=zone)
        row["at"] = now
        every = every_minutes(settings) * 60
        jitter = jitter_percent(settings) / 100.0
        span = every * (1.0 + random.uniform(-jitter, jitter)) if jitter else every
        row["next_at"] = now + max(60.0, span)
        row["round"] = util.safe_int(row.get("round"), 0) + 1
        row["hits"] = 0
    return {
        "zone": zone,
        "label": info.get("label") or zone,
        "pleasure": settings.float("special.pleasure_bonus", 0.0, 200.0),
        "endurance": settings.float("special.endurance_bonus", 0.0, 200.0),
        "moved": True,
        "next": row.get("zone") or zone,
    }


def toy_candidates(state: dict, settings: Settings) -> list[str]:
    """能当"特别档位"的小玩具：所有启用的。"""
    try:
        rows = toys.toys_payload(settings, state)
    except Exception:
        rows = []
    keys = [str(row.get("key") or "") for row in rows if row.get("enabled")]
    return [key for key in keys if key]


def current_toy(state: dict, settings: Settings, now: float | None = None) -> dict:
    """特别档位只跟着"正在使用的那个小玩具"；没有在用就没有特别档位。"""
    now = now or util.now_ts()
    if not enabled(settings):
        return {"enabled": False}
    active = toys.active_toy(state, settings, now) if hasattr(toys, "active_toy") else None
    key = str((active or {}).get("key") or "")
    if not key:
        return {"enabled": True, "key": "", "label": "", "remaining": 0, "timed": False,
                "in_use": False}
    label = ""
    try:
        label = str((toys.TOY_CATALOG.get(key) or {}).get("label") or key)
    except Exception:
        label = key
    return {"enabled": True, "key": key, "label": label, "remaining": 0,
            "timed": False, "in_use": True}


def daily_roll(state: dict, settings: Settings, toy_key: str = "",
               now: float | None = None) -> dict | None:
    """日常小玩具：用的正好是"特别档位"那个玩具，就按概率多涨快感/忍耐。"""
    if not enabled(settings):
        return None
    info = current_toy(state, settings, now)
    if not info.get("key") or (toy_key and toy_key != info["key"]):
        return None
    chance = settings.float("special.daily_chance", 0.0, 100.0)
    if chance <= 0 or random.random() * 100.0 >= chance:
        return None
    row = data(state)
    # 撞上之后档位换到另一个玩具（和特别敏感点一样，碰过就变）
    pool = toy_candidates(state, settings)
    if len(pool) > 1:
        row["toy"] = _pick(pool, exclude=info["key"])
        row["toy_at"] = now or util.now_ts()
        row["toy_next_at"] = 0.0
        row["toy_round"] = util.safe_int(row.get("toy_round"), 0) + 1
    return {
        "toy": info["key"],
        "toy_label": info["label"],
        "zone": info.get("zone", ""),
        "pleasure": settings.float("special.daily_pleasure", 0.0, 200.0),
        "endurance": settings.float("special.daily_endurance", 0.0, 200.0),
        "moved": True,
    }


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    info = current(state, settings, now)
    if not info.get("enabled"):
        return {"enabled": False}
    return {
        **info,
        "rotate_on_timer": rotate_on_timer(state, settings),
        "jitter_percent": jitter_percent(settings),
        "pleasure_bonus": settings.float("special.pleasure_bonus", 0.0, 200.0),
        "endurance_bonus": settings.float("special.endurance_bonus", 0.0, 200.0),
        "daily_chance": settings.float("special.daily_chance", 0.0, 100.0),
        "daily_pleasure": settings.float("special.daily_pleasure", 0.0, 200.0),
        "daily_endurance": settings.float("special.daily_endurance", 0.0, 200.0),
        "toy": current_toy(state, settings, now),
    }


def prompt_line(state: dict, settings: Settings, *, in_scene: bool,
                now: float | None = None) -> str:
    """活动场景里加一句"她现在最敏感的是哪儿"。"""
    if not in_scene or not enabled(settings):
        return ""
    info = current(state, settings, now)
    if not info.get("zone"):
        return ""
    if info.get("timed") and info.get("remaining"):
        when = f"（大约还有 {info['remaining']} 分钟会换）"
    else:
        when = "（碰过才会换）"
    return (f"【特别敏感点】她现在最敏感的是{info['label']}{when}："
            f"碰到这里她会明显更受不了。")


def reset(state: dict) -> None:
    state["special"] = dict(DEFAULT)
