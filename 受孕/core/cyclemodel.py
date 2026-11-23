"""生理期阶段：读 private_companion 的周期，或者用插件自己的模拟周期。

private_companion 的周期存在它自己的 SQLite 里：
    role_state_records.record_json -> cycle_clock
cycle_clock 的结构（schema 2）大致是：
    {"applicability": "applicable"|"not_applicable"|"unknown",
     "anchor_date": "2026-11-04", "phases": [{"phase": "menstrual", "days": 5}, ...],
     "segment_start_date": "...", "segment_start_number": 1,
     "pending_plan": {...}, "variation_enabled": true, "variation_seed": "...",
     "variation_version": 1, "variation_plan": {...}}
这里只读，不写；写周期的事交给 pc_cycle.py，受孕时才动。

为了和 PC 的投影**完全一致**，这里照搬了它 cycle.project() 的三条规则：
  1. 用 segment_start_date / segment_start_number 当周期起点（不是 anchor_date）；
  2. pending_plan 到 effective_date 之后就切换成新阶段天数、并把起点挪到那天；
  3. variation_enabled 时按它自己的 digest 算法做"每周期最多挪一天"的变化。
这样在 PC 面板里改锚点、改阶段天数、改周期变化，这边下一轮就跟着变。

读不到 PC 周期时退回插件自己的 28 天模拟周期，保证「生理期受孕概率」
始终有东西可算。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from . import util
from .settings import Settings

PHASES = ("menstrual", "follicular", "pre_ovulation", "ovulation", "luteal", "pms")
PHASE_LABELS = {
    "menstrual": "月经期",
    "follicular": "卵泡期",
    "pre_ovulation": "排卵前期",
    "ovulation": "排卵期",
    "luteal": "黄体期",
    "pms": "经前期",
    "recovery": "经期后恢复期",
    "paused": "孕期（周期暂停）",
    "unknown": "未知",
    "postpartum": "产后恢复期",
}
# 易孕期，只用于文案提示，不参与计算
FERTILE_PHASES = ("pre_ovulation", "ovulation")


def phase_label(phase: str) -> str:
    return PHASE_LABELS.get(str(phase or "").lower(), str(phase or "未知"))


# ---------------------------------------------------------------- private_companion

def _read_rows(db_path: Path) -> list[dict]:
    if not Path(db_path).is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
        try:
            rows = con.execute(
                "SELECT owner_key, revision, updated_at, record_json "
                "FROM role_state_records WHERE record_id = 'current' "
                "ORDER BY updated_at DESC").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    result = []
    for owner_key, revision, updated_at, raw in rows:
        record = util.read_json_text(raw)
        if not isinstance(record, dict):
            continue
        result.append({
            "owner_key": owner_key,
            "revision": revision,
            "updated_at": updated_at,
            "record": record,
        })
    return result


def read_pc_records(db_path) -> list[dict]:
    """读 private_companion 的 current 记录（所有角色，按更新时间倒序）。"""
    return _read_rows(Path(str(db_path or "")))


def read_pc_clock(db_path, role_name: str = "") -> dict | None:
    """取当前角色的 cycle_clock。

    返回 {"owner_key", "revision", "updated_at", "clock", "subject"}；
    多条记录时优先取 changed_by.subject_id == role_name 的那条。
    """
    rows = _read_rows(Path(str(db_path or "")))
    if not rows:
        return None
    picked = None
    for row in rows:
        changed = (row["record"] or {}).get("changed_by") or {}
        subject = str(changed.get("subject_id") or "")
        if role_name and subject == role_name:
            picked = row
            break
    if picked is None:
        for row in rows:
            clock = (row["record"] or {}).get("cycle_clock")
            if isinstance(clock, dict):
                picked = row
                break
    if picked is None:
        return None
    clock = (picked["record"] or {}).get("cycle_clock")
    if not isinstance(clock, dict):
        return None
    changed = (picked["record"] or {}).get("changed_by") or {}
    return {
        "owner_key": picked["owner_key"],
        "revision": picked["revision"],
        "updated_at": picked["updated_at"],
        "clock": clock,
        "subject": str(changed.get("subject_id") or ""),
    }


def clock_applicable(clock: dict | None) -> bool:
    return isinstance(clock, dict) and str(clock.get("applicability") or "") == "applicable"


# ---------------------------------------------------------------- 通用相位计算（与 PC 投影等价）

def _encode(value) -> str:
    """和 private_companion 的 encode() 一样：排序键、ASCII、紧凑分隔符。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value) -> str:
    return hashlib.sha256(_encode(value).encode("utf-8")).hexdigest()


def _variation_choose(phases: list[dict], seed: str, number: int, version: int) -> list[dict]:
    """照搬 PC 的 cycle_variation.choose()：最多把一天从某个阶段挪到另一个阶段。"""
    result = [dict(item) for item in phases]
    token = int(_digest(["cycle-variation", version, seed, number, phases]), 16)
    transfers = [
        (plus, minus)
        for plus, gain in enumerate(phases)
        for minus, loss in enumerate(phases)
        if plus != minus
        and gain.get("days", 0) < (120 if gain.get("phase") == "recovery" else 30)
        and loss.get("days", 0) > (4 if loss.get("phase") == "recovery" else 1)
    ]
    if token % 3 and transfers:
        plus, minus = transfers[(token // 3) % len(transfers)]
        result[plus]["days"] = int(result[plus].get("days", 0)) + 1
        result[minus]["days"] = int(result[minus].get("days", 0)) - 1
    return result


def _variation_current(clock: dict, phases: list[dict], start: date, number: int) -> list[dict]:
    """照搬 PC 的 cycle_variation.current()：优先用存下来的计划，否则现算。"""
    key = {
        "cycle_number": number,
        "cycle_start_date": start.isoformat(),
        "base_phases": phases,
        "version": clock.get("variation_version"),
    }
    saved = clock.get("variation_plan")
    if isinstance(saved, dict) and all(saved.get(name) == value for name, value in key.items()):
        return [dict(item) for item in saved.get("phases") or []]
    return _variation_choose(phases, str(clock.get("variation_seed") or ""),
                             number, clock.get("variation_version"))


def _segment(clock: dict, today: date) -> tuple[date, int, list[dict], bool] | None:
    """等价于 PC 的 _calendar()：算当前这一段的起点、周期号和阶段表。"""
    anchor = util.parse_date(clock.get("anchor_date"))
    if anchor is None:
        return None
    start = util.parse_date(clock.get("segment_start_date")) or anchor
    number = util.safe_int(clock.get("segment_start_number"), 1)
    phases = clock.get("phases")
    if not isinstance(phases, list) or not phases:
        return None
    variation = bool(clock.get("variation_enabled", False))
    pending = clock.get("pending_plan")
    if isinstance(pending, dict):
        effective = util.parse_date(pending.get("effective_date"))
        if effective is not None and today >= effective:
            pending_phases = pending.get("phases")
            if isinstance(pending_phases, list) and pending_phases:
                start = effective
                number = util.safe_int(pending.get("cycle_number"), 1)
                phases = pending_phases
                variation = bool(pending.get("variation_enabled", variation))
    return start, number, phases, variation


def phase_from_clock(clock: dict | None, today: date) -> dict | None:
    """算今天是哪个阶段——和 PC 的 cycle.project() 用同一套规则。

    与旧版（只看 anchor + phases）的区别：
      - 用 segment_start_date / segment_start_number 当这一段起点；
      - 到 pending_plan 的生效日之后，切到新阶段天数并重算周期号；
      - variation_enabled 时按 PC 的 digest 算法做每周期变化。
    """
    if not isinstance(clock, dict):
        return None
    segment = _segment(clock, today)
    if segment is None:
        return None
    start, number, phases, variation = segment
    anchor = util.parse_date(clock.get("anchor_date"))
    if anchor is None or today < anchor:
        return None
    total = 0
    for item in phases:
        try:
            days = int(item.get("days") or 0)
        except (TypeError, ValueError, AttributeError):
            return None
        if days < 0:
            return None
        total += days
    if total <= 0:
        return None

    completed, offset = divmod((today - start).days, total)
    cycle_start = start + timedelta(days=completed * total)
    cycle_number = completed + number
    if variation:
        try:
            phases = _variation_current(clock, phases, cycle_start, cycle_number)
        except (TypeError, ValueError):
            pass
    for index, item in enumerate(phases):
        try:
            days = int(item.get("days") or 0)
        except (TypeError, ValueError):
            return None
        if days > 0 and offset < sum(int(p.get("days") or 0) for p in phases[:index]) + days:
            walked = sum(int(p.get("days") or 0) for p in phases[:index])
            next_item = phases[(index + 1) % len(phases)] if phases else {}
            return {
                "phase": str(item.get("phase") or "unknown"),
                "day": offset + 1,
                "total": total,
                "phase_day": offset - walked + 1,
                "phase_days": days,
                "cycle_number": cycle_number,
                "cycle_start": cycle_start,
                "next_phase": str(next_item.get("phase") or "unknown"),
                "phase_index": index,
                "phases": [{"phase": str(p.get("phase") or "unknown"),
                            "days": int(p.get("days") or 0)} for p in phases],
            }
    return None


# ---------------------------------------------------------------- 插件自己的周期

def own_clock(settings: Settings, state: dict, today: date) -> dict:
    """插件自己的模拟周期；第一次用到时落一个锚点并存进 state。"""
    store = state.setdefault("own_cycle", {})
    anchor = util.parse_date(store.get("anchor_date"))
    if anchor is None:
        configured = util.parse_date(settings.str("cycle.own_anchor_date"))
        if configured is not None:
            anchor = configured
        else:
            phases = settings.own_cycle_days()
            total = sum(item["days"] for item in phases) or 28
            seed = hashlib.sha1(f"{state.get('created_at', '')}|{today.isoformat()}".encode()).hexdigest()
            offset = int(seed[:8], 16) % total
            anchor = today - timedelta(days=offset)
        store["anchor_date"] = anchor.isoformat()
    store.setdefault("phases", settings.own_cycle_days())
    return {
        "anchor_date": store["anchor_date"],
        "phases": store.get("phases") or settings.own_cycle_days(),
        "applicability": "applicable",
        "decision_origin": "plugin",
        "timezone": "Asia/Shanghai",
    }


# ---------------------------------------------------------------- 汇总

def resolve(settings: Settings, state: dict, today: date | None = None,
            *, pregnant: bool, postpartum: bool, pc_clock: dict | None = None) -> dict:
    """算出今天处于哪个阶段，并说明来源。

    pregnant 优先级最高：孕期周期整体暂停（PC 侧也会被置为 not_applicable）。
    """
    today = today or util.today()
    if pregnant:
        return {"phase": "paused", "day": None, "total": None, "source": "pregnancy",
                "applicable": False, "label": phase_label("paused")}
    if postpartum:
        return {"phase": "recovery", "day": None, "total": None, "source": "postpartum",
                "applicable": True, "label": phase_label("recovery")}

    source_mode = settings.str("cycle.source").lower() or "auto"
    if source_mode in ("auto", "pc") and clock_applicable(pc_clock):
        info = phase_from_clock(pc_clock, today)
        if info:
            info.update(source="private_companion", applicable=True,
                        label=phase_label(info["phase"]))
            return info

    if source_mode in ("auto", "own"):
        clock = own_clock(settings, state, today)
        info = phase_from_clock(clock, today)
        if info:
            info.update(source="own", applicable=True,
                        label=phase_label(info["phase"]))
            return info

    return {"phase": "unknown", "day": None, "total": None, "source": "none",
            "applicable": False, "label": phase_label("unknown")}


def describe(cycle: dict) -> str:
    phase = str(cycle.get("phase") or "unknown")
    label = cycle.get("label") or phase_label(phase)
    day = cycle.get("day")
    total = cycle.get("total")
    source = cycle.get("source")
    source_label = {
        "private_companion": "PC 周期",
        "own": "插件周期",
        "pregnancy": "孕期暂停",
        "postpartum": "产后恢复",
        "none": "无周期数据",
    }.get(str(source), str(source or "—"))
    if day and total:
        return f"{label}（第 {day}/{total} 天，{source_label}）"
    return f"{label}（{source_label}）"
