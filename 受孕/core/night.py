"""夜袭前的最近活动：射过会压低概率，没射/没高潮会抬高概率。"""

from __future__ import annotations

from . import tuning, util
from .settings import Settings

DEFAULT = {"at": 0.0, "kind": "", "ejac_at": 0.0, "orgasm_at": 0.0}


def data(state: dict) -> dict:
    row = state.get("night_activity")
    if not isinstance(row, dict):
        row = dict(DEFAULT)
        state["night_activity"] = row
    for key, default in DEFAULT.items():
        row.setdefault(key, default)
    return row


def mark_activity(state: dict, kind: str, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    row.update({"at": now, "kind": str(kind or ""), "ejac_at": 0.0, "orgasm_at": 0.0})
    return row


def mark_ejaculation(state: dict, now: float | None = None) -> None:
    now = now or util.now_ts()
    row = data(state)
    if row.get("at"):
        row["ejac_at"] = now


def mark_orgasm(state: dict, now: float | None = None) -> None:
    now = now or util.now_ts()
    row = data(state)
    if row.get("at"):
        row["orgasm_at"] = now


def adjust_chance(state: dict, settings: Settings, chance: float,
                  now: float | None = None) -> tuple[float, str]:
    """按最近活动修正夜袭概率，返回 (概率, 原因)。"""
    now = now or util.now_ts()
    row = data(state)
    at = util.safe_float(row.get("at"), 0.0)
    if not at:
        return chance, ""
    window = tuning.get(state, "night_raid", "activity_window_minutes",
                        settings.int("night_raid.activity_window_minutes", 1, 1440))
    if now - at > max(1, int(window)) * 60:
        return chance, ""
    ejac_at = util.safe_float(row.get("ejac_at"), 0.0)
    orgasm_at = util.safe_float(row.get("orgasm_at"), 0.0)
    after_ejac = max(0, int(tuning.get(
        state, "night_raid", "after_ejac_minutes",
        settings.int("night_raid.after_ejac_minutes", 0, 1440)))) * 60
    if ejac_at >= at and after_ejac and now - ejac_at <= after_ejac:
        factor = max(0.0, min(1.0, float(tuning.get(
            state, "night_raid", "after_ejac_factor",
            settings.float("night_raid.after_ejac_factor", 0.0, 1.0)))))
        return chance * factor, "刚射过，夜袭概率降低"
    unfinished = max(0, int(tuning.get(
        state, "night_raid", "unfinished_minutes",
        settings.int("night_raid.unfinished_minutes", 0, 1440)))) * 60
    if not ejac_at and not orgasm_at and unfinished and now - at <= unfinished:
        bonus = float(tuning.get(
            state, "night_raid", "unfinished_bonus",
            settings.float("night_raid.unfinished_bonus", 0.0, 100.0)))
        return min(100.0, chance + bonus), "活动没射也没高潮，夜袭概率提高"
    return chance, ""
