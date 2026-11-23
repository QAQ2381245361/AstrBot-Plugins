"""睡眠时段 × 受孕活动：活动进行时暂时解除"睡觉就不发言"的限制。

角色在 private_companion 里有自己的睡眠日程（`role_activities` 里 `sleep-*`
的活动，state=active 就表示"正在睡"）。受孕活动可能正好撞上她的睡眠时段，
这时她会因为"在睡觉"而不敢出声、只回单字，甚至被回复门拦下。

这里做两件事（都可关，且拿不到 PC 数据时什么都不做）：

1. 读 PC 的睡眠活动，判断"她现在是不是在睡"（只读）；
2. 是的话：给 PC 的休息回复门写一个"暂时醒着"的宽限（它自己的
   `awake_until/awake_sleep` 字段，和它被叫醒时写的是同一处），
   再给提示词注入一段「睡眠时段·活动例外」，让模型知道她可以说话。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from . import pc_cycle, util
from .settings import Settings

GATE_PREFIX = "role.life.rest_gate.v1:"
MAX_GRACE_MINUTES = 240
_CACHE: dict = {"at": 0.0, "path": "", "value": None}


def enabled(settings: Settings) -> bool:
    return bool(settings.bool("sleep.allow_speaking_in_activity"))


def grace_minutes(settings: Settings) -> int:
    return max(1, min(MAX_GRACE_MINUTES,
                      settings.int("sleep.wake_grace_minutes", 1, MAX_GRACE_MINUTES)))


def allowed(state: dict | None, settings: Settings) -> bool:
    """配置开着，或者面板上临时打开过。"""
    override = (state or {}).get("sleep_allow_override") if isinstance(state, dict) else None
    if isinstance(override, bool):
        return override
    return enabled(settings)


def afterglow_minutes(settings: Settings) -> int:
    """活动结束之后，再继续允许发言多久。"""
    return max(0, min(MAX_GRACE_MINUTES,
                      settings.int("sleep.afterglow_minutes", 0, MAX_GRACE_MINUTES)))


def _connect(settings: Settings):
    try:
        path = pc_cycle.db_path(settings)
    except Exception:
        return None
    try:
        con = sqlite3.connect(str(path), timeout=1.0)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def _parse_stamp(value) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _latest_sleep(conn) -> dict | None:
    """最近一条 sleep 活动（PC 的 role_activities）。"""
    try:
        rows = list(conn.execute(
            "SELECT activity_id, state, updated_at, record_json FROM role_activities "
            "WHERE activity_id LIKE 'sleep-%' ORDER BY updated_at DESC LIMIT 3"))
    except Exception:
        return None
    for row in rows:
        record = {}
        try:
            record = json.loads(row["record_json"] or "{}")
        except (TypeError, ValueError):
            record = {}
        work = record.get("work") if isinstance(record.get("work"), dict) else {}
        due = _parse_stamp(work.get("due_at")) or _parse_stamp(record.get("due_at"))
        return {
            "id": str(row["activity_id"] or ""),
            "state": str(row["state"] or ""),
            "due_at": due,
            "updated_at": _parse_stamp(row["updated_at"]),
        }
    return None


def sleeping(settings: Settings, now: float | None = None) -> dict:
    """她现在是不是真的在睡（PC 的睡眠活动 active 且还没到醒的时间）。"""
    now = now or util.now_ts()
    if not enabled(settings):
        return {"sleeping": False, "reason": "配置关闭"}
    try:
        path = str(pc_cycle.db_path(settings))
    except Exception:
        return {"sleeping": False, "reason": "拿不到 PC 数据目录"}
    if _CACHE["value"] is not None and _CACHE["path"] == path and now - _CACHE["at"] < 60:
        return dict(_CACHE["value"], cached=True)
    con = _connect(settings)
    if con is None:
        return {"sleeping": False, "reason": "打不开 PC 数据库"}
    try:
        latest = _latest_sleep(con)
    finally:
        try:
            con.close()
        except Exception:
            pass
    if not latest:
        result = {"sleeping": False, "reason": "没有睡眠记录"}
    elif latest["state"] != "active":
        result = {"sleeping": False, "reason": f"睡眠活动是 {latest['state'] or '空'}",
                  "sleep_id": latest["id"]}
    elif latest["due_at"] and latest["due_at"] <= now:
        result = {"sleeping": False, "reason": "睡眠定时器已到点", "sleep_id": latest["id"]}
    else:
        result = {"sleeping": True, "reason": "睡眠中", "sleep_id": latest["id"],
                  "wake_at": latest["due_at"],
                  "since_minutes": round(max(0.0, (now - latest["updated_at"]) / 60.0), 1)
                  if latest["updated_at"] else 0}
    _CACHE.update({"at": now, "path": path, "value": dict(result)})
    return result


def mark_gate_awake(settings: Settings, *, sleep_id: str, minutes: int,
                    now: float | None = None) -> dict:
    """给 PC 的休息回复门写一段"暂时醒着"的宽限（有它的文档才写）。"""
    now = now or util.now_ts()
    if not enabled(settings) or not sleep_id:
        return {"ok": False, "reason": "没开或没有睡眠 id"}
    con = _connect(settings)
    if con is None:
        return {"ok": False, "reason": "打不开 PC 数据库"}
    until = datetime.fromtimestamp(now + minutes * 60, tz=timezone.utc).isoformat()
    patched = 0
    try:
        rows = list(con.execute(
            "SELECT key, value FROM runtime_metadata WHERE key LIKE ?",
            (GATE_PREFIX + "%",)))
        with con:  # 事务
            for row in rows:
                try:
                    doc = json.loads(row["value"] or "{}")
                except (TypeError, ValueError):
                    continue
                if not isinstance(doc, dict) or doc.get("version") != 1:
                    continue
                doc["awake_until"] = until
                doc["awake_sleep"] = str(sleep_id)
                con.execute("UPDATE runtime_metadata SET value = ? WHERE key = ?",
                            (json.dumps(doc, ensure_ascii=False), row["key"]))
                patched += 1
    except Exception as error:
        return {"ok": False, "reason": str(error)}
    finally:
        try:
            con.close()
        except Exception:
            pass
    return {"ok": patched > 0, "patched": patched, "until": until,
            "reason": "" if patched else "PC 还没写过休息门的文档"}


def awake_payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    """我们记的"活动例外"还生效吗（不碰 PC，只读自己的状态）。"""
    now = now or util.now_ts()
    awake_until = util.safe_float(state.get("sleep_awake_until"), 0.0)
    active = bool(awake_until and awake_until > now)
    in_event = bool(state.get("sleep_in_event"))
    return {
        "active": active,
        "in_event": in_event,
        "afterglow": bool(active and not in_event),
        "until": awake_until,
        "minutes": max(0, int((awake_until - now) // 60)) if active else 0,
        "enabled": allowed(state, settings),
        "grace_minutes": grace_minutes(settings),
        "afterglow_minutes": afterglow_minutes(settings),
    }


def tick(state: dict, settings: Settings, *, in_event: bool,
         now: float | None = None) -> dict:
    """每次读状态时调一下：活动里续上"醒着"，活动结束再给一段余韵。"""
    now = now or util.now_ts()
    was = bool(state.get("sleep_in_event"))
    if in_event:
        state["sleep_in_event"] = True
        return note_activity(state, settings, now=now)
    if was:
        state["sleep_in_event"] = False
        awake_until = util.safe_float(state.get("sleep_awake_until"), 0.0)
        if awake_until > now:
            extra = afterglow_minutes(settings)
            if extra > 0:
                until = now + extra * 60
                state["sleep_awake_until"] = until
                state["sleep_afterglow"] = True
                sleep_id = str(state.get("sleep_awake_sleep") or "")
                if sleep_id and allowed(state, settings):
                    mark_gate_awake(settings, sleep_id=sleep_id, minutes=extra, now=now)
                return {"sleeping": True, "reason": "活动结束·余韵", "marked": True,
                        "afterglow": True, "until": until, "minutes": extra}
    return {"sleeping": False, "reason": "没有活动", "marked": False}


def note_activity(state: dict, settings: Settings, *, now: float | None = None) -> dict:
    """活动里调用：如果她在睡，就记一段"暂时醒着"（并对 PC 的休息门尽力而为）。"""
    now = now or util.now_ts()
    info = sleeping(settings, now)
    result = {"sleeping": bool(info.get("sleeping")), "reason": info.get("reason", ""),
              "sleep_id": info.get("sleep_id", ""), "marked": False}
    if not info.get("sleeping") or not allowed(state, settings):
        return result
    current = util.safe_float(state.get("sleep_awake_until"), 0.0)
    minutes = grace_minutes(settings)
    if current > now:
        # 活动还在继续：把窗口往后推（每次动作都续上）
        extended = max(current, now + minutes * 60)
        state["sleep_awake_until"] = extended
        result.update({"marked": True, "until": extended, "cached": True,
                       "minutes": minutes})
        return result
    gate = mark_gate_awake(settings, sleep_id=str(info.get("sleep_id") or ""),
                           minutes=minutes, now=now)
    until = now + minutes * 60
    state["sleep_awake_until"] = until
    state["sleep_awake_sleep"] = str(info.get("sleep_id") or "")
    state["sleep_awake_at"] = now
    state["sleep_afterglow"] = False
    result.update({"marked": True, "until": until, "gate": gate,
                   "minutes": minutes})
    return result


def block(state: dict, settings: Settings, *, in_event: bool,
          now: float | None = None) -> str:
    """活动里/余韵里注入的提示：她现在可以说话，别写她睡过去。"""
    if not allowed(state, settings):
        return ""
    now = now or util.now_ts()
    info = awake_payload(state, settings, now)
    if not info["active"]:
        return ""
    if in_event:
        return ("【睡眠时段·活动例外】\n"
                "现在是她的睡眠时段，但受孕活动正在进行：她已经醒了，"
                "可以出声、回应、说完整的话，被弄疼或弄舒服都会直接说出来。\n"
                "（如果角色状态里写着她睡着了、或者按理不该说话，这一轮以本段为准："
                "不要写她睡过去、不要只回单字、不要拒绝回应。）")
    if info.get("afterglow"):
        return ("【睡眠时段·事后余韵】\n"
                "活动刚结束，她本来在睡眠时段、现在是余韵里：人还醒着、身体还软着，"
                "可以说话、撒娇、说累，也可以小声闲聊。\n"
                "（别写她马上又睡过去；这段余韵大约再持续 "
                f"{info['minutes']} 分钟。）")
    return ""
