"""插入子宫：湿润/快感/高潮判定，疼痛，容量占用与扩张、溢出、退出退还。

- 足够湿润（`insert.wet_at`）且足够快感（`insert.pleasure_at`）才能进；
- 不够却硬来：很痛、掉快感、掉忍耐、只多一点点湿润；
- 正好在高潮时进：几乎没有痛感；
- 进入后占子宫容量（`insert.occupies_capacity` / `insert.capacity_ml`），
  会把子宫撑到「扩张」；撑满时把原来里面的东西挤出去（胎儿不会被挤出）；
- 退出：退还占用的容量，再判定剩下的东西还会不会撑着；不会就缩回去。
"""

from __future__ import annotations

import random

from . import endurance, fill, pregnancy, prompts, size, util, wetness
from .settings import Settings

DEFAULT = {"active": False, "at": 0.0, "ml": 0.0, "pain": 0.0, "force": False, "extra": ""}


def data(state: dict) -> dict:
    value = state.get("uterus_insert")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["uterus_insert"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def _cfg(state: dict, settings: Settings, key: str, default, low=0.0, high=1000.0):
    from . import tuning
    return tuning.get(state, "insert", key, settings.float(f"insert.{key}", low, high))
    return settings.float(f"insert.{key}", low, high)


def requirements(state: dict, settings: Settings) -> dict:
    wet = wetness.value_of(state, settings)
    pleasure = util.safe_float(state.get("pleasure"), 0.0)
    wet_at = _cfg(state, settings, "wet_at", 60.0)
    plea_at = _cfg(state, settings, "pleasure_at", 55.0)
    return {
        "wet": round(wet, 1), "wet_at": wet_at, "wet_ok": wet >= wet_at,
        "pleasure": round(pleasure, 1), "pleasure_at": plea_at, "pleasure_ok": pleasure >= plea_at,
        "orgasm": _recent_orgasm(state, settings),
    }


def _recent_orgasm(state: dict, settings: Settings) -> bool:
    at = util.safe_float(state.get("last_orgasm_at"), 0.0)
    window = settings.int("insert.orgasm_window_seconds", 0, 600)
    return bool(at) and util.now_ts() - at <= window


def _capacity(state: dict, settings: Settings) -> tuple[float, float, float]:
    """(基础容量, 当前有效容量, 当前里面的量)。"""
    info = fill.volume(state, settings)
    return (float(info["capacity_base"]), float(info["capacity_effective"]),
            float(info["ml"]))


def _set_stretch(state: dict, settings: Settings, total: float) -> dict:
    base = fill.capacity_base(state, settings)
    max_ratio = fill.stretch_ratio_max(state, settings)
    at = fill.stretch_at(state, settings)
    if base <= 0 or max_ratio <= 0:
        return {"expanded": False, "stretch": 0.0}
    ratio = total / base - 1.0
    if ratio < at:
        return {"expanded": False, "stretch": round(max(0.0, util.safe_float(
            state.get("uterus_stretch"), 0.0)), 3)}
    value = min(max_ratio, round(ratio, 3))
    state["uterus_stretch"] = value
    return {"expanded": True, "stretch": value}


def insertion_depth(state: dict, settings: Settings) -> dict:
    """算阴茎头实际能进到子宫里多少。

    总长减去阴道长度才是"能越过子宫颈的长度"；
    真正进去的部分再受阴茎头长度、子宫长度限制。
    """
    total = size.penis_length(state, settings)
    vagina = util.safe_float(
        size.vagina_length(state, settings).get("effective"), 0.0)
    head = size.penis_head_length(state, settings)
    uterus = max(1.0, size.uterus_length(state, settings))
    protrusion = max(0.0, total - vagina)
    depth = min(protrusion, head, uterus)
    return {"total": total, "vagina": vagina, "protrusion": round(protrusion, 2),
            "head": head, "uterus": uterus, "depth": round(depth, 2),
            "full": depth >= uterus - 0.01}


def stage_of(state: dict, settings: Settings) -> int:
    """1 才进来一点 / 2 几乎全进来 / 3 整个头都进来 / 4 子宫被插满。"""
    info = insertion_depth(state, settings)
    protrusion, head, uterus = info["protrusion"], info["head"], info["uterus"]
    if protrusion <= 0:
        return 1
    if uterus <= head and protrusion >= uterus:
        return 4
    if protrusion >= head:
        return 3
    if protrusion >= head * 0.55:
        return 2
    return 1


def enter(state: dict, settings: Settings, *, force: bool = False,
          now: float | None = None) -> dict:
    now = now or util.now_ts()
    info = data(state)
    if stage_of(state, settings) >= 3:
        state["ovary_open_at"] = now
    if info.get("active"):
        return {"ok": False, "reason": "已经在里面了"}
    ok, why = size.can_reach(state, settings, "uterus", now=now)
    if not ok:
        return {"ok": False, "reason": why}
    req = requirements(state, settings)
    ready = req["wet_ok"] and req["pleasure_ok"]
    if not ready and not force:
        return {"ok": False, "reason": "还不够湿或不够兴奋，进不去（可以强行，但会很痛）",
                "requirements": req}

    pain = 0.0
    push = False
    if not ready:
        pain = _cfg(state, settings, "force_pain", 12.0)
        push = True
        if settings.bool("insert.force_penalty_enabled"):
            state["pleasure"] = max(0.0, util.safe_float(state.get("pleasure"), 0.0)
                                    - _cfg(state, settings, "force_pleasure_drop", 8.0))
            endurance.add_extra(state, settings, -_cfg(state, settings, "force_endurance_drop", 10.0))
            wetness.gain(state, settings, extra=_cfg(state, settings, "force_wet_gain", 3.0), now=now)
    elif req["orgasm"]:
        pain = _cfg(state, settings, "orgasm_pain", 0.5)
    else:
        pain = _cfg(state, settings, "pain", 4.0)

    occupied = _cfg(state, settings, "capacity_ml", 10.0) if settings.bool(
        "insert.occupies_capacity") else 0.0
    base, capacity, ml = _capacity(state, settings)
    total = ml + occupied
    fetus = pregnancy.progress(state)
    overflow = 0.0
    extra_stretch = ""
    if fetus:
        # 有胎儿：不会被挤出，算额外扩张去容纳，仍旧有点痛
        extra_stretch = "fetus"
        pain += _cfg(state, settings, "fetus_pain", 2.0)
    elif total > capacity:
        overflow = total - capacity
        state["uterus_ml"] = round(max(0.0, ml - overflow), 2)
        state["uterus_overflow_at"] = now
        state["uterus_overflow_ml"] = round(overflow, 2)
        state["uterus_overflow_total"] = round(
            util.safe_float(state.get("uterus_overflow_total"), 0.0) + overflow, 2)
        total -= overflow

    stretched = _set_stretch(state, settings, total)
    info.update({"active": True, "at": now, "ml": round(occupied, 2),
                 "pain": round(pain, 1), "force": bool(push), "extra": extra_stretch})
    group = "uterus"
    lines = []
    if push:
        lines.append(prompts.text(state, group, "force", pain=round(pain, 1)))
    elif req["orgasm"]:
        lines.append(prompts.text(state, group, "orgasm"))
    lines.append(prompts.text(state, group, f"stage{stage_of(state, settings)}"))
    lines.append(prompts.text(state, group, "after"))
    if stretched.get("expanded"):
        lines.append(prompts.text(state, group, "expand",
                                  stretch=int(stretched["stretch"] * 100)))
    else:
        lines.append(prompts.text(state, group, "no_expand"))
    if overflow:
        lines.append(prompts.text(state, group, "overflow", ml=round(overflow, 1)))
    if extra_stretch == "fetus":
        lines.append(prompts.text(state, group, "fetus"))
    return {"ok": True, "pain": round(pain, 1), "force": bool(push),
            "overflow": round(overflow, 1), "stretched": stretched,
            "requirements": req, "stage": stage_of(state, settings),
        "depth": insertion_depth(state, settings),
        "lines": [line for line in lines if line],
            "payload": payload(state, settings, now=now)}


def exit(state: dict, settings: Settings, *, now: float | None = None) -> dict:
    now = now or util.now_ts()
    info = data(state)
    if not info.get("active"):
        return {"ok": False, "reason": "现在没有在里面"}
    info.update({"active": False, "at": 0.0, "ml": 0.0, "pain": 0.0, "force": False,
                 "extra": ""})
    # 退还占用的容量，再判定剩下的东西还会不会撑着
    base, capacity, ml = _capacity(state, settings)
    state["uterus_stretch"] = 0.0
    still = _set_stretch(state, settings, ml)
    lines = [prompts.text(state, "uterus", "exit")]
    lines.append(prompts.text(state, "uterus",
                              "expand" if still.get("expanded") else "no_expand",
                              stretch=int(still.get("stretch", 0.0) * 100)))
    return {"ok": True, "still_expanded": still.get("expanded", False),
            "lines": [line for line in lines if line],
            "payload": payload(state, settings, now=now)}


def active(state: dict) -> bool:
    return bool(data(state).get("active"))


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    info = data(state)
    req = requirements(state, settings)
    base, capacity, ml = _capacity(state, settings)
    current = capacity - ml
    return {
        "active": bool(info.get("active")),
        "pain": round(util.safe_float(info.get("pain"), 0.0), 1),
        "force": bool(info.get("force")),
        "extra": str(info.get("extra") or ""),
        "occupies_capacity": settings.bool("insert.occupies_capacity"),
        "capacity_ml": round(util.safe_float(info.get("ml"), 0.0), 1),
        "requirements": req,
        "ready": req["wet_ok"] and req["pleasure_ok"],
        "capacity": round(capacity, 1),
        "ml": round(ml, 1),
        "room": round(max(0.0, current), 1),
        "wet_at": req["wet_at"], "pleasure_at": req["pleasure_at"],
        "orgasm_window": settings.int("insert.orgasm_window_seconds", 0, 600),
    }


def block(state: dict, settings: Settings, *, in_scene: bool) -> str:
    info = data(state)
    if not info.get("active"):
        return ""
    req = requirements(state, settings)
    text = "【插入子宫】\n- 现在整根埋在子宫里，最深处被撑满，连动一下都清楚"
    if info.get("force"):
        text += "；刚才是硬闯进来的，现在还一阵阵发酸发痛"
    if info.get("extra") == "fetus":
        text += "；里面还有胎儿，被挤得发胀，隐隐作痛"
    text += f"（湿润 {req['wet']}、快感 {req['pleasure']}）"
    return text
