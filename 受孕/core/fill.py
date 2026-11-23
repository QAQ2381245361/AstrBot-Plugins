"""子宫里的量：充盈分段提示词、短暂撑开、满了溢出来、活动结束后漏出去。

- 容量 = `ejaculation.uterus_capacity_ml`（面板「数值细调」里也能改）；
- 短暂撑开：填到 `stretch_at` 以后每次内射会把子宫撑开一点（最多 `stretch_ratio`）；
  量降回基础容量以内就自己缩回去（不再靠"撑开保持多少分钟"）；
- 溢出：撑开到顶、并且已经到 `overflow_at` 比例以后，再射就装不下，
  多出来的顺着阴道往外溢（`overflow_enabled` 关掉就不溢，改成能一直装）；
- 结束后漏出：不在活动里时，子宫里的东西按 `after_leak_per_hour` 往外漏，
  漏到 `after_leak_until`（占容量 %）以下就停，剩下的交给原来的按小时吸收；
  开关是 `after_leak_enabled`（面板也能临时覆盖）；
- 充盈 4 段、溢出 3 段都有提示词，可在面板「子宫设置」页里改。
"""

from __future__ import annotations

import random

from . import intimacy, mood, prompts, tuning, util
from .settings import Settings

FILL_MAX = 4
OVERFLOW_MAX = 3
PROMPT_MAX = 400

# 充盈 4 段（按占"当前容量"的比例分）
FILL_LEVELS = (
    (0.00, "trace", "一点"),
    (0.35, "half", "半满"),
    (0.65, "near", "将溢"),
    (0.90, "full", "满溢"),
)

FILL_DEFAULTS = (
    "里面只有浅浅一层，还没什么特别的感觉",
    "小腹里温温的，动一下能感觉到一点晃",
    "已经沉甸甸的，走两步就觉得小腹发坠",
    "满得发胀，稍微一碰都像会被压出来",
)

# 溢出 3 段（按这次溢出来的量占容量比例分）
OVERFLOW_LEVELS = (
    (0.00, "little", "少量"),
    (0.12, "some", "明显"),
    (0.35, "much", "大量"),
)

OVERFLOW_DEFAULTS = (
    "有一点顺着缝隙往外渗，她自己先感觉到了",
    "明显往外淌，腿根一热，得赶紧夹住",
    "堵不住了，一股股顺着往下流，把下面都弄湿了",
)


# ---------------------------------------------------------------- 数值

def _tune(state: dict | None, settings: Settings, key: str, *,
          fallback: tuple, as_int: bool = False):
    if as_int:
        return int(round(tuning.get(state, "uterus", key,
                                    settings.int(f"ejaculation.uterus_{key}", 0, 100000))))
    return tuning.get(state, "uterus", key,
                      settings.float(f"ejaculation.uterus_{key}", 0.0, 100000.0))


def capacity_base(state: dict | None, settings: Settings) -> float:
    return max(1.0, round(_tune(state, settings, "capacity_ml",
                                fallback=(1.0, 500.0)), 1))


def stretch_ratio_max(state: dict | None, settings: Settings) -> float:
    return max(0.0, min(2.0, _tune(state, settings, "stretch_ratio",
                                   fallback=(0.0, 2.0))))


def stretch_at(state: dict | None, settings: Settings) -> float:
    return util.clamp(tuning.get(state, "uterus", "stretch_at",
                                 settings.float("ejaculation.uterus_stretch_at", 0.0, 1.0)),
                      0.0, 1.0)



def overflow_enabled(state: dict | None, settings: Settings) -> bool:
    override = (state or {}).get("uterus_overflow_enabled")
    if isinstance(override, bool):
        return override
    return bool(settings.bool("ejaculation.uterus_overflow_enabled"))


def overflow_at(state: dict | None, settings: Settings) -> float:
    return util.clamp(tuning.get(state, "uterus", "overflow_at",
                                 settings.float("ejaculation.uterus_overflow_at", 0.0, 1.0)),
                      0.0, 1.0)


def overflow_minutes(state: dict | None, settings: Settings) -> int:
    return int(max(0, tuning.get(state, "uterus", "overflow_minutes",
                                 settings.int("ejaculation.uterus_overflow_minutes", 0, 1440))))


def _stretch(state: dict, settings: Settings, ml: float, base_capacity: float) -> float:
    """当前撑开了多少（0–stretch_ratio_max）：量掉回"开始撑"的那条线以下就自己缩回去。"""
    value = max(0.0, util.safe_float(state.get("uterus_stretch"), 0.0))
    if value <= 0:
        return 0.0
    floor = base_capacity * stretch_at(state, settings)
    if ml < floor - 0.01:
        state["uterus_stretch"] = 0.0
        return 0.0
    return min(value, stretch_ratio_max(state, settings))


def after_leak_enabled(state: dict | None, settings: Settings) -> bool:
    """活动结束后允不允许渐渐漏出去（可以用面板开关覆盖）。"""
    override = (state or {}).get("uterus_after_leak_enabled")
    if isinstance(override, bool):
        return override
    return bool(settings.bool("ejaculation.uterus_after_leak_enabled"))


def after_leak_per_hour(state: dict | None, settings: Settings) -> float:
    return max(0.0, tuning.get(state, "uterus", "after_leak_per_hour",
                               settings.float("ejaculation.uterus_after_leak_per_hour",
                                              0.0, 100.0)))


def after_leak_until(state: dict | None, settings: Settings) -> float:
    """漏到容量的百分之几就停。"""
    return util.clamp(tuning.get(state, "uterus", "after_leak_until",
                                 settings.float("ejaculation.uterus_after_leak_until",
                                                0.0, 100.0)), 0.0, 100.0)


def set_after_leak_enabled(state: dict, settings: Settings, value: bool | None) -> bool:
    """None = 跟随配置。"""
    if value is None:
        state.pop("uterus_after_leak_enabled", None)
    else:
        state["uterus_after_leak_enabled"] = bool(value)
    return after_leak_enabled(state, settings)


def fetus_ml(state: dict, settings: Settings) -> float:
    """胎儿占的容量：按孕月长，满月 = 每胎 volume_ml；不受容量上限限制。"""
    try:
        from . import pregnancy
        progress = pregnancy.progress(state)
    except Exception:
        return 0.0
    if not progress:
        return 0.0
    try:
        fetuses = max(1, int(progress.get("fetuses") or 1))
    except (TypeError, ValueError):
        fetuses = 1
    month = max(1, min(10, int(progress.get("month") or 1)))
    per = settings.float("fetus.volume_ml", 0.0, 500.0)
    return round(per * fetuses * month / 10.0, 2)


def unbirth_ml(state: dict, settings: Settings) -> float:
    """缩小后待在子宫里的人占的容量（和胎儿一样占地方）。"""
    try:
        from . import unbirth
        if unbirth.inside(state):
            return unbirth.volume_ml(state, settings)
    except Exception:
        pass
    return 0.0


def room_ml(state: dict, settings: Settings, capacity: float, ml: float,
            fetus: float) -> float:
    """还能再装多少（胎儿占满时只剩一点点）。"""
    if fetus <= 0:
        return max(0.0, capacity - ml)
    full_at = capacity * settings.float("fetus.full_ratio", 0.1, 1.0)
    if fetus >= full_at:
        room = settings.float("fetus.extra_room_ml", 0.0, 100.0)
        return max(0.0, room - ml)
    return max(0.0, capacity - fetus - ml)


def _leak_shame(state: dict, settings: Settings, amount: float, now: float) -> None:
    gain = settings.float("leak.shame_gain", 0.0, 100.0)
    if gain <= 0 or amount <= 0:
        return
    cap = settings.float("leak.shame_cap", 0.0, 100.0)
    total = util.safe_float(state.get("leak_shame_total"), 0.0)
    if total >= cap:
        state["leak_at"] = now
        return
    add = min(gain, cap - total)
    mood.adjust(state, settings, "shame", delta=add, now=now)
    state["leak_shame_total"] = round(total + add, 1)
    state["leak_at"] = now


def leak_block(state: dict, settings: Settings, now: float | None = None) -> str:
    now = now or util.now_ts()
    at = util.safe_float(state.get("leak_at"), 0.0)
    minutes = max(1, settings.int("leak.minutes", 1, 240))
    if not at or now - at > minutes * 60:
        return ""
    line = prompts.text(state, "leak", "leak")
    return f"【子宫漏出】\n- {line}" if line else ""


def volume(state: dict, settings: Settings, now: float | None = None) -> dict:
    """当前子宫：量 / 基础容量 / 撑开后容量 / 占比 / 充盈段位 / 撑开情况。"""
    now = now or util.now_ts()
    base = intimacy.uterus_volume(state, settings, now=now)  # 顺手按小时吸收/漏出
    ml = base["ml"]
    try:
        from . import menstrual
        blood = menstrual.blood_ml(state, settings, now=now)
    except Exception:
        blood = 0.0
    semen_ml = ml
    ml = ml + blood
    leaked = max(0.0, util.safe_float(base.get("leaked"), 0.0))
    if leaked > 0:
        _leak_shame(state, settings, leaked, now)
    fetus = fetus_ml(state, settings) + unbirth_ml(state, settings)
    base_capacity = base["capacity"]
    stretch = _stretch(state, settings, ml, base_capacity)
    capacity = round(base_capacity * (1.0 + stretch), 2)
    ratio = 0.0 if capacity <= 0 else ml / capacity
    level = 0
    for index, (threshold, key, label) in enumerate(FILL_LEVELS):
        if ratio > 0 and ratio >= threshold:
            level = index + 1
    name = FILL_LEVELS[level - 1][2] if level else ""
    recent = util.safe_float(state.get("uterus_overflow_at"), 0.0)
    return {
        "ml": round(ml, 2),
        "semen_ml": round(semen_ml, 2),
        "blood_ml": round(blood, 2),
        "capacity": round(base_capacity, 2),
        "capacity_base": round(base_capacity, 2),
        "capacity_effective": capacity,
        "stretch": round(stretch, 3),
        "stretch_percent": round(stretch * 100, 0),

        "percent": round(min(200.0, ratio * 100), 1),
        "level": level,
        "level_name": name,
        "level_title": f"第{level}段·{name}" if level else "空",
        "tier": base["tier"],
        "tier_label": base["tier_label"],
        "overflow_enabled": overflow_enabled(state, settings),
        "overflow_at": round(overflow_at(state, settings) * 100, 1),
        "overflow_minutes": overflow_minutes(state, settings),
        "overflow_total": round(util.safe_float(state.get("uterus_overflow_total"), 0.0), 2),
        "overflow_last": round(util.safe_float(state.get("uterus_overflow_ml"), 0.0), 2),
        "overflow_last_at": recent,
        "overflow_recent": bool(recent and now - recent <= overflow_minutes(state, settings) * 60),
        "after_leak_enabled": after_leak_enabled(state, settings),
        "after_leak_per_hour": round(after_leak_per_hour(state, settings), 1),
        "after_leak_until": round(after_leak_until(state, settings), 0),
        "fetus_ml": fetus,
        "total_ml": round(ml + fetus, 2),
        "room_ml": round(room_ml(state, settings, capacity, ml, fetus), 2),
    }


def add(state: dict, settings: Settings, ml: float | None = None,
        now: float | None = None) -> dict:
    """内射一次：先撑开、再灌、灌不下就溢出来。"""
    now = now or util.now_ts()
    info = volume(state, settings, now=now)
    amount = intimacy.mode_volume(settings) if ml is None else max(0.0, util.safe_float(ml, 0.0))
    amount *= random.uniform(0.65, 1.35)
    base_capacity = info["capacity_base"]
    stretch_max = stretch_ratio_max(state, settings)

    # 1) 撑开：本来就已经装到 stretch_at 以上，这次内射会把她撑开一点
    before_ratio = info["ml"] / base_capacity if base_capacity > 0 else 0.0
    stretched = info["stretch"]
    if stretch_max > 0 and before_ratio >= stretch_at(state, settings):
        step = stretch_max / 3.0
        stretched = min(stretch_max, max(stretched, 0.0) + step)
        state["uterus_stretch"] = round(stretched, 3)
    capacity = base_capacity * (1.0 + stretched)

    # 2) 灌：超过 overflow_at 的部分往外溢（关掉溢出就只是一直装）
    raw = info.get("semen_ml", info["ml"]) + amount
    overflow = 0.0
    if overflow_enabled(state, settings):
        fetus = fetus_ml(state, settings) + unbirth_ml(state, settings)
        limit = capacity * overflow_at(state, settings)
        full_at = capacity * settings.float("fetus.full_ratio", 0.1, 1.0)
        if fetus > 0 and fetus >= full_at:
            limit = min(limit, settings.float("fetus.extra_room_ml", 0.0, 100.0))
        else:
            limit = max(0.0, limit - fetus)
        spill_above = min(capacity, limit)
        overflow = max(0.0, raw - spill_above)
    kept = raw - overflow
    state["uterus_ml"] = round(max(0.0, kept), 2)
    state["uterus_updated_at"] = now
    if overflow > 0:
        _leak_shame(state, settings, overflow, now)
        state["uterus_overflow_at"] = now
        state["uterus_overflow_ml"] = round(overflow, 2)
        state["uterus_overflow_total"] = round(
            util.safe_float(state.get("uterus_overflow_total"), 0.0) + overflow, 2)
    after = volume(state, settings, now=now)
    after.update({
        "added": round(amount, 2),
        "overflow": round(overflow, 2),
        "overflow_level": overflow_level(state, settings, overflow, now=now),
        "stretched_from": round(info["stretch"] * 100, 0),
        "stretched_to": round(stretched * 100, 0),
        "capacity_used": round(capacity, 2),
    })
    return after


def overflow_level(state: dict, settings: Settings, overflow: float,
                   now: float | None = None) -> int:
    capacity = max(1.0, volume(state, settings, now=now)["capacity_effective"])
    ratio = overflow / capacity
    level = 0
    for index, (threshold, key, label) in enumerate(OVERFLOW_LEVELS):
        if ratio >= threshold:
            level = index + 1
    return level


def clear(state: dict) -> None:
    intimacy.clear_uterus(state)
    for key in ("uterus_stretch", "uterus_overflow_at", "uterus_overflow_ml"):
        state[key] = 0.0
    state["uterus_overflow_total"] = 0.0


def set_overflow_enabled(state: dict, settings: Settings, value: bool | None) -> bool:
    """None = 跟随配置。"""
    if value is None:
        state.pop("uterus_overflow_enabled", None)
    else:
        state["uterus_overflow_enabled"] = bool(value)
    return overflow_enabled(state, settings)


# ---------------------------------------------------------------- 提示词（可自定义）

def _box(state: dict) -> dict:
    box = state.get("fill_prompts")
    if not isinstance(box, dict):
        box = {}
        state["fill_prompts"] = box
    return box


def _default(kind: str, level: int) -> str:
    table = FILL_DEFAULTS if kind == "level" else OVERFLOW_DEFAULTS
    index = int(level) - 1
    return table[index] if 0 <= index < len(table) else ""


def _names(kind: str) -> tuple:
    return tuple(row[2] for row in (FILL_LEVELS if kind == "level" else OVERFLOW_LEVELS))


def _count(kind: str) -> int:
    return FILL_MAX if kind == "level" else OVERFLOW_MAX


def override(state: dict | None, kind: str, level: int) -> str:
    if not isinstance(state, dict) or int(level) <= 0:
        return ""
    row = _box(state).get(kind)
    if not isinstance(row, (list, tuple)):
        return ""
    index = int(level) - 1
    text = str(row[index] or "").strip() if 0 <= index < len(row) else ""
    if not text or text == _default(kind, level):
        return ""
    return text


def prompt_of(state: dict | None, kind: str, level: int) -> str:
    return override(state, kind, level) or _default(kind, level)


def set_prompt(state: dict, kind: str, level: int, text: str) -> str:
    level = max(1, min(_count(kind), int(level)))
    box = _box(state)
    row = list(box.get(kind) or [])
    while len(row) < _count(kind):
        row.append("")
    value = str(text or "").strip()[:PROMPT_MAX]
    row[level - 1] = "" if value == _default(kind, level) else value
    if any(row):
        box[kind] = row
    else:
        box.pop(kind, None)
    return prompt_of(state, kind, level)


def set_prompts(state: dict, kind: str, texts) -> list[str]:
    values = list(texts or [])[:_count(kind)]
    while len(values) < _count(kind):
        values.append("")
    for index, text in enumerate(values, start=1):
        set_prompt(state, kind, index, text)
    return [prompt_of(state, kind, level) for level in range(1, _count(kind) + 1)]


def reset_prompts(state: dict, kind: str | None = None, level: int | None = None) -> int:
    box = _box(state)
    if not kind:
        count = len(box)
        box.clear()
        return count
    if kind not in box:
        return 0
    if level is not None:
        row = list(box.get(kind) or [])
        index = max(1, min(_count(kind), int(level))) - 1
        changed = 1 if index < len(row) and row[index] else 0
        while len(row) < _count(kind):
            row.append("")
        row[index] = ""
        if any(row):
            box[kind] = row
        else:
            box.pop(kind, None)
        return changed
    box.pop(kind, None)
    return 1


def prompts_payload(state: dict) -> list[dict]:
    rows = []
    for kind, label in (("level", "子宫充盈"), ("overflow", "子宫溢出")):
        stages = []
        for level in range(1, _count(kind) + 1):
            default = _default(kind, level)
            override_text = override(state, kind, level)
            stages.append({
                "level": level,
                "title": f"第{level}段·{_names(kind)[level - 1]}",
                "name": _names(kind)[level - 1],
                "default": default,
                "value": override_text or default,
                "custom": bool(override_text),
            })
        rows.append({
            "key": kind,
            "label": label,
            "stages": stages,
            "custom_count": sum(1 for stage in stages if stage["custom"]),
        })
    return rows


def prompt_block(state: dict, settings: Settings, *, in_scene: bool,
                 now: float | None = None) -> str:
    """活动场景里把子宫的充盈/溢出写成提示（日常不带）。"""
    if not in_scene:
        return ""
    now = now or util.now_ts()
    info = volume(state, settings, now=now)
    lines = []
    if info["ml"] > 0.5 and info["level"]:
        head = f"- 子宫（{info['ml']:.1f} ml / {info['capacity_effective']:.0f} ml，{info['level_title']}）"
        if info["stretch"] > 0:
            head += f"｜已经撑开 +{info['stretch_percent']:.0f}%"
        lines.append(f"{head}：{prompt_of(state, 'level', info['level'])}。")
    if info["overflow_recent"] and info["overflow_last"] > 0:
        level = 0
        capacity = max(1.0, info["capacity_effective"])
        ratio = info["overflow_last"] / capacity
        for index, (threshold, key, label) in enumerate(OVERFLOW_LEVELS):
            if ratio >= threshold:
                level = index + 1
        if level:
            lines.append(f"- 刚才没装下、溢出来一些（约 {info['overflow_last']:.1f} ml，"
                         f"{_names('overflow')[level - 1]}）：{prompt_of(state, 'overflow', level)}。")
    if not lines:
        return ""
    body = "\n".join(lines)
    tail = "\n（这些是身体里的真实状态：按这个写她的感受，别报毫升数；"
    tail += "要清掉就用「排出」，别自己宣布已经干净了。）" if info["overflow_enabled"] else \
        "\n（这些是身体里的真实状态：按这个写她的感受，别报毫升数。）"
    return "【子宫】\n" + body + tail
