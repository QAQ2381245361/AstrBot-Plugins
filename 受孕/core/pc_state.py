"""把孕期阶段/避孕等写进 private_companion 的角色状态（尽力而为）。

PC 的 record_json 里有 values.energy / values.conditions。我们只改这两处，
不动 revision（和周期暂停的做法一致），PC 下次自己维护状态时可能覆盖，
但当前这一轮它能读到。
"""

from __future__ import annotations

import json
import re

from . import pc_cycle
from .settings import PLUGIN_DATA_DIR, Settings

MARK_PREFIX = "怀孕"
# 只认我们自己写的格式「怀孕（第N个月·阶段[·N胎]）」，
# 不用 startswith("怀孕") —— 免得把模型自己写的「怀孕初期，容易累」之类条件删掉。
MARK_PATTERN = re.compile(r"^怀孕（第\d+个月·")


def _text(item) -> str:
    """PC 的 condition 是对象；我们早期版本写过裸字符串，这里两种都认。"""
    if isinstance(item, dict):
        return str(item.get("text") or "")
    return str(item)


def _is_mark(item) -> bool:
    return bool(MARK_PATTERN.match(_text(item)))


def _load(settings: Settings) -> dict | None:
    try:
        return pc_cycle.load(settings)
    except Exception:
        return None


def _write(settings: Settings, current: dict, changes: dict) -> tuple[bool, str]:
    """只改 changes 里列的字段（values 是逐字段合并），不整份覆盖。

    以前是"整份 record 写回"，如果手里那份是旧的（或 PC 刚写过别的字段），
    就会把 PC 的新值盖回去 —— 有一次就把 PC 刚修的 energy 78 写回成了 0。
    """
    try:
        return pc_cycle.patch(pc_cycle.db_path(settings),
                              current["owner_key"], current["revision"], changes)
    except Exception as error:
        return False, str(error)


def _conditions(record: dict) -> list:
    values = record.setdefault("values", {})
    raw = values.get("conditions")
    if not isinstance(raw, list):
        raw = []
        values["conditions"] = raw
    return raw


def _sanitize(conditions: list) -> bool:
    """剔掉非对象条目（旧版本写坏的裸字符串），返回是否改动过。

    private_companion 只认 {"kind","text","expires_at"} 对象：它读取时会做
    c["expires_at"]，列表里混进字符串会抛 TypeError，整段「角色当前状态」降级。
    """
    kept = [item for item in conditions if isinstance(item, dict)]
    if len(kept) == len(conditions):
        return False
    conditions[:] = kept
    return True


def sync_pregnancy(settings: Settings, month: int, stage_title: str,
                   fetuses: int = 1) -> dict:
    """把"怀孕（第N个月·阶段）"写进 PC 的 conditions（只动 conditions）。"""
    if not settings.bool("pregnancy.stage_pc_enabled"):
        return {"ok": False, "reason": "配置关闭"}
    current = _load(settings)
    if not current:
        return {"ok": False, "reason": "没有 PC 角色记录"}
    record = current["record"]
    conditions = _conditions(record)
    _sanitize(conditions)
    conditions[:] = [item for item in conditions if not _is_mark(item)]
    label = f"{MARK_PREFIX}（第{month}个月·{stage_title}"
    if fetuses > 1:
        label += f"·{fetuses}胎"
    label += "）"
    conditions.append({"kind": "other", "text": label, "expires_at": None})
    ok, why = _write(settings, current, {"values": {"conditions": conditions}})
    return {"ok": ok, "reason": why, "label": label}


def clear_pregnancy(settings: Settings) -> dict:
    current = _load(settings)
    if not current:
        return {"ok": False, "reason": "没有 PC 角色记录"}
    record = current["record"]
    conditions = _conditions(record)
    # 旧格式（裸字符串）也算"有标记"：_sanitize 会把它们剔掉，但必须触发写库，
    # 否则库里的脏数据会一直留着。
    dirty = _sanitize(conditions)
    before = len(conditions)
    conditions[:] = [item for item in conditions if not _is_mark(item)]
    if not dirty and len(conditions) == before:
        return {"ok": True, "reason": "本来就没有"}
    ok, why = _write(settings, current, {"values": {"conditions": conditions}})
    return {"ok": ok, "reason": why}


def is_staying_up(settings: Settings, keywords: list[str] | None = None) -> bool:
    """PC 角色状态里有没有“熬夜/失眠”之类的条件。"""
    current = _load(settings)
    if not current:
        return False
    words = [str(word) for word in (keywords or (
        "熬夜", "失眠", "睡不着", "没睡", "通宵", "还醒着")) if str(word).strip()]
    conditions = (current.get("record", {}).get("values", {}) or {}).get("conditions") or []
    text = "".join(_text(item) for item in conditions if isinstance(item, dict))
    return any(word in text for word in words)


def add_condition(settings: Settings, text: str, *, kind: str = "other",
                  marker: str = "ASMR助眠") -> dict:
    """给 PC 角色状态加一条临时条件（同 marker 旧条目会先清掉）。"""
    current = _load(settings)
    if not current:
        return {"ok": False, "reason": "没有 PC 角色记录"}
    record = current["record"]
    conditions = _conditions(record)
    _sanitize(conditions)
    conditions[:] = [
        item for item in conditions
        if not (isinstance(item, dict) and str(item.get("text") or "").startswith(marker))
    ]
    conditions.append({"kind": kind, "text": str(text)[:300], "expires_at": None})
    ok, why = _write(settings, current, {"values": {"conditions": conditions}})
    return {"ok": ok, "reason": why, "condition": text}


NIGHT_BYPASS_FILE = PLUGIN_DATA_DIR / "night_raid_bypass.json"


def set_night_raid_bypass(settings: Settings, until: float) -> bool:
    """给 PC 留一个临时标记：夜袭/余韵期间不限深夜开口。"""
    try:
        NIGHT_BYPASS_FILE.parent.mkdir(parents=True, exist_ok=True)
        NIGHT_BYPASS_FILE.write_text(
            json.dumps({"until": float(until)}, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def clear_night_raid_bypass() -> None:
    try:
        NIGHT_BYPASS_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def energy_skip_reason(before: int, delta: int) -> str:
    """什么时候不该再写 PC 精力（避免把已经是 0 的值反复写回）。"""
    if not delta:
        return "no_change"
    if before <= 0 and delta <= 0:
        return "zero_guard"
    return ""


def adjust_energy(settings: Settings, delta: int) -> dict:
    """给 PC 的 values.energy 加/减一点（0–100，只动 energy）。"""
    current = _load(settings)
    if not current:
        return {"ok": False, "reason": "没有 PC 角色记录"}
    values = current["record"].get("values")
    values = values if isinstance(values, dict) else {}
    try:
        before = int(float(values.get("energy") or 0))
    except (TypeError, ValueError):
        before = 0
    skip = energy_skip_reason(before, int(delta))
    if skip:
        return {"ok": False, "skipped": skip, "before": before,
                "reason": ("PC 精力已经是 0，跳过重复写低值" if skip == "zero_guard"
                           else "数值没变化，跳过写入")}
    after = max(0, min(100, before + int(delta)))
    # 和 PC 的「单次状态维护最多掉多少」保持一致：插件直接写 energy 也不能一次掉穿。
    capped = False
    limit = 20
    if int(delta) < 0 and after < before - limit:
        after = max(0, before - limit)
        capped = True
    ok, why = _write(settings, current, {"values": {"energy": after}})
    return {"ok": ok, "reason": why, "before": before, "after": after,
            "capped": capped}
