"""阴道湿润度：一直在变（不在活动里也算），分 4 段提示词，破处时会减轻疼痛。

- `base` 是基础湿润度：没人碰、时间久了会回落到这里，不会掉到 0；
- 被碰/快感涨/用玩具/高潮都会让它往上涨（数值都可调）；
- 一直没人碰，过了 `idle_minutes` 就开始按 `decay_per_hour` 落回基础值；
- 4 段（偏干 / 微湿 / 湿 / 很湿）的起点可调，提示词可自定义；
- 处女膜没破时：湿润度和快感都够了，破处的疼痛会按 `pain_relief` 降低（100 = 完全不疼）。
"""

from __future__ import annotations

from . import intimacy, prompts, tuning, util
from .settings import Settings

DEFAULT = {"value": 0.0, "at": 0.0}
PROMPT_MAX = 400

LEVELS = (
    (0.0, "dry", "偏干"),
    (0.25, "slight", "微湿"),
    (0.50, "wet", "湿"),
    (0.75, "soaked", "很湿"),
)

LEVEL_PROMPTS = (
    "那里还干着，动作会有点涩，得慢慢来",
    "已经有点潮了，碰上去会轻轻一颤",
    "明显湿了，指尖一碰就带出一点水声，腰会不自觉地跟",
    "湿得一塌糊涂，顺着腿根往下淌，稍微一动就有声音",
)


def data(state: dict) -> dict:
    value = state.get("wetness")
    if not isinstance(value, dict):
        value = {}
        state["wetness"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def enabled(settings: Settings) -> bool:
    return bool(settings.bool("wetness.enabled"))


def base(settings: Settings, state: dict | None = None) -> float:
    value = tuning.get(state, "wetness", "base", settings.float("wetness.base", 0.0, 100.0))
    return util.clamp(util.safe_float(value, 0.0), 0.0, 100.0)


def base_float_enabled(settings: Settings, state: dict | None = None) -> bool:
    if isinstance(state, dict):
        override = state.get("wetness_base_float_enabled")
        if isinstance(override, bool):
            return override
    return settings.bool("wetness.base_float_enabled")


def base_float(state: dict, settings: Settings, now: float | None = None) -> dict:
    """基础湿润度的浮动：鱼之心「欲」+ 快感 + 忍耐，按权重折算，封顶。"""
    info = {"enabled": base_float_enabled(settings, state), "amount": 0.0,
            "desire": 0.0, "pleasure": 0.0, "endurance": 0.0}
    if not info["enabled"]:
        return info
    snap = state.get("fish_snapshot") if isinstance(state.get("fish_snapshot"), dict) else {}
    desire = util.clamp(util.safe_float(snap.get("desire"), 0.0), 0.0, 100.0)
    pleasure = util.clamp(util.safe_float(state.get("pleasure"), 0.0), 0.0, 100.0)
    end_percent = 0.0
    try:
        from . import endurance
        end_percent = util.clamp(util.safe_float(
            endurance.payload(state, settings, now=now).get("percent"), 0.0), 0.0, 100.0)
    except Exception:
        end_percent = 0.0
    def _weight(key: str) -> float:
        return tuning.get(state, "wetness", key,
                          settings.float(f"wetness.{key}", 0.0, 100.0))

    amount = (desire / 100.0 * _weight("base_float_desire")
              + pleasure / 100.0 * _weight("base_float_pleasure")
              + end_percent / 100.0 * _weight("base_float_endurance"))
    amount = min(_weight("base_float_cap"), max(0.0, amount))
    info.update({"amount": round(amount, 2), "desire": round(desire, 1),
                 "pleasure": round(pleasure, 1), "endurance": round(end_percent, 1)})
    return info


def base_effective(state: dict, settings: Settings, now: float | None = None) -> float:
    return round(base(settings, state) + base_float(state, settings, now=now)["amount"], 2)


def level_at(settings: Settings, index: int, state: dict | None = None) -> float:
    value = tuning.get(state, "wetness", f"level_at_{index}",
                       settings.float(f"wetness.level_at_{index}", 0.0, 100.0))
    return util.clamp(util.safe_float(value, 0.0), 0.0, 100.0)


def idle_minutes(settings: Settings) -> int:
    return max(0, settings.int("wetness.idle_minutes", 0, 1440))


def decay_per_hour(settings: Settings) -> float:
    return max(0.0, settings.float("wetness.decay_per_hour", 0.0, 500.0))


def _settle(state: dict, settings: Settings, now: float) -> float:
    """没再被碰就先等一阵，再慢慢落回基础湿润度。"""
    if not enabled(settings):
        return 0.0
    row = data(state)
    floor = base_effective(state, settings, now=now)
    value = util.clamp(util.safe_float(row.get("value"), floor), 0.0, 100.0)
    value = max(floor, value)
    last = util.safe_float(row.get("at"), 0.0) or now
    idle = idle_minutes(settings) * 60
    hours = max(0.0, (now - last - idle) / 3600.0)
    if hours > 0:
        value = max(floor, value - decay_per_hour(settings) * hours)
        row["at"] = now
    row["value"] = round(value, 2)
    return row["value"]


def value_of(state: dict, settings: Settings, now: float | None = None) -> float:
    now = now or util.now_ts()
    return _settle(state, settings, now)


def gain(state: dict, settings: Settings, *, touch: float = 0.0, pleasure: float = 0.0,
         extra: float = 0.0, mult: float = 1.0, now: float | None = None) -> float:
    """一次刺激：碰几下 / 涨了多少快感 / 额外的量，都换成湿润度（mult 是鱼之心「欲」的加成）。"""
    if not enabled(settings):
        return 0.0
    now = now or util.now_ts()
    value = _settle(state, settings, now)
    amount = (max(0.0, touch) * settings.float("wetness.gain_per_touch", 0.0, 100.0)
              + max(0.0, pleasure) * settings.float("wetness.gain_per_pleasure", 0.0, 10.0)
              + max(0.0, extra)) * max(0.0, util.safe_float(mult, 1.0))
    if amount <= 0:
        return value
    row = data(state)
    row["value"] = round(util.clamp(value + amount, 0.0, 100.0), 2)
    row["at"] = now
    try:
        from . import menstrual
        menstrual.add_pad_fluid(state, settings, "爱液", amount * 0.05, now=now)
    except Exception:
        pass
    return row["value"]


def gain_orgasm(state: dict, settings: Settings, now: float | None = None) -> float:
    return gain(state, settings, extra=settings.float("wetness.orgasm_gain", 0.0, 100.0), now=now)


def level_of(value: float, settings: Settings, state: dict | None = None) -> int:
    if value <= 0:
        return 0
    level = 1
    for index in (1, 2, 3):
        if value >= level_at(settings, index, state):
            level = index + 1
    return max(1, min(4, level))


def level_title(level: int) -> str:
    index = int(level) - 1
    if 0 <= index < len(LEVELS):
        return f"第{int(level)}段·{LEVELS[index][2]}"
    return ""


# ---------------------------------------------------------------- 提示词（可自定义）

def _box(state: dict) -> dict:
    box = state.get("wetness_prompts")
    if not isinstance(box, dict):
        box = {}
        state["wetness_prompts"] = box
    return box


def prompt_override(state: dict | None, level: int) -> str:
    if not isinstance(state, dict) or int(level) <= 0:
        return ""
    row = _box(state).get("stages")
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
    box = _box(state)
    row = list(box.get("stages") or [])
    while len(row) < 4:
        row.append("")
    value = str(text or "").strip()[:PROMPT_MAX]
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
    box = _box(state)
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
            "name": LEVELS[level - 1][2],
            "default": default,
            "value": override or default,
            "custom": bool(override),
        })
    return [{"key": "levels", "label": "湿润度分段", "stages": stages,
             "max_len": PROMPT_MAX,
             "custom_count": sum(1 for row in stages if row["custom"])}]


# ---------------------------------------------------------------- 破处疼痛

def hymen_relief(state: dict, settings: Settings, *, pleasure: float,
                 now: float | None = None) -> dict:
    """湿润度 + 快感都够的话，破处没那么疼（返回 0–1 的减弱比例）。"""
    wet = value_of(state, settings, now)
    wet_at = util.clamp(settings.float("wetness.pain_wetness_at", 0.0, 100.0), 0.0, 100.0)
    pleasure_at = util.clamp(settings.float("wetness.pain_pleasure_at", 0.0, 100.0), 0.0, 100.0)
    ratio = util.clamp(settings.float("wetness.pain_relief", 0.0, 100.0), 0.0, 100.0)
    wet_enough = wet >= wet_at
    pleasure_enough = util.safe_float(pleasure, 0.0) >= pleasure_at
    relief = (ratio / 100.0) if (wet_enough and pleasure_enough) else 0.0
    return {
        "wet": round(wet, 1),
        "wet_at": wet_at,
        "pleasure": round(util.safe_float(pleasure, 0.0), 1),
        "pleasure_at": pleasure_at,
        "wet_enough": wet_enough,
        "pleasure_enough": pleasure_enough,
        "relief": round(relief, 2),
        "pain": pain_label(relief),
    }


def pain_label(relief: float) -> str:
    if relief >= 0.9:
        return "none"
    if relief >= 0.45:
        return "slight"
    return "normal"


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    value = value_of(state, settings, now)
    level = level_of(value, settings, state)
    return {
        "enabled": enabled(settings),
        "value": round(value, 1),
        "base": round(base(settings, state), 1),
        "base_float": base_float(state, settings, now=now),
        "base_effective": base_effective(state, settings, now=now),
        "level": level,
        "level_title": level_title(level),
        "prompt": prompt_of(state, level),
        "level_at": [round(level_at(settings, index, state), 0) for index in (1, 2, 3)],
        "idle_minutes": idle_minutes(settings),
        "decay_per_hour": decay_per_hour(settings),
        "gain_per_touch": settings.float("wetness.gain_per_touch", 0.0, 100.0),
        "gain_per_pleasure": settings.float("wetness.gain_per_pleasure", 0.0, 10.0),
        "pain_wetness_at": settings.float("wetness.pain_wetness_at", 0.0, 100.0),
        "pain_pleasure_at": settings.float("wetness.pain_pleasure_at", 0.0, 100.0),
        "pain_relief": settings.float("wetness.pain_relief", 0.0, 100.0),
        "fish_desire_to_wet": settings.float("wetness.fish_desire_to_wet", 0.0, 100.0),
        "fish_desire_min_minutes": max(0, settings.int("wetness.fish_desire_min_minutes", 0, 1440)),
        "prompts": prompts_payload(state),
    }


def prompt_block(state: dict, settings: Settings, *, in_scene: bool,
                 daily_active: bool = False, now: float | None = None) -> str:
    """活动里都带；日常里只在她确实湿到一定程度时才带（免得平常聊天也提）。"""
    if not enabled(settings):
        return ""
    now = now or util.now_ts()
    value = value_of(state, settings, now)
    level = level_of(value, settings)
    if level <= 0:
        return ""
    min_level = int(tuning.get(state, "wetness", "prompt_min_level",
                               settings.int("wetness.prompt_min_level", 1, 4)))
    if not in_scene and not daily_active and level < min_level:
        return ""
    if in_scene:
        try:
            from . import unbirth
            if unbirth.inside(state, settings):
                ub_text = prompts.text(state, "unbirth", "wet",
                                       level=level_title(level))
                return ("【Unbirth·湿润】\n"
                        f"- {ub_text}\n"
                        "（这是她被他在里面撑着时的湿润程度，别报数值。）")
        except Exception:
            pass
    return ("【湿润度】\n"
            f"- {level_title(level)}（{value:.0f}/100）：{prompt_of(state, level)}。\n"
            "（这是她身体此刻的湿润程度，活动外也可能一直是这样；别报数值。）")


def clear(state: dict, settings: Settings, now: float | None = None) -> None:
    now = now or util.now_ts()
    state["wetness"] = {"value": round(base(settings), 2), "at": now}
