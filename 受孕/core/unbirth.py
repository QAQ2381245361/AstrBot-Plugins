"""Unbirth：缩小后钻进阴道/子宫，待在子宫里，最后被"生出来"。

- 缩小机/还原机：`shrink()` / `restore()`，比例可调（0.01–1）；
- 钻进需要：内裤脱了、缩小到总体积不超过子宫极限扩张体积；
- 待在子宫：占容量（按用户身高体重 × 缩小比例算体积），算"特殊的怀孕状态"，
  有独立的扩张档位（不引发/少量/大量/极限）；
- `birth_out()`：一步一步"生出"，主人可以逆着来，AstrBot 有对应反应；
- 默认关闭（`unbirth.enabled`）；配置、提示词、面板按钮齐全。
"""

from __future__ import annotations

import random
from . import body, clothing, endurance, intimacy, mood, prompts, size, util, wetness
from .settings import Settings

DEFAULT = {"ratio": 1.0, "shrink_at": 0.0, "inside": False, "enter_at": 0.0,
           "settle_at": 0.0, "expansion": "", "birth_step": 0, "volume_ml": 0.0,
           "resist": 0, "pos": "", "remaining": 0, "birth_at": 0.0,
           "last_step_at": 0.0, "step_line": "", "fail_streak": 0,
           "gave_up": False}
EXPANSIONS = ("none", "small", "mid", "extreme")
EXPANSION_LABELS = {"": "", "none": "不引发扩张", "small": "引发少量扩张",
                    "mid": "引发大量扩张", "extreme": "引发极限扩张"}


def enabled(settings: Settings, state: dict | None = None) -> bool:
    if isinstance(state, dict):
        override = state.get("unbirth_enabled")
        if isinstance(override, bool):
            return override
    return settings.bool("unbirth.enabled")


def _text(state: dict, key: str, **fmt) -> str:
    """经期优先用 _period 变体提示词。"""
    if state.get("menstrual_active"):
        line = prompts.text(state, "unbirth", f"{key}_period", **fmt)
        if line:
            return line
    return prompts.text(state, "unbirth", key, **fmt)


def data(state: dict) -> dict:
    value = state.get("unbirth")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["unbirth"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def inside(state: dict) -> bool:
    return bool(data(state).get("inside"))


def ratio(state: dict) -> float:
    return util.clamp(util.safe_float(data(state).get("ratio"), 1.0), 0.01, 1.0)


def resist_keywords(state: dict, settings: Settings) -> list[str]:
    rows = state.get("unbirth_resist_keywords")
    if isinstance(rows, list) and rows:
        return [str(word).strip() for word in rows if str(word).strip()]
    return list(settings.list("unbirth.resist_keywords") or [])


def _num(state: dict, settings: Settings, key: str, lo: float = 0.0,
         hi: float = 100.0) -> float:
    from . import tuning
    return tuning.get(state, "unbirth", key, settings.float(f"unbirth.{key}", lo, hi))


def user_body(state: dict, settings: Settings) -> dict:
    row = state.get("user_body") if isinstance(state.get("user_body"), dict) else {}
    height = util.clamp(util.safe_float(row.get("height_cm"), settings.float(
        "unbirth.user_height", 50.0, 250.0)), 50.0, 250.0)
    weight = util.clamp(util.safe_float(row.get("weight_kg"), settings.float(
        "unbirth.user_weight", 20.0, 300.0)), 20.0, 300.0)
    return {"height_cm": round(height, 1), "weight_kg": round(weight, 1)}


def volume_ml(state: dict, settings: Settings) -> float:
    """用户缩小后的体积（ml）：体重按 1kg≈1000ml 近似，再乘缩小比例的立方。"""
    body = user_body(state, settings)
    full = body["weight_kg"] * 1000.0
    return round(full * (ratio(state) ** 3), 2)


def limit_ml(state: dict, settings: Settings) -> float:
    try:
        from . import fill
        cap = fill.capacity_base(state, settings)
        stretch = fill.stretch_ratio_max(state, settings)
    except Exception:
        cap, stretch = 20.0, 0.35
    return round(cap * (1.0 + stretch) * _num(state, settings, "limit_factor", 0.1, 5.0), 2)


def min_ratio(state: dict, settings: Settings) -> float:
    body = user_body(state, settings)
    full = body["weight_kg"] * 1000.0
    limit = max(1.0, limit_ml(state, settings))
    if full <= limit:
        return 0.01
    return max(0.01, round((limit / full) ** (1.0 / 3.0), 3))


def shrink(state: dict, settings: Settings, ratio_value: float | None = None,
           now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings, state):
        return {"ok": False, "reason": "Unbirth 没开"}
    row = data(state)
    if row.get("inside"):
        return {"ok": False, "reason": "还在子宫里，先出来再调大小"}
    value = util.clamp(util.safe_float(
        ratio_value, _num(state, settings, "shrink_ratio", 0.01, 1.0)), 0.01, 1.0)
    row.update({"ratio": value, "shrink_at": now, "birth_step": 0})
    return {"ok": True, "ratio": value, "volume_ml": volume_ml(state, settings),
            "min_ratio": min_ratio(state, settings),
            "line": prompts.text(state, "unbirth", "shrink", ratio=value)}


def restore(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings, state):
        return {"ok": False, "reason": "Unbirth 没开"}
    row = data(state)
    if row.get("inside"):
        return {"ok": False, "reason": "还在子宫里，先出来再还原"}
    row.update({"ratio": 1.0, "shrink_at": now, "birth_step": 0})
    return {"ok": True, "ratio": 1.0, "line": prompts.text(state, "unbirth", "restore")}


def _expansion_of(state: dict, settings: Settings) -> str:
    vol = volume_ml(state, settings)
    limit = max(1.0, limit_ml(state, settings))
    share = vol / limit
    if share <= _num(state, settings, "expand_small", 0.0, 1.0) * 0.5:
        return "none"
    if share <= _num(state, settings, "expand_small", 0.0, 1.0):
        return "small"
    if share <= _num(state, settings, "expand_mid", 0.0, 1.0):
        return "mid"
    return "extreme"


def inside(state: dict, settings: Settings | None = None) -> bool:
    if settings is not None and not enabled(settings, state):
        return False
    return bool(data(state).get("inside"))


def settle(state: dict, settings: Settings, now: float | None = None) -> dict:
    """待在里面的时候按分钟持续加：快感/湿润/忍耐/子宫开发度/敏感度。"""
    if not enabled(settings, state):
        return {}
    row = data(state)
    if not row.get("inside"):
        return {}
    now = now or util.now_ts()
    last = util.safe_float(row.get("settle_at"), 0.0) or util.safe_float(
        row.get("enter_at"), 0.0) or now
    minutes = max(0.0, (now - last) / 60.0)
    cap = max(1, int(_num(state, settings, "inside_max_minutes", 1, 1440)))
    minutes = min(minutes, float(cap))
    row["settle_at"] = now
    if minutes <= 0:
        return {"minutes": 0.0}
    pleasure = _num(state, settings, "inside_pleasure", 0.0, 100.0) * minutes
    wet = _num(state, settings, "inside_wet", 0.0, 100.0) * minutes
    endurance_gain = _num(state, settings, "inside_endurance", 0.0, 100.0) * minutes
    dev = _num(state, settings, "inside_dev", 0.0, 100.0) * minutes
    sens = _num(state, settings, "inside_sens", 0.0, 10.0) * minutes
    if pleasure:
        state["pleasure"] = util.safe_float(state.get("pleasure"), 0.0) + pleasure
    if wet:
        wetness.gain(state, settings, extra=wet, now=now)
    if endurance_gain:
        endurance.add_extra(state, settings, endurance_gain)
    if dev or sens:
        intimacy.add_zone_bonus(state, settings, "uterus", dev=dev, sens=sens)
    return {"minutes": round(minutes, 1), "pleasure": round(pleasure, 2),
            "wet": round(wet, 2), "endurance": round(endurance_gain, 2),
            "dev": round(dev, 3), "sensitivity": round(sens, 4)}


def _hymen_phase(state: dict, settings: Settings, mode: str, now: float,
                 volume: float | None = None) -> dict | None:
    """通过处女膜：pass=钻过（可能只撑到，不破），break=撞破。"""
    if not body.hymen_intact(state):
        return None
    mode = "break" if str(mode or "").lower() in ("break", "撞破", "破") else "pass"
    if mode == "break":
        info = body.rupture_hymen(state, settings, "Unbirth 撞破处女膜", now=now,
                                  force=True, blood_key="unbirth")
        line = prompts.text(state, "unbirth", "hymen_break")
        result = {"mode": "break", "line": line, "ruptured": bool(info)}
        if info:
            result.update({"pain": info.get("pain"), "pleasure": info.get("pleasure", 0),
                           "blood": info.get("blood")})
        return result

    vol = util.safe_float(volume if volume is not None else volume_ml(state, settings), 0.0)
    hole = size.hymen_hole(state, settings)
    diameter = 2.0 * (3.0 * max(0.0, vol) / (4.0 * 3.1415926)) ** (1.0 / 3.0)
    if hole > 0 and diameter > hole * 3.0:
        return {"mode": "too_big", "blocked": True,
                "line": prompts.text(state, "unbirth", "hymen_too_big"),
                "diameter": round(diameter, 2), "hole": hole}
    damage = max(0.0, min(60.0, (diameter - hole) * 15.0))
    row = data(state)
    if damage > 0:
        added = body.add_hymen_damage(state, settings, damage, now=now,
                                      blood_key="unbirth")
        if added.get("ruptured"):
            return {"mode": "break", "line": prompts.text(state, "unbirth", "hymen_break"),
                    "ruptured": True, "blood": added.get("blood"),
                    "damage": added.get("damage"), "diameter": round(diameter, 2),
                    "hole": hole}
        state.setdefault("hymen", {}).setdefault("stretch_damage", 0.0)
        state["hymen"]["stretch_damage"] = max(
            util.safe_float(state["hymen"].get("stretch_damage"), 0.0), round(damage, 1))
    pleasure = _num(state, settings, "hymen_pass_pleasure", 0.0, 100.0)
    endurance_gain = _num(state, settings, "hymen_pass_endurance", 0.0, 100.0)
    wet = _num(state, settings, "hymen_pass_wet", 0.0, 100.0)
    desire = _num(state, settings, "hymen_pass_desire", 0.0, 100.0)
    if pleasure:
        state["pleasure"] = util.safe_float(state.get("pleasure"), 0.0) + pleasure
    if endurance_gain:
        endurance.add_extra(state, settings, endurance_gain)
    if wet:
        wetness.gain(state, settings, extra=wet, now=now)
    if desire:
        mood.adjust(state, settings, "desire", delta=desire, now=now)
    line = _text(state, "hymen_pass", damage=round(damage, 0))
    return {"mode": "pass", "line": line, "damage": round(damage, 1),
            "pleasure": pleasure, "endurance": endurance_gain, "wet": wet,
            "desire": desire, "diameter": round(diameter, 2), "hole": hole}


def enter(state: dict, settings: Settings, now: float | None = None,
          hymen_mode: str = "pass", location: str = "uterus") -> dict:
    now = now or util.now_ts()
    if not enabled(settings, state):
        return {"ok": False, "reason": "Unbirth 没开"}
    row = data(state)
    if row.get("inside"):
        return {"ok": False, "reason": "已经在里面了"}
    location = str(location or "uterus").lower()
    if location not in ("uterus", "tube", "ovary"):
        location = "uterus"
    if clothing.blocked(state, settings, "vagina")[0]:
        return {"ok": False, "reason": "内裤还没脱，进不去"}
    vol = volume_ml(state, settings)
    diameter = 2.0 * (3.0 * max(0.0, vol) / (4.0 * 3.1415926)) ** (1.0 / 3.0)
    if location == "tube":
        width = settings.float("size.tube_width", 0.01, 20.0)
        if diameter > width:
            return {"ok": False,
                    "reason": f"缩得还不够小：直径 {diameter:.2f}cm > 输卵管 {width:.2f}cm"}
    elif location == "ovary":
        width = settings.float("size.ovary_width", 0.01, 20.0) / 2.0
        if diameter > width:
            return {"ok": False,
                    "reason": f"缩得还不够小：直径 {diameter:.2f}cm > 卵巢可进入的 {width:.2f}cm"}
    limit = limit_ml(state, settings)
    if vol > limit:
        return {"ok": False, "reason": f"还太大了（{vol:.0f}ml > 子宫能容纳的 {limit:.0f}ml），再缩小一点"}
    hymen_info = _hymen_phase(state, settings, hymen_mode, now, vol)
    if hymen_info and hymen_info.get("blocked"):
        return {"ok": False, "reason": "太大，钻不过处女膜；只能选「撞破」",
                "hymen": hymen_info}
    total = total_steps(state, settings)
    labels = {"uterus": "子宫", "tube": "输卵管", "ovary": "卵巢"}
    row.update({"inside": True, "enter_at": now, "settle_at": now, "volume_ml": vol,
                "expansion": _expansion_of(state, settings), "birth_step": 0,
                "location": location,
                "pos": labels[location], "remaining": total, "birth_total": total,
                "birth_at": 0.0, "last_step_at": now, "step_line": "",
                "fail_streak": 0, "gave_up": False})
    pleasure = _num(state, settings, "enter_pleasure", 0.0, 100.0)
    endurance_gain = _num(state, settings, "enter_endurance", 0.0, 100.0)
    wet = _num(state, settings, "enter_wet", 0.0, 100.0)
    state["pleasure"] = util.safe_float(state.get("pleasure"), 0.0) + pleasure
    endurance.add_extra(state, settings, endurance_gain)
    wetness.gain(state, settings, extra=wet, now=now)
    line = _text(state,
                    f"{location}_enter" if location != "uterus" else "enter",
                    size=round(vol, 1))
    expansion = prompts.text(state, "unbirth", f"expand_{row['expansion']}")
    return {"ok": True, "volume_ml": vol, "expansion": row["expansion"],
            "hymen": hymen_info,
            "expansion_label": EXPANSION_LABELS.get(row["expansion"], ""),
            "pleasure": pleasure, "endurance": endurance_gain, "wet": wet,
            "lines": [line, expansion]}


def max_ratio(state: dict, settings: Settings) -> float:
    """在子宫里时，变大不能超过子宫极限扩张体积。"""
    body = user_body(state, settings)
    full = body["weight_kg"] * 1000.0
    limit = max(1.0, limit_ml(state, settings))
    if full <= limit:
        return 1.0
    return max(0.01, min(1.0, round((limit / full) ** (1.0 / 3.0), 3)))


def grow(state: dict, settings: Settings, delta: float | None = None,
         now: float | None = None) -> dict:
    """变大：体内最多长到子宫极限；在阴道里超过截面 3 倍会撑破处女膜。"""
    now = now or util.now_ts()
    if not enabled(settings, state):
        return {"ok": False, "reason": "Unbirth 没开"}
    row = data(state)
    step = _num(state, settings, "grow_step", 0.01, 1.0) if delta is None else delta
    old_ratio = ratio(state)
    target = util.clamp(old_ratio + max(0.0, util.safe_float(step, 0.0)), 0.01, 1.0)
    capped = False
    location = str(row.get("location") or "uterus") if row.get("inside") else ""
    ub_body = user_body(state, settings)
    full = max(1.0, ub_body["weight_kg"] * 1000.0)
    max_diameter = 0.0
    if location in ("tube", "ovary"):
        max_diameter = (settings.float("size.tube_width", 0.01, 20.0)
                        if location == "tube"
                        else settings.float("size.ovary_width", 0.01, 20.0) / 2.0)
    elif not row.get("inside"):
        max_diameter = size.vagina_width(state, settings) * 4.0
    if max_diameter:
        max_vol = 4.0 * 3.1415926 / 3.0 * (max_diameter / 2.0) ** 3
        cap = max(0.01, min(1.0, (max_vol / full) ** (1.0 / 3.0)))
        if target > cap:
            target = cap
            capped = True
    elif row.get("inside"):
        cap = max_ratio(state, settings)
        if target > cap:
            target = cap
            capped = True
    row.update({"ratio": round(target, 3), "shrink_at": now, "birth_step": 0})
    note = ""
    hymen_info = None
    if capped:
        if location == "tube":
            note = "在输卵管里只能长到输卵管能容纳的大小"
        elif location == "ovary":
            note = "在卵巢里最多只能长到卵巢大小的一半"
        elif not row.get("inside"):
            note = "在阴道里最多只能长到阴道宽度的 4 倍"
        else:
            note = "在子宫里只能长到子宫极限扩张的大小"
    if not row.get("inside"):
        ub_body = user_body(state, settings)
        full = ub_body["weight_kg"] * 1000.0
        vol = full * (target ** 3)
        diameter = 2.0 * (3.0 * max(0.0, vol) / (4.0 * 3.1415926)) ** (1.0 / 3.0)
        width = size.vagina_width(state, settings) if hasattr(size, "vagina_width") else 3.0
        if diameter > width * 3.0 and body.hymen_intact(state):
            info = body.rupture_hymen(state, settings, "Unbirth 变大撑破处女膜",
                               blood_key="unbirth",
                                      now=now, force=True)
            line = prompts.text(state, "unbirth", "hymen_grow_break", size=round(vol, 1))
            hymen_info = {"mode": "grow_break", "line": line,
                          "ruptured": bool(info), "diameter": round(diameter, 2),
                          "limit": round(width * 3.0, 2)}
    return {"ok": True, "ratio": round(target, 3), "volume_ml": volume_ml(state, settings),
            "max_ratio": max_ratio(state, settings), "capped": capped, "note": note,
            "hymen": hymen_info}


def exit(state: dict, settings: Settings, now: float | None = None,
         hymen_mode: str = "pass") -> dict:
    now = now or util.now_ts()
    row = data(state)
    if not row.get("inside"):
        return {"ok": False, "reason": "现在没在里面"}
    settle(state, settings, now=now)
    hymen_info = _hymen_phase(state, settings, hymen_mode, now,
                              util.safe_float(row.get("volume_ml"), 0.0))
    row.update({"inside": False, "enter_at": 0.0, "settle_at": 0.0,
                "expansion": "", "birth_step": 0, "resist": 0,
                "pos": "", "remaining": 0, "birth_total": 0, "birth_at": 0.0,
                "last_step_at": 0.0, "step_line": ""})
    return {"ok": True, "line": _text(state, "exit"),
            "hymen": hymen_info}


def request_enabled(state: dict, settings: Settings) -> bool:
    override = state.get("unbirth_request_enabled")
    if isinstance(override, bool):
        return override
    return settings.bool("unbirth.request_enabled")


def total_steps(state: dict, settings: Settings) -> int:
    """生在子宫里要几步：基础步数 + 从最深处往外多出来的步数。"""
    base = max(1, int(_num(state, settings, "birth_steps", 1, 20)))
    depth = max(0, int(_num(state, settings, "birth_depth_steps", 0, 10)))
    return base + depth


def pos_of(remaining: int, total: int) -> str:
    total = max(1, total)
    ratio = max(0.0, min(1.0, remaining / total))
    if remaining <= 0:
        return "阴道口"
    if ratio >= 0.75:
        return "子宫"
    if ratio >= 0.5:
        return "子宫颈"
    if ratio >= 0.25:
        return "阴道"
    return "阴道口"


def _advance(state: dict, settings: Settings, now: float, *, auto: bool = False) -> dict:
    row = data(state)
    total = max(1, util.safe_int(row.get("birth_total"), total_steps(state, settings)))
    current = util.safe_int(row.get("remaining"), total)
    remaining = max(0, min(current, total) - 1)
    row["remaining"] = remaining
    row["birth_step"] = util.safe_int(row.get("birth_step"), 0) + 1
    row["last_step_at"] = now
    row["pos"] = pos_of(remaining, total)
    if remaining <= 0:
        row.update({"inside": False, "enter_at": 0.0, "birth_at": 0.0,
                    "pos": "", "remaining": 0, "birth_total": 0,
                    "birth_step": 0, "resist": 0})
        line = prompts.text(state, "unbirth", "birth_done")
        return {"done": True, "remaining": 0, "pos": "", "line": line}
    key = "birth_auto" if auto else "birth_progress"
    line = prompts.text(state, "unbirth", key, pos=row["pos"], remaining=remaining,
                        total=total)
    row["step_line"] = line
    return {"done": False, "remaining": remaining, "pos": row["pos"], "line": line}


def tick_birth(state: dict, settings: Settings, now: float | None = None) -> dict:
    """正在生出时，剩余步数随时间减少；每次减少留一句提示。"""
    if not enabled(settings, state):
        return {}
    row = data(state)
    if not row.get("inside") or not row.get("birth_at"):
        return {}
    now = now or util.now_ts()
    minutes = max(1, int(_num(state, settings, "birth_step_minutes", 1, 240)))
    last = util.safe_float(row.get("last_step_at"), now)
    steps = int(max(0.0, (now - last) / 60.0) // minutes)
    if steps <= 0:
        return {}
    result = {}
    for _ in range(min(steps, 10)):
        result = _advance(state, settings, now, auto=True)
        if result.get("done"):
            break
    return result


def _birth_fail(state: dict, settings: Settings, reason: str,
                line: str = "") -> dict:
    row = data(state)
    streak = util.safe_int(row.get("fail_streak"), 0) + 1
    row["fail_streak"] = streak
    limit = max(1, int(_num(state, settings, "birth_giveup_after", 1, 20)))
    if streak >= limit:
        row.update({"fail_streak": 0, "gave_up": True, "birth_at": 0.0,
                    "step_line": ""})
        return {"ok": True, "failed": True, "gave_up": True,
                "step": row.get("birth_step"), "steps": total_steps(state, settings),
                "remaining": row.get("remaining"), "pos": row.get("pos"),
                "reason": reason,
                "line": prompts.text(state, "unbirth", "birth_giveup",
                                     reason=reason, tries=streak)}
    return {"ok": True, "failed": True, "gave_up": False,
            "step": row.get("birth_step"), "steps": total_steps(state, settings),
            "remaining": row.get("remaining"), "pos": row.get("pos"),
            "reason": reason, "streak": streak,
            "line": line or prompts.text(state, "unbirth", "birth_fail",
                                          chance=0, reason=reason)}


def birth_out(state: dict, settings: Settings, *, resist: bool = False,
              now: float | None = None, hymen_mode: str = "pass") -> dict:
    """一步一步生出来；resist=True 表示主人逆着来。"""
    now = now or util.now_ts()
    if not enabled(settings, state):
        return {"ok": False, "reason": "Unbirth 没开"}
    row = data(state)
    if not row.get("inside"):
        return {"ok": False, "reason": "现在没在里面"}
    location = str(row.get("location") or "uterus")
    if location in ("tube", "ovary"):
        line = prompts.text(state, "unbirth", "no_birth",
                            pos="输卵管" if location == "tube" else "卵巢")
        return {"ok": False, "line": line,
                "reason": "在输卵管/卵巢里没法生出来，只能先退回子宫或退出去"}
    ratio_now = ratio(state)
    min_ratio = _num(state, settings, "birth_min_ratio", 0.01, 1.0)
    if ratio_now < min_ratio:
        return _birth_fail(state, settings, "缩得太小，子宫和产道夹得太紧")

    started = bool(row.get("birth_at"))
    hymen_info = None
    if not started:
        row["birth_at"] = now
        row["last_step_at"] = now
        hymen_info = _hymen_phase(state, settings, hymen_mode, now,
                                  util.safe_float(row.get("volume_ml"), 0.0))
        if hymen_info and hymen_info.get("blocked"):
            return {"ok": False, "reason": "太大，钻不过处女膜；只能选「撞破」",
                    "hymen": hymen_info}
        if not row.get("remaining"):
            row["remaining"] = total_steps(state, settings)
        row["pos"] = pos_of(util.safe_int(row.get("remaining")), total_steps(state, settings))

    if resist:
        chance = _num(state, settings, "resist_chance", 0.0, 100.0)
        total = max(1, util.safe_int(row.get("birth_total"), total_steps(state, settings)))
        if random.random() * 100.0 < chance:
            add = max(0, int(_num(state, settings, "resist_add_steps", 0, 5)))
            remaining = util.safe_int(row.get("remaining"), total) + add
            row["remaining"] = remaining
            row["pos"] = pos_of(remaining, total)
            row["resist"] = util.safe_int(row.get("resist"), 0) + 1
            row["fail_streak"] = 0
            row["gave_up"] = False
            mood.adjust(state, settings, "desire",
                        delta=_num(state, settings, "resist_desire", 0.0, 100.0), now=now)
            line = prompts.text(state, "unbirth", "birth_resist",
                                resist=row["resist"], remaining=remaining,
                                pos=row["pos"], step=row["resist"])
        else:
            row["resist_fail"] = util.safe_int(row.get("resist_fail"), 0) + 1
            line = prompts.text(state, "unbirth", "birth_resist_fail",
                                remaining=total, pos=row.get("pos") or "子宫")
        row["step_line"] = line
        return {"ok": True, "step": row["birth_step"], "steps": total,
                "remaining": row["remaining"], "pos": row["pos"],
                "resist": True, "resist_success": line is not None,
                "hymen": hymen_info, "done": False, "line": line}

    difficulty = _num(state, settings, "birth_difficulty", 0.0, 100.0)
    success = util.clamp(100.0 - difficulty * (1.0 - ratio_now) * 1.6, 5.0, 100.0)
    if random.random() * 100 > success:
        return _birth_fail(
            state, settings, "试了几次都没出来",
            prompts.text(state, "unbirth", "birth_fail", chance=round(success, 1)))
    row["fail_streak"] = 0
    row["gave_up"] = False
    advanced = _advance(state, settings, now, auto=False)
    return {"ok": True, "step": row["birth_step"],
            "steps": total_steps(state, settings),
            "remaining": advanced["remaining"], "pos": advanced["pos"],
            "done": advanced["done"], "hymen": hymen_info,
            "line": advanced["line"]}


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    settle(state, settings, now=now)
    tick_birth(state, settings, now=now)
    row = data(state)
    body = user_body(state, settings)
    ratio_value = ratio(state)
    return {
        "enabled": enabled(settings, state),
        "ratio": ratio_value,
        "min_ratio": min_ratio(state, settings),
        "volume_ml": volume_ml(state, settings),
        "limit_ml": limit_ml(state, settings),
        "inside": bool(row.get("inside")),
        "location": str(row.get("location") or "uterus"),
        "can_birth": str(row.get("location") or "uterus") == "uterus",
        "expansion": str(row.get("expansion") or ""),
        "expansion_label": EXPANSION_LABELS.get(str(row.get("expansion") or ""), ""),
        "birth_step": util.safe_int(row.get("birth_step"), 0),
        "birth_steps": int(_num(state, settings, "birth_steps", 1, 20)),
        "total_steps": util.safe_int(row.get("birth_total"), 0) or total_steps(state, settings),
        "remaining": util.safe_int(row.get("remaining"), 0),
        "pos": str(row.get("pos") or ""),
        "birth_active": bool(row.get("birth_at")),
        "gave_up": bool(row.get("gave_up")),
        "fail_streak": util.safe_int(row.get("fail_streak"), 0),
        "step_minutes": int(_num(state, settings, "birth_step_minutes", 1, 240)),
        "request_enabled": request_enabled(state, settings),
        "resist": util.safe_int(row.get("resist"), 0),
        "height_cm": body["height_cm"], "weight_kg": body["weight_kg"],
        "shrink_ratio": _num(state, settings, "shrink_ratio", 0.01, 1.0),
        "max_ratio": max_ratio(state, settings),
        "can_grow": True,
        "resist_keywords": resist_keywords(state, settings),
        "can_enter": (not row.get("inside")
                      and volume_ml(state, settings) <= limit_ml(state, settings)
                      and not clothing.blocked(state, settings, "vagina")[0]),
    }


def block(state: dict, settings: Settings, now: float | None = None) -> str:
    if not enabled(settings, state):
        return ""
    settle(state, settings, now=now)
    row = data(state)
    if not row.get("inside"):
        return ""
    tick_birth(state, settings, now=now)
    line = _text(state, "inside",
                 size=round(util.safe_float(row.get("volume_ml"), 0.0), 1))
    extra = EXPANSION_LABELS.get(str(row.get("expansion") or ""), "")
    pos = str(row.get("pos") or "子宫")
    remaining = util.safe_int(row.get("remaining"), 0)
    body = f"【待在子宫里】\n- {line}" + (f"（{extra}）" if extra else "")
    body += f"\n- 现在在：{pos}；她想出来还要 {remaining} 步。"
    if row.get("step_line"):
        body += f"\n- {row['step_line']}"
    return body


def clear(state: dict) -> None:
    state["unbirth"] = dict(DEFAULT)
