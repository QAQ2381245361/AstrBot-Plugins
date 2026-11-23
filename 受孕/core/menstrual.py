"""月经期的经血、卫生巾与内裤湿源。"""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path
import json

from . import clothing, prompts, util
from .settings import Settings

DEFAULT = {
    "blood_ml": 0.0, "last_tick": 0.0, "last_change": 0.0,
    "pad_ml": 0.0, "pad_sources": {}, "pad_full": False,
    "pad_change_due_at": 0.0,
    "change_until": 0.0, "change_bottom": "", "change_intruded": False,
    "change_toy": None,
}


def data(state: dict) -> dict:
    row = state.get("menstrual")
    if not isinstance(row, dict):
        row = dict(DEFAULT)
        state["menstrual"] = row
    for key, value in DEFAULT.items():
        row.setdefault(key, value)
    return row


def blood_ml(state: dict, settings: Settings, now: float | None = None) -> float:
    if not settings.bool("menstrual.enabled"):
        return 0.0
    return max(0.0, util.safe_float(data(state).get("blood_ml"), 0.0))


PAD_LABELS = {"pad": "卫生巾", "pad_liner": "护垫", "pad_regular": "日用卫生巾",
              "pad_night": "夜用卫生巾", "pad_pants": "安睡裤"}
PAD_MODELS = {"pad": "regular", "pad_liner": "liner", "pad_regular": "regular",
              "pad_night": "night", "pad_pants": "pants"}


def pad_key(state: dict, settings: Settings) -> str:
    key = str(clothing.worn(state, settings).get("pad", {}).get("key") or "")
    return key if key in PAD_LABELS else ""


def pad_worn(state: dict, settings: Settings) -> bool:
    return bool(pad_key(state, settings))


def pad_label(state: dict, settings: Settings) -> str:
    return PAD_LABELS.get(pad_key(state, settings), "")


def pad_capacity(state: dict | None, settings: Settings) -> float:
    key = pad_key(state, settings) if isinstance(state, dict) else "pad_regular"
    models = settings.config.get("menstrual", {}).get("pad_models")
    if not isinstance(models, dict):
        models = {}
    model = PAD_MODELS.get(key, "regular")
    value = models.get(model)
    if value is None:
        value = {"liner": 8.0, "regular": 20.0, "night": 35.0, "pants": 60.0}.get(model, 20.0)
    return max(1.0, util.safe_float(value, 20.0))


def choose_pad(state: dict, settings: Settings, now: float | None = None) -> str:
    if not settings.bool("menstrual.pad_auto_choose"):
        return "pad_regular"
    hour = datetime.fromtimestamp(now or util.now_ts()).hour
    if hour >= 22 or hour < 8:
        return "pad_pants"
    if hour < 10:
        return "pad_liner"
    return "pad_regular"


def pad_percent(state: dict, settings: Settings) -> float:
    cap = pad_capacity(state, settings)
    return round(min(100.0, max(0.0, util.safe_float(data(state).get("pad_ml"), 0.0)) / cap * 100), 1)


def add_pad_fluid(state: dict, settings: Settings, kind: str, amount: float,
                  now: float | None = None) -> float:
    """卫生巾吸收液体；返回实际吸收量。"""
    if not settings.bool("menstrual.enabled") or amount <= 0 or not pad_worn(state, settings):
        return 0.0
    row = data(state)
    cap = pad_capacity(state, settings)
    before = max(0.0, util.safe_float(row.get("pad_ml"), 0.0))
    take = min(max(0.0, amount), max(0.0, cap - before))
    if take <= 0:
        return 0.0
    row["pad_ml"] = round(before + take, 2)
    sources = row.get("pad_sources")
    if not isinstance(sources, dict):
        sources = {}
        row["pad_sources"] = sources
    sources[kind] = round(util.safe_float(sources.get(kind), 0.0) + take, 2)
    row["pad_full"] = row["pad_ml"] >= cap * 0.999
    return round(take, 2)


def pad_source_text(state: dict) -> str:
    sources = data(state).get("pad_sources")
    if not isinstance(sources, dict) or not sources:
        return ""
    names = [str(key) for key, value in sources.items() if util.safe_float(value, 0.0) > 0.05]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return "、".join(names[:-1]) + "和" + names[-1] + "混在一起"


def _mark_underwear(state: dict, cause: str, now: float) -> None:
    clothing.mark_panties_wet(state, cause, now=now)


def _fish_desire(state: dict, settings: Settings, amount: float) -> None:
    if amount <= 0:
        return
    try:
        path = Path(settings.str("sources.fish_heart_state"))
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        data["desire"] = round(min(100.0, max(0.0,
            util.safe_float(data.get("desire"), 0.0) + amount)), 2)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def changing(state: dict, now: float | None = None) -> bool:
    now = now or util.now_ts()
    return util.safe_float(data(state).get("change_until"), 0.0) > now


def _add_shame(state: dict, settings: Settings, amount: float,
               now: float) -> None:
    """这些来源的羞耻只会停在满溢前，不触发羞耻责怪事件。"""
    if amount <= 0:
        return
    from . import mood
    cap = min(99.99, max(0.0, settings.float("menstrual.pad_shame_cap", 0.0, 100.0)))
    current = mood.value_of(state, settings, "shame", now=now)
    room = max(0.0, cap - current)
    if room > 0:
        mood.adjust(state, settings, "shame", delta=min(amount, room), now=now)


def notice_text(state: dict, settings: Settings) -> str:
    stored = str(state.get("menstrual_notice_prompt") or "").strip()
    return stored or prompts.text(state, "clothing", "pad_notice")


def change_pad(state: dict, settings: Settings, *, now: float | None = None,
               seen: bool | None = None) -> dict:
    """开始换：先脱卫生巾和下装，耗时结束后由 finish_change 穿上新的。"""
    now = now or util.now_ts()
    row = data(state)
    old_sources = dict(row.get("pad_sources") or {})
    mixed = [str(k) for k, v in old_sources.items()
             if util.safe_float(v, 0.0) > 0.05 and str(k) != "经血"]
    if pad_worn(state, settings):
        clothing.remove(state, settings, "pad", now=now)
    toy = state.get("toy")
    if isinstance(toy, dict) and toy.get("key"):
        row["change_toy"] = dict(toy)
        state["toy"] = None
    bottom = str(clothing.worn(state, settings).get("bottom", {}).get("key") or "")
    if bottom:
        row["change_bottom"] = bottom
        clothing.remove(state, settings, "bottom", now=now)
    row.update({"pad_ml": 0.0, "pad_sources": {}, "pad_full": False,
                "pad_change_due_at": 0.0, "change_intruded": False,
                "change_until": now + max(0, settings.int(
                    "menstrual.pad_change_minutes", 0, 60)) * 60})
    from . import mood, wetness
    _add_shame(state, settings,
               settings.float("menstrual.pad_change_shame", 0.0, 100.0), now)
    mood.adjust(state, settings, "desire",
                delta=settings.float("menstrual.pad_change_desire", 0.0, 100.0), now=now)
    wetness.gain(state, settings,
                 extra=settings.float("menstrual.pad_change_wet", 0.0, 100.0), now=now)
    _fish_desire(state, settings,
                 settings.float("menstrual.pad_change_fish_desire", 0.0, 100.0))
    source_text = ""
    if mixed:
        if len(mixed) == 1:
            source_text = mixed[0]
        else:
            source_text = "、".join(mixed[:-1]) + "和" + mixed[-1]
        _add_shame(state, settings,
                   settings.float("menstrual.pad_mixed_shame", 0.0, 100.0), now)
        mood.adjust(state, settings, "desire",
                    delta=settings.float("menstrual.pad_mixed_desire", 0.0, 100.0), now=now)
        _fish_desire(state, settings,
                     settings.float("menstrual.pad_mixed_fish_desire", 0.0, 100.0))
        wetness.gain(state, settings,
                     extra=settings.float("menstrual.pad_mixed_wet", 0.0, 100.0), now=now)
        line = prompts.text(state, "clothing", "pad_mixed_remove",
                            source=source_text)
    else:
        line = prompts.text(state, "clothing", "pad_changing")
    try:
        from . import unbirth
        if unbirth.data(state).get("inside"):
            _add_shame(state, settings,
                       settings.float("menstrual.pad_unbirth_shame", 0.0, 100.0), now)
            mood.adjust(state, settings, "desire",
                        delta=settings.float("menstrual.pad_unbirth_desire", 0.0, 100.0), now=now)
            wetness.gain(state, settings,
                         extra=settings.float("menstrual.pad_unbirth_wet", 0.0, 100.0), now=now)
            _fish_desire(state, settings,
                         settings.float("menstrual.pad_unbirth_fish_desire", 0.0, 100.0))
            extra = prompts.text(state, "clothing", "pad_change_unbirth")
            if extra:
                line = (line + "\n" + extra) if line else extra
    except Exception:
        pass
    state["menstrual_note"] = {"at": now, "line": line, "seen": False}
    return {"ok": True, "line": line, "seen": False, "changing": True,
            "notice": notice_text(state, settings)}


def finish_change(state: dict, settings: Settings, *, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    if util.safe_float(row.get("change_until"), 0.0) > now:
        return {"ok": False, "reason": "还没换好"}
    result = clothing.wear(state, settings, "pad", choose_pad(state, settings, now=now))
    bottom = str(row.get("change_bottom") or "")
    if bottom:
        from . import state as state_mod
        if not state_mod.scene_active(state, settings):
            clothing.wear(state, settings, "bottom", bottom)
    row["change_bottom"] = ""
    row["change_until"] = 0.0
    row["change_toy"] = None
    seen = bool(row.get("change_intruded")) or (
        random.random() * 100 < settings.float("menstrual.pad_seen_chance", 0.0, 100.0))
    line = prompts.text(state, "clothing", "pad_change")
    if row.get("change_intruded"):
        line = prompts.text(state, "clothing", "pad_change_intruded") or line
    elif seen:
        from . import mood
        mood.adjust(state, settings, "shame",
                    delta=settings.float("menstrual.pad_seen_shame", 0.0, 100.0), now=now)
        _fish_desire(state, settings,
                     settings.float("menstrual.pad_seen_fish_desire", 0.0, 100.0))
        line = prompts.text(state, "clothing", "pad_seen") or line
    row["change_intruded"] = False
    state["menstrual_note"] = {"at": now, "line": line, "seen": seen}
    return {"ok": True, "line": line, "seen": seen, "changed": True}


def tick(state: dict, settings: Settings, *, phase: str = "",
         now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    if changing(state, now):
        if util.safe_float(row.get("change_until"), 0.0) > now:
            return {"changed": False, "changing": True}
        return finish_change(state, settings, now=now)
    last = util.safe_float(row.get("last_tick"), now)
    hours = max(0.0, min(6.0, (now - last) / 3600.0)) if last else 0.0
    row["last_tick"] = now
    if not settings.bool("menstrual.enabled"):
        row["blood_ml"] = 0.0
        state["menstrual_active"] = False
        return {"changed": False}
    state["menstrual_active"] = phase == "menstrual"
    if phase == "menstrual":
        base = settings.float("menstrual.flow_ml_per_hour", 0.0, 200.0)
        jitter = settings.float("menstrual.flow_jitter", 0.0, 1.0)
        rate = base * max(0.1, 1.0 + random.uniform(-jitter, jitter))
        cap = settings.float("menstrual.capacity_ml", 1.0, 500.0)
        row["blood_ml"] = round(min(cap, util.safe_float(row.get("blood_ml"), 0.0)
                                    + rate * hours), 2)
        # 卫生巾先吸收
        absorbed = add_pad_fluid(state, settings, "经血", util.safe_float(row.get("blood_ml"), 0.0), now=now)
        if absorbed:
            row["blood_ml"] = round(max(0.0, util.safe_float(row.get("blood_ml"), 0.0) - absorbed), 2)
        if not pad_worn(state, settings) and util.safe_float(row.get("blood_ml"), 0.0) > 0:
            _mark_underwear(state, "period", now)
        elif pad_worn(state, settings) and row.get("pad_full") and \
                util.safe_float(row.get("blood_ml"), 0.0) > 0:
            spill = min(util.safe_float(row.get("blood_ml"), 0.0),
                        max(0.5, util.safe_float(row.get("blood_ml"), 0.0) * 0.25))
            row["blood_ml"] = round(max(0.0, util.safe_float(row.get("blood_ml"), 0.0) - spill), 2)
            sources = row.get("pad_sources") if isinstance(row.get("pad_sources"), dict) else {}
            cause = "mix" if len([v for v in sources.values() if util.safe_float(v, 0.0) > 0]) > 1 else "period"
            _mark_underwear(state, cause, now)
    else:
        # 经期结束后，残余慢慢排掉
        drain = settings.float("menstrual.drain_ml_per_hour", 0.0, 200.0) * hours
        if drain:
            row["blood_ml"] = round(max(0.0, util.safe_float(row.get("blood_ml"), 0.0) - drain), 2)

    # 自动穿/换卫生巾
    if settings.bool("menstrual.auto_pad") and phase == "menstrual":
        try:
            from . import state as state_mod
            from . import sleep_inside
            busy = (state_mod.scene_active(state, settings)
                    or state_mod.daily_active(state, settings)
                    or sleep_inside.active(state))
        except Exception:
            busy = False
        if busy:
            return {"changed": False, "blood_ml": round(util.safe_float(row.get("blood_ml"), 0.0), 2)}
        if not pad_worn(state, settings):
            result = clothing.wear(state, settings, "pad", choose_pad(state, settings, now=now))
            if result.get("ok"):
                row["last_change"] = now
                state["menstrual_note"] = {
                    "at": now,
                    "line": prompts.text(state, "clothing", "pad_on")}
        elif pad_percent(state, settings) >= settings.float(
                "menstrual.change_at_percent", 1.0, 100.0):
            warn = max(0, settings.int("menstrual.pad_warn_minutes", 0, 60)) * 60
            due = util.safe_float(row.get("pad_change_due_at"), 0.0)
            if warn and not due:
                row["pad_change_due_at"] = now + warn
                return {"changed": False, "pre_notice": notice_text(
                    state, settings), "blood_ml": round(
                        util.safe_float(row.get("blood_ml"), 0.0), 2)}
            if due and now < due:
                return {"changed": False, "blood_ml": round(
                    util.safe_float(row.get("blood_ml"), 0.0), 2)}
            wait = max(1, settings.int("menstrual.change_min_minutes", 1, 240)) * 60
            if now - util.safe_float(row.get("last_change"), 0.0) >= wait:
                changed = change_pad(state, settings, now=now)
                return {"changed": True, "line": changed.get("line"),
                        "seen": bool(changed.get("seen")),
                        "notice": changed.get("notice")}
    return {"changed": False, "blood_ml": round(util.safe_float(row.get("blood_ml"), 0.0), 2)}


def _unbirth_inside(state: dict) -> bool:
    try:
        from . import unbirth
        return bool(unbirth.data(state).get("inside"))
    except Exception:
        return False


def payload(state: dict, settings: Settings, *, phase: str = "") -> dict:
    row = data(state)
    return {
        "enabled": settings.bool("menstrual.enabled"),
        "phase": phase,
        "active": bool(state.get("menstrual_active")),
        "blood_ml": round(util.safe_float(row.get("blood_ml"), 0.0), 2),
        "capacity_ml": round(settings.float("menstrual.capacity_ml", 1.0, 500.0), 1),
        "pad_worn": pad_worn(state, settings),
        "pad_ml": round(util.safe_float(row.get("pad_ml"), 0.0), 2),
        "pad_capacity_ml": round(pad_capacity(state, settings), 1),
        "pad_percent": pad_percent(state, settings),
        "pad_source": pad_source_text(state),
        "changing": changing(state),
        "toy_removed": bool(row.get("change_toy")),
        "unbirth_inside": _unbirth_inside(state),
        "pad_shame_cap": round(settings.float("menstrual.pad_shame_cap", 0.0, 100.0), 1),
        "note": (state.get("menstrual_note") or {}).get("line", ""),
        "pad_label": pad_label(state, settings),
        "settings": {
            "flow_ml_per_hour": settings.float("menstrual.flow_ml_per_hour", 0, 200),
            "flow_jitter": settings.float("menstrual.flow_jitter", 0, 1),
            "capacity_ml": settings.float("menstrual.capacity_ml", 1, 500),
            "drain_ml_per_hour": settings.float("menstrual.drain_ml_per_hour", 0, 200),
            "notice_text": notice_text(state, settings),
            "notice_default": prompts.text(state, "clothing", "pad_notice"),
            "pad_notice_chance": settings.float("menstrual.pad_notice_chance", 0, 100),
            "pad_warn_minutes": settings.int("menstrual.pad_warn_minutes", 0, 60),
            "pad_change_minutes": settings.int("menstrual.pad_change_minutes", 0, 60),
            "change_at_percent": settings.float("menstrual.change_at_percent", 1, 100),
            "change_min_minutes": settings.int("menstrual.change_min_minutes", 1, 240),
            "pad_auto_choose": settings.bool("menstrual.pad_auto_choose"),
            "pad_models": {
                "liner": settings.float("menstrual.pad_models.liner", 1, 500),
                "regular": settings.float("menstrual.pad_models.regular", 1, 500),
                "night": settings.float("menstrual.pad_models.night", 1, 500),
                "pants": settings.float("menstrual.pad_models.pants", 1, 500),
            },
        },
    }
