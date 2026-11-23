"""出生后的孩子：只记录背景，不建独立角色。"""

from __future__ import annotations

import random

from . import prompts, util
from .settings import Settings

CARE_LABELS = {
    "self": "她自己带",
    "family": "家人带",
    "nanny": "保姆带",
    "adoption": "送养",
    "background": "背景里",
}
MAX_AGE_MONTHS = 20 * 12


def data(state: dict) -> list:
    rows = state.get("children")
    if not isinstance(rows, list):
        rows = []
        state["children"] = rows
    return rows


def _months(old: dict, now: float) -> int:
    born = util.safe_float(old.get("born_at"), now)
    return max(0, int((now - born) / (30.44 * 86400)))


def age_text(months: int) -> str:
    if months < 24:
        return f"{max(1, months)}个月大"
    return f"{months // 12}岁"


def prune(state: dict, now: float | None = None) -> list:
    now = now or util.now_ts()
    rows = data(state)
    rows[:] = [row for row in rows
               if isinstance(row, dict) and _months(row, now) < MAX_AGE_MONTHS]
    return rows


def add_birth(state: dict, settings: Settings, sexes: list[str],
              now: float | None = None) -> list:
    now = now or util.now_ts()
    rows = prune(state, now)
    care = str(settings.str("children.care_mode") or "family")
    if care not in CARE_LABELS:
        care = "family"
    born = []
    for sex in sexes or ["未知"]:
        row = {"born_at": now, "sex": "女" if sex == "女" else "男",
               "care_mode": care, "name": ""}
        rows.append(row)
        born.append(row)
    if len(rows) > 50:
        del rows[:len(rows) - 50]
    return born


def roster(state: dict, settings: Settings, now: float | None = None) -> list:
    now = now or util.now_ts()
    rows = prune(state, now)
    out = []
    for row in rows:
        months = _months(row, now)
        out.append({
            "sex": row.get("sex") or "未知",
            "age_months": months,
            "age_text": age_text(months),
            "care_mode": row.get("care_mode") or "family",
            "care_label": CARE_LABELS.get(str(row.get("care_mode") or "family"), "家人带"),
            "name": row.get("name") or "",
        })
    return out


def summary(state: dict, settings: Settings, now: float | None = None) -> str:
    rows = roster(state, settings, now)
    if not rows:
        return ""
    parts = []
    for row in rows:
        label = row["sex"] + "孩"
        if row.get("name"):
            label = row["name"] + f"（{label}）"
        parts.append(f"{label}，{row['age_text']}，{row['care_label']}")
    return "；".join(parts)


def prompt_line(state: dict, settings: Settings, now: float | None = None) -> str:
    text = summary(state, settings, now)
    if not text:
        return ""
    return f"（她的孩子：{text}。孩子不参与亲密场景；如果就在旁边，她会先顾及孩子。）"


def self_care(state: dict, settings: Settings, now: float | None = None) -> bool:
    return any(row.get("care_mode") == "self" for row in data(state))


def maybe_interrupt(state: dict, settings: Settings, now: float | None = None) -> dict | None:
    """自己带孩子时，亲密场景开始可能被孩子打断。"""
    if not settings.bool("children.intimacy_interrupt_enabled"):
        return None
    if not self_care(state, settings, now):
        return None
    now = now or util.now_ts()
    rows = [row for row in data(state)
            if row.get("care_mode") == "self" and _months(row, now) < 12 * max(
                1, settings.int("children.intimacy_child_max_age_years", 1, 18))]
    if not rows:
        return None
    chance = settings.float("children.intimacy_interrupt_chance", 0.0, 100.0)
    if chance <= 0 or random.random() * 100 >= chance:
        return None
    line = prompts.text(state, "children", "interrupt")
    state["children_interrupt_note"] = {"at": now, "line": line}
    return {"line": line}
