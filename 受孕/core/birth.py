"""生产：临产期 → 生产前 → 生产中 → 完成。

- 怀孕剩下 `birth.due_days` 天时自动进入「临产期」，临产期持续 `birth.due_days` 天；
- 之后「生产前」`birth.pre_minutes` 分钟，「生产中」`birth.active_minutes` 分钟，然后完成；
- 全靠**读的时候按时间推进**（懒结算），没有定时器；插件没开着时阶段停在原地，
  下次打开发现隔了很久，会把阶段时间往后推 `birth.resume_delay_seconds`，稍过一会再继续；
- 生产中疼痛随时间涨；主人说安抚/帮助的话（关键词可调）会降疼痛（幅度可调）；
- 羊水破会加大量湿润（不加欲）；处女膜未破时会破、但疼痛不叠加，只是能感觉到；
- 阶段切换会返回事件，由 main 主动发一条（不受睡眠发言限制）。
"""

from __future__ import annotations

from . import body, prompts, util, wetness
from .settings import Settings

STAGES = ("due", "pre", "active", "done")
STAGE_LABELS = {"": "还没有", "due": "临产期", "pre": "生产前", "active": "生产中", "done": "生产完成"}
DEFAULT = {"stage": "", "stage_at": 0.0, "started_at": 0.0, "last_tick": 0.0,
           "pain": 0.0, "water_at": 0.0, "comfort_at": 0.0, "hymen": False,
           "resumed_at": 0.0}


def data(state: dict) -> dict:
    value = state.get("birth")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["birth"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def enabled(settings: Settings) -> bool:
    return settings.bool("birth.enabled")


def stage_of(state: dict) -> str:
    return str(data(state).get("stage") or "")


def in_progress(state: dict) -> bool:
    return stage_of(state) in ("due", "pre", "active")


def due_days(settings: Settings) -> float:
    return settings.float("birth.due_days", 0.0, 60.0)


def pre_minutes(settings: Settings) -> int:
    return max(0, settings.int("birth.pre_minutes", 0, 1440))


def active_minutes(settings: Settings) -> int:
    return max(0, settings.int("birth.active_minutes", 0, 1440))


def _num(state: dict, settings: Settings, key: str, lo: float = 0.0,
         hi: float = 100.0) -> float:
    from . import tuning
    return tuning.get(state, "birth", key, settings.float(f"birth.{key}", lo, hi))


def comfort_keywords(settings: Settings, state: dict | None = None) -> list[str]:
    if isinstance(state, dict):
        rows = state.get("birth_comfort_keywords")
        if isinstance(rows, list) and rows:
            return [str(word).strip() for word in rows if str(word).strip()]
    rows = settings.list("birth.comfort_keywords") or []
    if not rows:
        raw = settings.str("birth.comfort_keywords") if hasattr(settings, "str") else ""
        rows = [part.strip() for part in str(raw).replace("，", ",").split(",") if part.strip()]
    return [str(word).strip() for word in rows if str(word).strip()]


def pain_max(settings: Settings, state: dict | None = None) -> float:
    return max(1.0, _num(state, settings, "pain_max", 1.0, 100.0))


def active(state: dict) -> bool:
    return stage_of(state) in ("pre", "active")


def _days_left(progress: dict, now: float) -> float:
    try:
        return float(progress.get("days_left") or 0.0)
    except (TypeError, ValueError):
        return 999.0


def _set_stage(state: dict, settings: Settings, stage: str, now: float) -> dict:
    row = data(state)
    row["stage"] = stage
    row["stage_at"] = now
    if stage == "due" and not row.get("started_at"):
        row["started_at"] = now
    line = prompts.text(state, "birth", stage if stage in ("due", "pre", "active", "done") else "")
    return {"stage": stage, "label": STAGE_LABELS.get(stage, stage), "line": line}


def _start_due(state: dict, settings: Settings, now: float) -> dict | None:
    if not enabled(settings) or stage_of(state):
        return None
    try:
        from . import pregnancy
        progress = pregnancy.progress(state, now=now)
    except Exception:
        return None
    if not progress:
        return None
    if _days_left(progress, now) > due_days(settings):
        return None
    return _set_stage(state, settings, "due", now)


def _apply_pain(state: dict, settings: Settings, stage: str, now: float) -> float:
    row = data(state)
    base = {"due": _num(state, settings, "pain_due", 0.0, 100.0),
            "pre": _num(state, settings, "pain_pre", 0.0, 100.0),
            "active": _num(state, settings, "pain_active", 0.0, 100.0)}.get(stage, 0.0)
    elapsed = max(0.0, now - util.safe_float(row.get("stage_at"), now)) / 60.0
    pain = base + elapsed * _num(state, settings, "pain_per_minute", 0.0, 100.0)
    pain = max(pain, util.safe_float(row.get("pain"), 0.0))
    row["pain"] = round(min(pain_max(settings, state), max(0.0, pain)), 1)
    return row["pain"]


def tick(state: dict, settings: Settings, now: float | None = None) -> dict:
    """推进生产阶段；返回 {"changed": bool, "stage":..., "events":[...]}。"""
    now = now or util.now_ts()
    if not enabled(settings):
        return {"changed": False}
    row = data(state)
    events = []
    # 没在孕期、也没进入生产：清干净
    try:
        from . import pregnancy
        progress = pregnancy.progress(state, now=now)
    except Exception:
        progress = None

    if row.get("stage") == "done":
        return {"changed": False, "stage": "done", "events": []}

    if not progress and stage_of(state) not in ("done",):
        if stage_of(state):
            row.update({"stage": "", "stage_at": 0.0, "pain": 0.0})
        return {"changed": False}

    started = False
    if not stage_of(state):
        change = _start_due(state, settings, now)
        if change:
            events.append(change)
            started = True

    stage = stage_of(state)
    if not stage:
        return {"changed": False, "events": []}

    # 断线保护：隔了很久没读 → 把阶段时间往后推一点，缓缓继续
    last = util.safe_float(row.get("last_tick"), 0.0)
    gap_minutes = max(1, int(_num(state, settings, "gap_minutes", 1, 1440)))
    resume = max(0, int(_num(state, settings, "resume_delay_seconds", 0, 3600)))
    if last and stage in ("due", "pre", "active") and now - last > gap_minutes * 60:
        shift = max(0.0, (now - last) - resume)
        if shift > 0:
            row["stage_at"] = util.safe_float(row.get("stage_at"), now) + shift
            row["resumed_at"] = now
    row["last_tick"] = now

    # 阶段推进
    stage = stage_of(state)
    if stage == "due":
        duration = due_days(settings) * 86400
        if now - util.safe_float(row.get("stage_at"), now) >= duration:
            events.append(_set_stage(state, settings, "pre", now))
    stage = stage_of(state)
    if stage == "pre":
        if now - util.safe_float(row.get("stage_at"), now) >= pre_minutes(settings) * 60:
            events.append(_set_stage(state, settings, "active", now))
    stage = stage_of(state)
    if stage == "active":
        # 羊水破：加大量湿润（不加欲），只做一次
        if not util.safe_float(row.get("water_at"), 0.0):
            row["water_at"] = now
            wetness.gain(state, settings,
                         extra=_num(state, settings, "water_wet", 0.0, 100.0), now=now)
            events.append({"stage": "water", "label": "羊水破了",
                           "line": prompts.text(state, "birth", "water")})
            if settings.bool("birth.hymen_break"):
                relief = {"relief": 100.0}
                try:
                    hymen = body.rupture_hymen(state, settings, "生产",
                                               relief=relief.get("relief", 100.0))
                except Exception:
                    hymen = None
                if hymen:
                    row["hymen"] = True
                    events.append({"stage": "hymen", "label": "处女膜破了",
                                   "line": prompts.text(state, "birth", "hymen")})
        if now - util.safe_float(row.get("stage_at"), now) >= active_minutes(settings) * 60:
            events.append(_set_stage(state, settings, "done", now))
            row.update({"stage": "done", "stage_at": now, "pain": 0.0})
    stage = stage_of(state)
    if stage in ("due", "pre", "active"):
        _apply_pain(state, settings, stage, now)
    return {"changed": bool(events) or started, "stage": stage,
            "label": STAGE_LABELS.get(stage, stage), "events": events,
            "pain": round(util.safe_float(row.get("pain"), 0.0), 1)}


def needs_finish(state: dict) -> bool:
    return stage_of(state) == "done" and not data(state).get("finished")


def mark_finished(state: dict) -> None:
    data(state)["finished"] = True


def comfort(state: dict, settings: Settings, text: str, now: float | None = None) -> dict:
    """主人安抚/帮助：命中关键词就降疼痛。"""
    if not enabled(settings) or not active(state):
        return {}
    now = now or util.now_ts()
    row = data(state)
    if now - util.safe_float(row.get("comfort_at"), 0.0) < max(
            0, int(_num(state, settings, "comfort_cooldown_seconds", 0, 3600))):
        return {}
    words = comfort_keywords(settings, state)
    body_text = str(text or "")
    hit = next((word for word in words if word and word in body_text), "")
    if not hit:
        return {}
    relief = _num(state, settings, "comfort_relief", 0.0, 100.0)
    before = util.safe_float(row.get("pain"), 0.0)
    row["pain"] = round(max(0.0, before - relief), 1)
    row["comfort_at"] = now
    return {"ok": True, "hit": hit, "relief": relief,
            "pain": row["pain"],
            "line": prompts.text(state, "birth", "comfort", pain=row["pain"])}


def relief_pain(state: dict, settings: Settings, now: float | None = None) -> dict:
    """面板「安抚一下」：直接降一次产痛（和聊天关键词共用冷却）。"""
    if not enabled(settings) or not active(state):
        return {}
    now = now or util.now_ts()
    row = data(state)
    if now - util.safe_float(row.get("comfort_at"), 0.0) < max(
            0, int(_num(state, settings, "comfort_cooldown_seconds", 0, 3600))):
        return {}
    relief = _num(state, settings, "comfort_relief", 0.0, 100.0)
    before = util.safe_float(row.get("pain"), 0.0)
    row["pain"] = round(max(0.0, before - relief), 1)
    row["comfort_at"] = now
    return {"ok": True, "relief": relief, "pain": row["pain"]}


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    stage = stage_of(state)
    progress = None
    try:
        from . import pregnancy
        progress = pregnancy.progress(state, now=now)
    except Exception:
        progress = None
    return {
        "enabled": enabled(settings),
        "stage": stage,
        "label": STAGE_LABELS.get(stage, stage or "还没有"),
        "active": stage in ("pre", "active"),
        "in_progress": stage in ("due", "pre", "active"),
        "pain": round(util.safe_float(row.get("pain"), 0.0), 1),
        "pain_max": pain_max(settings, state),
        "left_minutes": _left_minutes(row, settings, stage, now),
        "days_left": round(_days_left(progress, now), 1) if progress else None,
        "due_days": due_days(settings),
        "pre_minutes": pre_minutes(settings),
        "active_minutes": active_minutes(settings),
        "keywords": comfort_keywords(settings, state),
        "relief": _num(state, settings, "comfort_relief", 0.0, 100.0),
    }


def _left_minutes(row: dict, settings: Settings, stage: str, now: float) -> int:
    at = util.safe_float(row.get("stage_at"), now)
    if stage == "due":
        total = due_days(settings) * 1440
    elif stage == "pre":
        total = pre_minutes(settings)
    elif stage == "active":
        total = active_minutes(settings)
    else:
        return 0
    elapsed = (now - at) / 60.0
    return max(0, int(total - elapsed))


def block(state: dict, settings: Settings, now: float | None = None) -> str:
    if not enabled(settings):
        return ""
    stage = stage_of(state)
    if stage not in ("due", "pre", "active", "done"):
        return ""
    row = data(state)
    line = prompts.text(state, "birth", stage)
    pain = util.safe_float(row.get("pain"), 0.0)
    extra = f"（现在产痛 {pain:.0f}/{pain_max(settings, state):.0f}）" if stage in ("pre", "active") else ""
    return f"【生产】\n- {STAGE_LABELS.get(stage, stage)}：{line}{extra}"


def clear(state: dict) -> None:
    state["birth"] = dict(DEFAULT)
