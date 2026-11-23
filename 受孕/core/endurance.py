"""高潮忍耐条：快感涨的时候同时在攒"还能忍多久"，攒满了再刺激就高潮。

- 快感低于 `gain_at` 时每次只加一点点（`gain_low`），到了/超过就加正常的量（`gain_high`）；
- 条的长度 `cap`：每连续高潮一次就变长一点（`combo_grow`，最多到 `combo_cap` 倍），
  `reset_minutes` 分钟没再高潮就缩回基础长度（`cap`）；
- 满了以后**再一次**刺激才高潮（"满了再加就高潮"），高潮后清空、长度变长。
"""

from __future__ import annotations

from . import intimacy, util
from .settings import Settings

DEFAULT = {"value": 0.0, "at": 0.0, "combo": 0, "cap": 0.0, "last_orgasm_at": 0.0}


def data(state: dict) -> dict:
    value = state.get("endurance")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["endurance"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def enabled(settings: Settings) -> bool:
    return bool(settings.bool("endurance.enabled"))


def base_cap(settings: Settings) -> float:
    return max(1.0, settings.float("endurance.cap", 1.0, 10000.0))


def combo_limit(settings: Settings) -> float:
    return max(1.0, settings.float("endurance.combo_cap", 1.0, 20.0))


def reset_minutes(settings: Settings) -> int:
    return max(0, settings.int("endurance.reset_minutes", 0, 1440))


def idle_minutes(settings: Settings) -> int:
    return max(0, settings.int("endurance.idle_minutes", 0, 1440))


def level_at(settings: Settings, index: int) -> float:
    """第 index 段的起点（占总条长的百分比）。"""
    return util.clamp(settings.float(f"endurance.level_at_{index}", 0.0, 100.0), 0.0, 100.0)


LEVEL_NAMES = ("还在忍", "有点忍不住", "快撑不住了", "到顶了")

# 4 段默认提示词（可自定义）
LEVEL_PROMPTS = (
    "还能稳着，只是呼吸比刚才重一点",
    "开始有点忍不住了：指尖会抓住东西，声音也压不住",
    "快撑不住了：腰会自己动，眼泪都要被逼出来，嘴里只剩碎掉的求饶",
    "到顶了：再碰一下整个人就绷住，连呼吸都是断的",
)


def level_of(value: float, cap: float, settings: Settings) -> int:
    if value <= 0 or cap <= 0:
        return 0
    percent = value / cap * 100.0
    level = 1
    for index in (1, 2, 3):
        if percent >= level_at(settings, index):
            level = index + 1
    return max(1, min(4, level))


def level_title(level: int) -> str:
    index = int(level) - 1
    if 0 <= index < len(LEVEL_NAMES):
        return f"第{int(level)}段·{LEVEL_NAMES[index]}"
    return ""


def _prompt_box(state: dict) -> dict:
    box = state.get("endurance_prompts")
    if not isinstance(box, dict):
        box = {}
        state["endurance_prompts"] = box
    return box


def prompt_override(state: dict | None, level: int) -> str:
    if not isinstance(state, dict) or int(level) <= 0:
        return ""
    row = _prompt_box(state).get("stages")
    if not isinstance(row, (list, tuple)):
        return ""
    index = int(level) - 1
    text = str(row[index] or "").strip() if 0 <= index < len(row) else ""
    if not text or text == LEVEL_PROMPTS[index]:
        return ""
    return text


def prompt_of(state: dict | None, level: int) -> str:
    index = int(level) - 1
    default = LEVEL_PROMPTS[index] if 0 <= index < len(LEVEL_PROMPTS) else ""
    return prompt_override(state, level) or default


def set_prompt(state: dict, level: int, text: str) -> str:
    level = max(1, min(4, int(level)))
    box = _prompt_box(state)
    row = list(box.get("stages") or [])
    while len(row) < 4:
        row.append("")
    value = str(text or "").strip()[:400]
    row[level - 1] = "" if value == LEVEL_PROMPTS[level - 1] else value
    if any(row):
        box["stages"] = row
    else:
        box.pop("stages", None)
    return prompt_of(state, level)


def set_prompts(state: dict, texts) -> list[str]:
    values = list(texts or [])[:4]
    while len(values) < 4:
        values.append("")
    for index, text in enumerate(values, start=1):
        set_prompt(state, index, text)
    return [prompt_of(state, level) for level in (1, 2, 3, 4)]


def reset_prompts(state: dict, level: int | None = None) -> int:
    box = _prompt_box(state)
    if "stages" not in box:
        return 0
    if level is not None:
        index = max(1, min(4, int(level))) - 1
        row = list(box.get("stages") or [])
        changed = 1 if index < len(row) and row[index] else 0
        row[index] = ""
        if any(row):
            box["stages"] = row
        else:
            box.pop("stages", None)
        return changed
    box.pop("stages", None)
    return 1


def prompts_payload(state: dict) -> list[dict]:
    stages = []
    for level in (1, 2, 3, 4):
        default = LEVEL_PROMPTS[level - 1]
        override = prompt_override(state, level)
        stages.append({
            "level": level,
            "title": level_title(level),
            "name": LEVEL_NAMES[level - 1],
            "default": default,
            "value": override or default,
            "custom": bool(override),
        })
    return [{"key": "levels", "label": "高潮忍耐条分段", "stages": stages,
             "custom_count": sum(1 for row in stages if row["custom"])}]


def _decay(state: dict, settings: Settings, now: float) -> dict:
    """一直没人碰：先等 idle_minutes，过了这段才开始按小时往回掉。"""
    row = data(state)
    if not enabled(settings):
        return row
    last = util.safe_float(row.get("at"), 0.0) or now
    idle = idle_minutes(settings) * 60
    hours = max(0.0, (now - last - idle) / 3600.0)
    if hours > 0:
        per_hour = settings.float("endurance.decay_per_hour", 0.0, 1000.0)
        value = util.safe_float(row.get("value"), 0.0) - per_hour * hours
        row["value"] = round(max(0.0, value), 2)
        row["at"] = now
    return row


def cap_for(settings: Settings, combo: int) -> float:
    """按连续次数算条长（配置改了立刻生效，不用重置）。"""
    base = base_cap(settings)
    grow = settings.float("endurance.combo_grow", 0.0, 5.0)
    cap = min(base * combo_limit(settings), base * (1.0 + grow * max(0, int(combo))))
    return round(max(1.0, cap), 2)


def _settle(state: dict, settings: Settings, now: float) -> dict:
    """没再被碰就先等一阵、再慢慢回落；连续高潮的长条也会随时间缩回去。"""
    row = data(state)
    if not enabled(settings):
        return row
    row = _decay(state, settings, now)
    last = util.safe_float(row.get("last_orgasm_at"), 0.0)
    limit = reset_minutes(settings)
    if last and limit and now - last >= limit * 60:
        row["combo"] = 0
        row["value"] = 0.0
    return row


def cap_of(state: dict, settings: Settings, now: float | None = None) -> float:
    if not enabled(settings):
        return base_cap(settings)
    row = _settle(state, settings, now or util.now_ts())
    return cap_for(settings, util.safe_int(row.get("combo"), 0))


def value_of(state: dict, settings: Settings, now: float | None = None) -> float:
    if not enabled(settings):
        return 0.0
    row = _settle(state, settings, now or util.now_ts())
    return util.clamp(util.safe_float(row.get("value"), 0.0), 0.0, cap_of(state, settings, now))


def is_full(state: dict, settings: Settings, now: float | None = None) -> bool:
    if not enabled(settings):
        return False
    return value_of(state, settings, now) >= cap_of(state, settings, now) - 1e-6


def gain_amount(state: dict, settings: Settings, pleasure: float) -> float:
    """按加完之后的快感决定这次攒多少忍耐。"""
    at = settings.float("endurance.gain_at", 0.0, 1000.0)
    low = settings.float("endurance.gain_low", 0.0, 1000.0)
    high = settings.float("endurance.gain_high", 0.0, 1000.0)
    return high if pleasure >= at else low


def gain(state: dict, settings: Settings, *, pleasure: float, mult: float = 1.0,
         extra: float = 0.0, now: float | None = None) -> dict:
    """记一次快感上涨带来的忍耐变化。"""
    now = now or util.now_ts()
    if not enabled(settings):
        return {"enabled": False}
    row = _settle(state, settings, now)
    cap = cap_of(state, settings, now)
    before = util.safe_float(row.get("value"), 0.0)
    amount = gain_amount(state, settings, pleasure) * max(0.0, mult) + max(0.0, extra)
    if amount > 0:
        amount *= max(0.0, settings.float("endurance.gain_multiplier", 0.0, 10.0))
    after = util.clamp(before + amount, 0.0, cap)
    row["value"] = round(after, 2)
    row["at"] = now
    return {"enabled": True, "before": round(before, 2), "after": round(after, 2),
            "amount": round(after - before, 2), "cap": cap,
            "full": after >= cap - 1e-6, "was_full": before >= cap - 1e-6}


def add_extra(state: dict, settings: Settings, amount: float,
              now: float | None = None) -> float:
    """单独加一点忍耐（特别敏感点之类）。"""
    if not enabled(settings) or amount <= 0:
        return 0.0
    now = now or util.now_ts()
    row = _settle(state, settings, now)
    zone = str((state.get("last_touch") or {}).get("zone") or "")
    if zone:
        sens = intimacy.zone_sensitivity_effective(state, settings, zone)
        amount = amount * (1.0 + settings.float("endurance.sens_boost", 0.0, 5.0)
                           * max(0.0, sens - 1.0))
    amount *= max(0.0, settings.float("endurance.gain_multiplier", 0.0, 10.0))
    cap = cap_of(state, settings, now)
    row["value"] = round(util.clamp(util.safe_float(row.get("value"), 0.0) + amount,
                                    0.0, cap), 2)
    row["at"] = now
    return row["value"]


def consume(state: dict, settings: Settings, now: float | None = None) -> dict:
    """高潮之后：清空，并把下一次的条变长一点。"""
    now = now or util.now_ts()
    row = data(state)
    base = base_cap(settings)
    combo = util.safe_int(row.get("combo"), 0) + 1
    cap = cap_for(settings, combo)
    row.update({"value": 0.0, "at": now, "combo": combo, "last_orgasm_at": now})
    return {"combo": combo, "cap": cap, "grow": round(cap - base, 2)}


def prompt_block(state: dict, settings: Settings, *, in_event: bool,
                 now: float | None = None) -> str:
    """活动/日常小场景里把忍耐条当前那一段写成一句提示。"""
    if not in_event or not enabled(settings):
        return ""
    now = now or util.now_ts()
    payload_data = payload(state, settings, now)
    level = payload_data.get("level") or 0
    if level <= 0:
        return ""
    return ("【高潮忍耐】\n"
            f"- {payload_data['level_title']}（{payload_data['value']:.0f}/{payload_data['cap']:.0f}）："
            f"{payload_data['prompt']}。\n"
            "（这是她还能忍多久：别报数值；满了以后再被刺激一下就会到，"
            "要说清她在硬撑。）")


def clear(state: dict, settings: Settings, now: float | None = None) -> None:
    """重置（面板「重置」之类）。"""
    now = now or util.now_ts()
    state["endurance"] = {"value": 0.0, "at": now, "combo": 0, "last_orgasm_at": 0.0}


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = _settle(state, settings, now)
    cap = cap_of(state, settings, now)
    value = value_of(state, settings, now)
    return {
        "enabled": enabled(settings),
        "value": round(value, 1),
        "cap": round(cap, 1),
        "percent": round(min(100.0, value / cap * 100.0), 1) if cap > 0 else 0.0,
        "full": value >= cap - 1e-6,
        "combo": util.safe_int(row.get("combo"), 0),
        "base_cap": base_cap(settings),
        "grow_percent": round(max(0.0, cap - base_cap(settings)), 1),
        "gain_at": settings.float("endurance.gain_at", 0.0, 1000.0),
        "gain_low": settings.float("endurance.gain_low", 0.0, 1000.0),
        "gain_high": settings.float("endurance.gain_high", 0.0, 1000.0),
        "reset_minutes": reset_minutes(settings),
        "idle_minutes": idle_minutes(settings),
        "decay_per_hour": settings.float("endurance.decay_per_hour", 0.0, 1000.0),
        "level": level_of(value, cap, settings),
        "level_title": level_title(level_of(value, cap, settings)),
        "level_at": [round(level_at(settings, index), 1) for index in (1, 2, 3)],
        "prompt": prompt_of(state, level_of(value, cap, settings)),
        "prompts": prompts_payload(state),
    }
