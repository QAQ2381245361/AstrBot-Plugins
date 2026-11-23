"""让 private_companion 的月经周期在孕期"不生效"。

PC 的周期存在它自己的库里，只有一条 current 记录，结构是：
    role_state_records(owner_key, record_id='current', revision, updated_at, record_json)
    record_json.cycle_clock.applicability ∈ unknown / not_applicable / applicable

我们做的是 PC 自己的「手动对齐」等价物：把 applicability 改成
not_applicable、decision_origin 改成 manual。这样：
- PC 投影周期时会直接跳过（cycle.project 早退），提示词里不再出现经期/PMS；
- 它的 evolve() 看到 decision_origin=manual 会保留 applicability，
  所以后续它自己写状态也不会把周期又打开（除非有人在面板里手动对齐）。

刻意不动 revision / updated_at：
两者是 PC 乐观锁和时钟回归检查用的。我们只换 record_json 这一列，
PC 下一次正常写入仍能通过 expected_revision，并在 transform 里读到我们改过的
clock，从而继续保留 not_applicable。这样不会给它的后台维护制造冲突。

生产/结束后 restore()：把 applicability 还原，并把锚点整体往后挪"暂停了多少天"，
让周期从停下来的地方接着走，而不是凭空跳十个月。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import cyclemodel, util
from .settings import PC_DB, PC_CYCLE_BACKUP, Settings

BUSY_TIMEOUT_MS = 3000
APPLICABILITY = ("unknown", "not_applicable", "applicable")


def db_path(settings: Settings) -> Path:
    configured = settings.str("pregnancy.pc_db_path")
    return Path(configured) if configured else Path(PC_DB)


def backup_path() -> Path:
    return PC_CYCLE_BACKUP


def _pick(rows: list[dict], role_name: str, owner_key: str = "") -> dict | None:
    if not rows:
        return None
    if owner_key:
        for row in rows:
            if row.get("owner_key") == owner_key:
                return row
    for row in rows:
        changed = (row.get("record") or {}).get("changed_by") or {}
        if role_name and str(changed.get("subject_id") or "") == role_name:
            return row
    for row in rows:
        clock = (row.get("record") or {}).get("cycle_clock")
        if isinstance(clock, dict):
            return row
    return rows[0]


def load(settings: Settings) -> dict | None:
    """读当前角色记录。返回 {owner_key, revision, updated_at, record}。"""
    rows = cyclemodel.read_pc_records(db_path(settings))
    return _pick(rows, settings.str("pregnancy.pc_role_name"))


def load_by_owner(settings: Settings, owner_key: str) -> dict | None:
    rows = cyclemodel.read_pc_records(db_path(settings))
    return _pick(rows, settings.str("pregnancy.pc_role_name"), owner_key)


def _update(db: Path, owner_key: str, revision, new_record: dict) -> tuple[bool, str]:
    """带 revision 乐观锁地替换 record_json（整份替换，慎用）。"""
    payload = json.dumps(new_record, ensure_ascii=False, separators=(",", ":"))
    try:
        con = sqlite3.connect(str(db), timeout=BUSY_TIMEOUT_MS / 1000)
        try:
            con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            with con:
                cursor = con.execute(
                    "UPDATE role_state_records SET record_json = ? "
                    "WHERE owner_key = ? AND record_id = 'current' AND revision = ?",
                    (payload, owner_key, revision))
                changed = cursor.rowcount
        finally:
            con.close()
    except sqlite3.Error as error:
        return False, f"写库失败：{error}"
    if changed == 1:
        return True, ""
    return False, "记录在读取后被改过（revision 冲突）"


def patch(db: Path, owner_key: str, revision, changes: dict) -> tuple[bool, str]:
    """在同一个事务里"读→只改这几个字段→写回"，绝不整份覆盖。

    changes 里 `值 = None` 表示删掉这个键；`values` 特判成"只动列出的那几个字段"：
        {"values": {"energy": 70}} → 只改 values.energy，其它字段（busy/hunger/mood…）
        原样保留。

    这样就算我们手里的记录是旧的、或者 PC 刚写过别的字段，也不会被我们不认识的
    旧值盖回去（以前整份覆盖会把 PC 刚写的 energy 写回成旧值）。
    """
    payload_changes = json.dumps(changes, ensure_ascii=False)
    try:
        con = sqlite3.connect(str(db), timeout=BUSY_TIMEOUT_MS / 1000)
        try:
            con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            with con:
                row = con.execute(
                    "SELECT record_json FROM role_state_records "
                    "WHERE owner_key = ? AND record_id = 'current' AND revision = ?",
                    (owner_key, revision)).fetchone()
                if row is None:
                    return False, "记录在读取后被改过（revision 冲突）"
                try:
                    record = json.loads(row[0])
                except (TypeError, ValueError):
                    return False, "记录不是合法 JSON"
                if not isinstance(record, dict):
                    return False, "记录不是对象"
                apply_changes(record, changes)
                cursor = con.execute(
                    "UPDATE role_state_records SET record_json = ? "
                    "WHERE owner_key = ? AND record_id = 'current' AND revision = ?",
                    (json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                     owner_key, revision))
                if cursor.rowcount != 1:
                    return False, "记录在读取后被改过（revision 冲突）"
        finally:
            con.close()
    except sqlite3.Error as error:
        return False, f"写库失败：{error}"
    return True, ""


def apply_changes(record: dict, changes: dict) -> None:
    """把 changes 合并进 record（就地修改）。values 是逐字段合并，None 表示删除。"""
    for key, value in (changes or {}).items():
        if key == "values" and isinstance(value, dict):
            values = record.get("values")
            if not isinstance(values, dict):
                values = {}
                record["values"] = values
            for field, item in value.items():
                if item is None:
                    values.pop(field, None)
                else:
                    values[field] = item
            continue
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value


# ---------------------------------------------------------------- 暂停周期

def suppress(settings: Settings, *, now: float | None = None) -> dict:
    """把 PC 周期置为 not_applicable，并留一份原始 clock 备份。"""
    now = now or util.now_ts()
    db = db_path(settings)
    if not Path(db).is_file():
        return {"ok": False, "reason": f"找不到 private_companion 的库：{db}"}

    current = load(settings)
    if not current:
        return {"ok": False, "reason": "PC 库里没有角色状态记录（没启用或还没跑过）"}

    record = current["record"]
    clock = record.get("cycle_clock")
    if not isinstance(clock, dict):
        return {"ok": False, "reason": "PC 记录里没有 cycle_clock（周期没开）"}

    if str(clock.get("applicability") or "") == "not_applicable":
        return {"ok": True, "mode": "already", "owner_key": current["owner_key"]}

    new_clock = dict(clock)
    new_clock["applicability"] = "not_applicable"
    new_clock["decision_origin"] = "manual"
    changes = {
        "cycle_clock": new_clock,
        "cycle_paused_by": "astrbot_plugin_conception",
        "cycle_paused_reason": "受孕：孕期暂停月经周期",
    }

    ok, why = patch(db, current["owner_key"], current["revision"], changes)
    if not ok:
        # 常见原因是它刚写过一次：重读一次再试
        retry = load(settings)
        retry_clock = (retry or {}).get("record", {}).get("cycle_clock")
        if retry and isinstance(retry_clock, dict) and \
                str(retry_clock.get("applicability") or "") != "not_applicable" and \
                retry["owner_key"] == current["owner_key"]:
            retry_new_clock = dict(retry_clock)
            retry_new_clock["applicability"] = "not_applicable"
            retry_new_clock["decision_origin"] = "manual"
            ok, why = patch(db, retry["owner_key"], retry["revision"], {
                "cycle_clock": retry_new_clock,
                "cycle_paused_by": "astrbot_plugin_conception",
                "cycle_paused_reason": "受孕：孕期暂停月经周期",
            })
            if ok:
                current = retry
    if not ok:
        return {"ok": False, "reason": why}

    # 写入成功后再落备份：备份里存"改之前"的原记录，恢复时要用
    backup = {
        "owner_key": current["owner_key"],
        "revision": current["revision"],
        "updated_at": current["updated_at"],
        "subject": str((record.get("changed_by") or {}).get("subject_id") or ""),
        "clock": clock,
        "record": record,
        "suppressed_at": now,
        "suppressed_date": datetime.fromtimestamp(now).date().isoformat(),
        "written_by": "astrbot_plugin_conception",
    }
    if not util.write_json_atomic(backup_path(), backup):
        return {"ok": True, "mode": "db", "owner_key": current["owner_key"],
                "warning": "周期已暂停，但原始 clock 备份写入失败"}
    return {"ok": True, "mode": "db", "owner_key": current["owner_key"]}


def is_suppressed(settings: Settings) -> bool:
    current = load(settings)
    if not current:
        return False
    clock = current["record"].get("cycle_clock")
    return isinstance(clock, dict) and str(clock.get("applicability") or "") == "not_applicable"


def has_backup() -> bool:
    return backup_path().is_file()


# ---------------------------------------------------------------- 恢复周期

def _shift_clock(clock: dict, days: int) -> dict:
    """把周期锚点整体往后挪 days 天，让相位从暂停处接着走。"""
    result = dict(clock)
    if days <= 0:
        return result
    for key in ("anchor_date", "segment_start_date"):
        value = util.parse_date(result.get(key))
        if value is not None:
            result[key] = (value + timedelta(days=days)).isoformat()
    # 暂停前挂起的"下个周期计划"已经过期，丢掉；让 PC 按当前配置重新生成
    result["pending_plan"] = None
    result.pop("variation_plan", None)
    result["segment_start_number"] = 1
    return result


def _restored_clock(clock: dict, original: dict, days: int, today) -> dict:
    result = _shift_clock(clock, days)
    result["applicability"] = "applicable"
    result["decision_origin"] = "manual"
    result["initialization"] = "manual"
    if util.parse_date(result.get("anchor_date")) is None:
        result["anchor_date"] = today.isoformat()
        result["segment_start_date"] = today.isoformat()
        result["segment_start_number"] = 1
    return result


def restore(settings: Settings, *, now: float | None = None) -> dict:
    """把周期还原；锚点按实际暂停天数平移。

    返回 {"ok": bool, "restored": bool, "reason": str}
    """
    now = now or util.now_ts()
    backup = util.read_json(backup_path(), None)
    if not isinstance(backup, dict):
        return {"ok": True, "restored": False, "reason": "没有备份（周期本来就没被改过）"}

    db = db_path(settings)
    if not Path(db).is_file():
        return {"ok": False, "restored": False, "reason": f"找不到 PC 的库：{db}"}

    current = load_by_owner(settings, str(backup.get("owner_key") or ""))
    if not current:
        return {"ok": False, "restored": False, "reason": "PC 库里找不到要恢复的记录"}

    record = current["record"]
    clock = record.get("cycle_clock")
    if not isinstance(clock, dict):
        return {"ok": False, "restored": False, "reason": "记录里没有 cycle_clock"}

    original = backup.get("clock") or {}
    target = str(original.get("applicability") or "applicable")
    if target not in APPLICABILITY:
        target = "applicable"
    if target == "not_applicable":
        # 暂停前本来就没开周期：只把备份清掉，不擅自打开
        backup_path().unlink(missing_ok=True)
        return {"ok": True, "restored": False, "reason": "暂停前周期本来就没启用"}

    suppressed_date = util.parse_date(backup.get("suppressed_date"))
    today = datetime.fromtimestamp(now).date()
    days = max(0, (today - suppressed_date).days) if suppressed_date else 0

    changes = {
        "cycle_clock": _restored_clock(clock, original, days, today),
        "cycle_paused_by": None,
        "cycle_paused_reason": None,
    }

    ok, why = patch(db, current["owner_key"], current["revision"], changes)
    if not ok:
        retry = load_by_owner(settings, str(backup.get("owner_key") or ""))
        retry_clock = (retry or {}).get("record", {}).get("cycle_clock")
        if retry and isinstance(retry_clock, dict):
            ok, why = patch(db, retry["owner_key"], retry["revision"], {
                "cycle_clock": _restored_clock(retry_clock, original, days, today),
                "cycle_paused_by": None,
                "cycle_paused_reason": None,
            })
    if not ok:
        return {"ok": False, "restored": False, "reason": why}

    try:
        backup_path().unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True, "restored": True, "days": days,
            "reason": f"周期已恢复（锚点后移 {days} 天）"}


# ---------------------------------------------------------------- 数据库备份

def backup_db(settings: Settings, *, keep: int = 2) -> dict:
    """用 sqlite3 的在线备份接口复制一份 PC 库，受孕开始时做一次。"""
    if not settings.bool("pregnancy.backup_pc_db"):
        return {"ok": False, "reason": "配置里关掉了备份"}
    source = db_path(settings)
    if not Path(source).is_file():
        return {"ok": False, "reason": "找不到要备份的库"}
    target = Path(backup_path()).parent / f"pc_db_backup_{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=5)
        try:
            dst = sqlite3.connect(str(target))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except (sqlite3.Error, OSError) as error:
        return {"ok": False, "reason": f"备份失败：{error}"}
    try:
        backups = sorted(target.parent.glob("pc_db_backup_*.sqlite3"))
        for old in backups[:-keep]:
            old.unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True, "path": str(target)}


def describe(settings: Settings) -> str:
    current = load(settings)
    if not current:
        return "PC 周期：读不到记录"
    clock = current["record"].get("cycle_clock")
    if not isinstance(clock, dict):
        return "PC 周期：记录里没有 cycle_clock"
    applicability = str(clock.get("applicability") or "unknown")
    label = {"applicable": "生效中", "not_applicable": "已暂停（不生效）",
             "unknown": "未确定"}.get(applicability, applicability)
    backup = util.read_json(backup_path(), None)
    extra = ""
    if isinstance(backup, dict) and backup.get("suppressed_date"):
        extra = f"｜暂停于 {backup['suppressed_date']}"
    return f"PC 周期：{label}（记录 revision {current['revision']}）{extra}"
