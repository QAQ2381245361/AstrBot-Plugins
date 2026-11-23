"""尺寸：阴道长度（会小幅浮动）与生殖器长度/粗细。

- 基础值都在配置里（cm）：`size.vagina_length` / `size.penis_length` / `size.penis_girth`；
- 阴道长度会因为**高潮 / 快感高 / 忍耐高 / 胎儿**略微变长，每种情况有各自的涨幅和保持时间
  （`size.float_*` / `size.float_*_minutes`），过期自动消失；不在活动里、没有这些情况时就是基础值；
- 生殖器**明显短于**阴道长度（差超过 `size.reach_margin`）时碰不到子宫颈、也插不进子宫；
- 首次见到 / 明显变化时，按 `size.notice_chance` 的概率让她主动发一条（内容在 prompts 的 size 组）。
"""

from __future__ import annotations

import random

from . import pregnancy, prompts, tuning, util
from .settings import Settings

FLOAT_KINDS = ("orgasm", "pleasure", "endurance")


def _value(state: dict | None, settings: Settings, key: str, default: float) -> float:
    return tuning.get(state, "size", key, settings.float(f"size.{key}", 0.0, 1000.0))


def penis_length(state: dict | None, settings: Settings) -> float:
    return max(1.0, round(_value(state, settings, "penis_length",
                                  settings.float("size.penis_length", 1.0, 100.0)), 1))


def penis_girth(state: dict | None, settings: Settings) -> float:
    return max(0.5, round(_value(state, settings, "penis_girth",
                                  settings.float("size.penis_girth", 0.5, 50.0)), 1))


def penis_head_length(state: dict | None, settings: Settings) -> float:
    """阴茎头长度（单独算，不算进总长）。"""
    return max(0.5, round(_value(state, settings, "penis_head_length",
                                 settings.float("size.penis_head_length", 0.5, 50.0)), 1))


def vagina_width(state: dict | None, settings: Settings) -> float:
    """阴道截面大小（cm，直径），和阴道长度分开。"""
    return max(0.2, round(_value(state, settings, "vagina_width",
                                 settings.float("size.vagina_width", 0.2, 50.0)), 2))


def hymen_hole(state: dict | None, settings: Settings) -> float:
    """处女膜孔洞大小（cm），永远小于阴道截面。"""
    hole = _value(state, settings, "hymen_hole",
                  settings.float("size.hymen_hole", 0.1, 100.0))
    width = vagina_width(state, settings)
    return round(max(0.1, min(hole, max(0.15, width - 0.1))), 2)


def hymen_depth(state: dict | None, settings: Settings) -> float:
    """处女膜大致深度（cm）：插入超过这里才算顶破。"""
    return max(0.5, round(_value(state, settings, "hymen_depth",
                                  settings.float("size.hymen_depth", 0.5, 30.0)), 2))


def uterus_base(state: dict | None, settings: Settings) -> float:
    """子宫基础长度（面板里可改的那个值）。"""
    return max(1.0, round(_value(state, settings, "uterus_length",
                                 settings.float("size.uterus_length", 1.0, 100.0)), 1))


def uterus_length(state: dict | None, settings: Settings) -> float:
    """子宫实际长度：基础值 + 胎儿撑长（有上限）。"""
    base = uterus_base(state, settings)
    if not state:
        return base
    return max(1.0, round(base + fetus_float(state, settings), 1))


def vagina_base(state: dict | None, settings: Settings) -> float:
    return max(1.0, round(_value(state, settings, "vagina_length",
                                  settings.float("size.vagina_length", 1.0, 100.0)), 1))


def _floats(state: dict) -> dict:
    value = state.get("size_floats")
    if not isinstance(value, dict):
        value = {}
        state["size_floats"] = value
    return value


def float_active(state: dict, settings: Settings, kind: str,
                 now: float | None = None) -> bool:
    now = now or util.now_ts()
    row = _floats(state).get(kind)
    if not isinstance(row, dict):
        return False
    until = util.safe_float(row.get("until"), 0.0)
    if until <= now:
        _floats(state).pop(kind, None)
        return False
    return True


def note(state: dict, settings: Settings, kind: str, now: float | None = None) -> dict:
    """记一次会让阴道变长的情况（高潮/快感高/忍耐高）；已经在浮动里就续一下。"""
    now = now or util.now_ts()
    if kind not in FLOAT_KINDS:
        return {}
    amount = settings.float(f"size.float_{kind}", 0.0, 10.0)
    minutes = settings.int(f"size.float_{kind}_minutes", 0, 720)
    if amount <= 0 or minutes <= 0:
        return {}
    row = _floats(state).setdefault(kind, {})
    row["amount"] = amount
    row["until"] = now + minutes * 60
    row["at"] = now
    return {"kind": kind, "amount": amount, "minutes": minutes}


def fetus_float(state: dict, settings: Settings) -> float:
    """怀孕时胎儿把里面撑长一点（每胎 / 按月）。"""
    progress = pregnancy.progress(state)
    if not progress:
        return 0.0
    try:
        fetuses = max(1, int(progress.get("fetuses") or 1))
    except (TypeError, ValueError):
        fetuses = 1
    amount = settings.float("size.float_fetus", 0.0, 10.0)
    month = max(1, min(10, int(progress.get("month") or 1)))
    raw = amount * fetuses * (0.5 + month / 10.0)
    ratio = max(1.0, settings.float("size.fetus_uterus_max_ratio", 1.0, 5.0))
    base = uterus_base(state, settings)
    max_extra = max(0.0, base * (ratio - 1.0))
    return round(min(raw, max_extra), 2)


def vagina_length(state: dict, settings: Settings, *,
                  now: float | None = None) -> dict:
    now = now or util.now_ts()
    base = vagina_base(state, settings)
    active = {}
    total = base
    for kind in FLOAT_KINDS:
        row = _floats(state).get(kind)
        if not isinstance(row, dict):
            continue
        until = util.safe_float(row.get("until"), 0.0)
        if until <= now:
            _floats(state).pop(kind, None)
            continue
        amount = util.safe_float(row.get("amount"), 0.0)
        active[kind] = {"amount": round(amount, 2),
                        "left_minutes": max(0, int((until - now) // 60))}
        total += amount
    stretch = state.get("cervix_stretch")
    if isinstance(stretch, dict):
        until = util.safe_float(stretch.get("until"), 0.0)
        amount = max(0.0, util.safe_float(stretch.get("amount"), 0.0))
        entered = bool(stretch.get("entered"))
        try:
            from . import uterus_insert
            entered = entered or uterus_insert.active(state)
        except Exception:
            pass
        if until > now and amount:
            active["cervix_stretch"] = {
                "amount": round(0.0 if entered else amount, 2),
                "entered": entered,
                "left_minutes": max(0, int((until - now) // 60))}
            if not entered:
                total += amount
        elif until <= now:
            state.pop("cervix_stretch", None)
    fetus = fetus_float(state, settings)
    if fetus:
        active["fetus"] = {"amount": fetus, "left_minutes": 0}
        total += fetus
    shorten = 0.0
    threshold = settings.float("pleasure.orgasm_threshold", 0.0, 100.0)
    ratio = settings.float("size.pre_orgasm_ratio", 0.0, 1.0)
    after_orgasm = isinstance(_floats(state).get("orgasm"), dict)
    if not after_orgasm and threshold > 0 and util.safe_float(
            state.get("pleasure"), 0.0) >= threshold * ratio:
        shorten = max(0.0, settings.float("size.pre_orgasm_shorten", 0.0, 20.0))
        if shorten:
            active["pre_orgasm"] = {"amount": -round(shorten, 2), "left_minutes": 0}
            total -= shorten
    return {"base": base, "effective": round(max(1.0, total), 2), "floats": active,
            "delta": round(total - base, 2)}


def reach_margin(settings: Settings) -> float:
    return max(0.0, settings.float("size.reach_margin", 0.0, 20.0))


def reachable(state: dict, settings: Settings, now: float | None = None) -> dict:
    length = vagina_length(state, settings, now=now)["effective"]
    penis = penis_length(state, settings)
    short_by = round(length - penis, 2)
    reach = penis + reach_margin(settings) >= length
    return {"reachable": reach, "penis": penis, "vagina": length,
            "short_by": short_by if short_by > 0 else 0.0,
            "margin": reach_margin(settings)}


def can_reach(state: dict, settings: Settings, zone: str,
              now: float | None = None) -> tuple[bool, str]:
    """子宫颈 / 子宫：太短就碰不到（其它部位不受影响）。"""
    if zone not in ("cervix", "uterus"):
        return True, ""
    info = reachable(state, settings, now=now)
    if info["reachable"]:
        return True, ""
    max_stretch = max(0.0, settings.float("size.cervix_stretch_max", 0.0, 20.0))
    short = max(0.0, util.safe_float(info.get("short_by"), 0.0))
    if 0 < short <= max_stretch:
        now = now or util.now_ts()
        minutes = max(1, settings.int("size.cervix_stretch_minutes", 1, 240))
        amount = min(max_stretch, short)
        ratio = settings.float("size.cervix_stretch_ratio", 0.0, 1.0)
        state["cervix_stretch"] = {
            "amount": amount,
            "until": now + minutes * 60,
            "ratio": ratio,
            "entered": amount >= max_stretch * ratio if max_stretch > 0 else False,
        }
        return True, ""
    return False, (f"他不够长，碰不到{('子宫颈' if zone == 'cervix' else '子宫')}"
                   f"（差 {short:.1f} cm，可以调尺寸或换方式）")


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    vagina = vagina_length(state, settings, now=now)
    info = reachable(state, settings, now=now)
    return {
        "penis_length": penis_length(state, settings),
        "penis_girth": penis_girth(state, settings),
        "penis_head_length": penis_head_length(state, settings),
        "uterus_length": uterus_length(state, settings),
        "uterus_length_base": uterus_base(state, settings),
        "uterus_length_effective": uterus_length(state, settings),
        "vagina_width": vagina_width(state, settings),
        "hymen_hole": hymen_hole(state, settings),
        "vagina": vagina,
        "reachable": info["reachable"],
        "short_by": info["short_by"],
        "margin": info["margin"],
        "notice_chance": settings.float("size.notice_chance", 0.0, 100.0),
    }


def _seen(state: dict) -> dict:
    value = state.get("size_seen")
    if not isinstance(value, dict):
        value = {}
        state["size_seen"] = value
    return value


def notice_check(state: dict, settings: Settings, *,
                 now: float | None = None) -> dict | None:
    """首次见到 / 明显变化：按概率决定要不要让她主动发一条。

    返回 {"first": bool, "changed": bool, "line": 提示词} 或 None（不触发）。
    """
    now = now or util.now_ts()
    seen = _seen(state)
    length = penis_length(state, settings)
    girth = penis_girth(state, settings)
    delta_at = max(0.1, settings.float("size.notice_delta", 0.1, 20.0))
    first = not seen
    changed = (not first) and (abs(length - util.safe_float(seen.get("length"), length)) >= delta_at
                               or abs(girth - util.safe_float(seen.get("girth"), girth)) >= delta_at)
    if not first and not changed:
        return None
    chance = settings.float("size.notice_chance", 0.0, 100.0)
    # 第一次见到必然触发；之后的变化才按概率
    hit = first or random.random() * 100.0 < chance
    seen.update({"length": length, "girth": girth, "seen_at": now})
    if not hit:
        return None
    key = "first_see" if first else "changed"
    line = prompts.text(state, "size", key, length=length, girth=girth)
    return {"first": first, "changed": changed, "line": line}
