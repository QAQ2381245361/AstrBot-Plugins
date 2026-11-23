"""日常情绪：欲望度 / 羞耻度。

这两条数值只在**日常**里起作用（受孕活动里有更直接的那套）：

- 欲望度：每次激发小玩具就涨（`mood.desire_gain`），随时间回退（比羞耻快一点点）；
  满了会把她推到"自己贴上来"的程度 —— 由 main 负责把它升级成正常受孕场景；
- 羞耻度：每次激发小玩具涨（`mood.shame_gain`）；安慰、摸摸头、亲吻、正常聊天
  都能降；随时间也会回落。满了会给她添一点鱼之心的「责怪」，并进入一段羞耻期，
  羞耻期里她自己不肯再碰玩具；
- 两条都有 4 段提示词（可在面板「敏感点阶段性表现设置 → 日常情绪」里改）。

数值都按"用到的时候才算"处理：不跑定时器，插件停几天再开也能自然回落。
"""

from __future__ import annotations

from . import tuning, util
from .settings import Settings

MOOD_KEYS = ("desire", "shame")
MOOD_LABELS = {"desire": "欲望度", "shame": "羞耻度"}
MOOD_MAX = 100.0
MOOD_PROMPT_MAX = 400
# 满了之后回到多少（这样还能继续涨，不会卡在 100）
FULL_RESET = {"desire": 30.0, "shame": 35.0}

# 4 段：每 25 一点一段
STAGE_NAMES = {
    "desire": ("平静", "起意", "难耐", "满溢"),
    "shame": ("没在意", "有点羞", "脸热", "满溢"),
}

MOOD_DEFAULTS = {"desire": 0.0, "shame": 0.0, "desire_at": 0.0, "shame_at": 0.0,
                 "shame_until": 0.0, "desire_full_at": 0.0, "shame_full_at": 0.0,
                 "relief_at": 0.0, "inited": False}

# 4 段提示词：写"她现在是什么状态"，给模型看
MOOD_PROMPTS = {
    "desire": (
        "身体还安静着，只是偶尔会走神想一下他，转头就被别的事盖过去",
        "心里开始浮起来：坐着也不专心，会不自觉想被碰，但还压得住",
        "已经有点难耐了：小腹发紧、腿会并起来又松开，注意力全被身体拽走",
        "满溢了：几乎没法想别的事，只想被他抱住、压住——再不给就要自己贴上去",
    ),
    "shame": (
        "刚才那点事还能装作没发生，只是会下意识避开他的视线",
        "有点羞：说话变小、耳根发热，被提到刚才的事会立刻岔开话题",
        "脸热得厉害：不敢看他，一边觉得丢人，一边又有点发软",
        "羞耻满溢：恨不得把脸埋进枕头里，连玩具都不肯再碰，只想被哄",
    ),
}


# ---------------------------------------------------------------- 数值

def mood_of(state: dict) -> dict:
    value = state.get("mood")
    if not isinstance(value, dict):
        value = {}
        state["mood"] = value
    for key, default in MOOD_DEFAULTS.items():
        value.setdefault(key, default)
    return value


def level_of(value: float) -> int:
    """0 = 还没起来；1–4 = 四段。"""
    number = util.clamp(util.safe_float(value, 0.0), 0.0, MOOD_MAX)
    if number <= 0:
        return 0
    return max(1, min(4, int((number - 0.001) // 25) + 1))


def stage_name(key: str, level: int) -> str:
    names = STAGE_NAMES.get(key) or ()
    index = int(level) - 1
    return names[index] if 0 <= index < len(names) else ""


def stage_title(key: str, level: int) -> str:
    if int(level) <= 0:
        return "无"
    return f"第{int(level)}段·{stage_name(key, level)}"


def prompt_for(key: str, level: int) -> str:
    row = MOOD_PROMPTS.get(key) or ()
    index = int(level) - 1
    return row[index] if 0 <= index < len(row) else ""


def settle(state: dict, settings: Settings, now: float | None = None) -> dict:
    """按时间把两条数值回退一下（不跑定时器）。"""
    now = now or util.now_ts()
    mood = mood_of(state)
    if not mood.get("inited"):
        # 新建的这条数值：羞耻度一开局就有一点（她要碰小玩具），之后能一路降到 0
        initial = util.clamp(settings.float("mood.shame_initial", 0.0, 100.0), 0.0, MOOD_MAX)
        if not util.safe_float(mood.get("shame"), 0.0):
            mood["shame"] = round(initial, 2)
            mood["shame_at"] = now
        mood["inited"] = True
    for key, rate_path in (("desire", "mood.desire_decay_per_hour"),
                           ("shame", "mood.shame_decay_per_hour")):
        at = util.safe_float(mood.get(f"{key}_at"), 0.0) or now
        value = util.clamp(util.safe_float(mood.get(key), 0.0), 0.0, MOOD_MAX)
        if now > at:
            hours = (now - at) / 3600.0
            short = rate_path.split(".")[-1]
            rate = tuning.get(state, "mood", short,
                              settings.float(rate_path, 0.0, 200.0))
            if rate and hours > 0:
                value = max(0.0, value - rate * hours)
            mood[f"{key}_at"] = now
        mood[key] = round(util.clamp(value, 0.0, MOOD_MAX), 2)
    return mood


def value_of(state: dict, settings: Settings, key: str,
             now: float | None = None) -> float:
    return round(util.safe_float(settle(state, settings, now).get(key), 0.0), 1)


def _set(state: dict, key: str, value: float, now: float) -> float:
    mood = mood_of(state)
    mood[key] = round(util.clamp(value, 0.0, MOOD_MAX), 2)
    mood[f"{key}_at"] = now
    return mood[key]


def adjust(state: dict, settings: Settings, key: str, *,
           delta: float | None = None, value: float | None = None,
           now: float | None = None) -> float:
    """面板手动加减/直接设值（先按时间回退，再改）。"""
    now = now or util.now_ts()
    settle(state, settings, now)
    if key not in MOOD_KEYS:
        return 0.0
    if value is not None:
        new = util.safe_float(value, 0.0)
    else:
        new = util.safe_float(mood_of(state).get(key), 0.0) + util.safe_float(delta, 0.0)
    return _set(state, key, new, now)


# ---------------------------------------------------------------- 触发

def add_toy_gain(state: dict, settings: Settings,
                 now: float | None = None) -> dict:
    """每激发一次小玩具：欲望 +，羞耻 +。返回 {desire, shame}。"""
    now = now or util.now_ts()
    settle(state, settings, now)
    desire = util.safe_float(mood_of(state).get("desire"), 0.0) + \
        settings.float("mood.desire_gain", 0.0, 100.0)
    shame = util.safe_float(mood_of(state).get("shame"), 0.0) + \
        settings.float("mood.shame_gain", 0.0, 100.0)
    return {
        "desire": _set(state, "desire", desire, now),
        "shame": _set(state, "shame", shame, now),
        "desire_gain": round(settings.float("mood.desire_gain", 0.0, 100.0), 2),
        "shame_gain": round(settings.float("mood.shame_gain", 0.0, 100.0), 2),
    }


def comfort(state: dict, settings: Settings, kind: str = "安慰",
            now: float | None = None) -> dict:
    """安慰/摸摸头/亲吻：羞耻明显降、欲望也降一点。"""
    now = now or util.now_ts()
    settle(state, settings, now)
    shame_relief = max(0.0, settings.float("mood.comfort_relief", 0.0, 100.0))
    desire_relief = max(0.0, settings.float("mood.comfort_desire_relief", 0.0, 100.0))
    before_shame = util.safe_float(mood_of(state).get("shame"), 0.0)
    before_desire = util.safe_float(mood_of(state).get("desire"), 0.0)
    shame = _set(state, "shame", before_shame - shame_relief, now)
    desire = _set(state, "desire", before_desire - desire_relief, now)
    return {
        "kind": str(kind or "安慰"),
        "shame": shame, "desire": desire,
        "shame_delta": round(shame - before_shame, 2),
        "desire_delta": round(desire - before_desire, 2),
    }


def daily_relief(state: dict, settings: Settings,
                 now: float | None = None) -> dict:
    """正常进行日常（每聊一轮）羞耻降一点点；有冷却，别一秒钟降十次。"""
    now = now or util.now_ts()
    settle(state, settings, now)
    mood = mood_of(state)
    cooldown = max(0, settings.int("mood.daily_relief_minutes", 0, 240)) * 60
    last = util.safe_float(mood.get("relief_at"), 0.0)
    if cooldown and last and (now - last) < cooldown:
        return {"relief": 0.0, "shame": util.safe_float(mood.get("shame"), 0.0)}
    amount = max(0.0, settings.float("mood.daily_relief", 0.0, 100.0))
    before = util.safe_float(mood.get("shame"), 0.0)
    shame = _set(state, "shame", before - amount, now)
    mood["relief_at"] = now
    return {"relief": round(shame - before, 2), "shame": shame}


# ---------------------------------------------------------------- 满溢

def desire_full(state: dict, settings: Settings, now: float | None = None,
                value: float | None = None) -> bool:
    current = util.safe_float(mood_of(state).get("desire"), 0.0) if value is None else value
    return current >= MOOD_MAX - 1e-9


def shame_full(state: dict, settings: Settings, now: float | None = None) -> bool:
    return util.safe_float(mood_of(state).get("shame"), 0.0) >= MOOD_MAX - 1e-9


def note_desire_full(state: dict, settings: Settings,
                     now: float | None = None) -> None:
    now = now or util.now_ts()
    mood = mood_of(state)
    mood["desire_full_at"] = now
    _set(state, "desire", FULL_RESET["desire"], now)


def start_shame_period(state: dict, settings: Settings,
                       now: float | None = None) -> int:
    """羞耻满溢：进羞耻期，返回持续分钟数。"""
    now = now or util.now_ts()
    mood = mood_of(state)
    minutes = max(1, settings.int("mood.shame_period_minutes", 1, 720))
    mood["shame_until"] = now + minutes * 60
    mood["shame_full_at"] = now
    _set(state, "shame", FULL_RESET["shame"], now)
    return minutes


def shame_period_active(state: dict, now: float | None = None) -> bool:
    now = now or util.now_ts()
    return util.safe_float(mood_of(state).get("shame_until"), 0.0) > now


def shame_period_remaining(state: dict, now: float | None = None) -> int:
    now = now or util.now_ts()
    left = util.safe_float(mood_of(state).get("shame_until"), 0.0) - now
    return 0 if left <= 0 else (int(left) + 59) // 60


def clear_shame_period(state: dict) -> None:
    mood_of(state)["shame_until"] = 0.0


# ---------------------------------------------------------------- 提示词自定义

def _prompt_box(state: dict) -> dict:
    box = state.get("mood_prompts")
    if not isinstance(box, dict):
        box = {}
        state["mood_prompts"] = box
    return box


def _same_as_default(text: str, default: str) -> bool:
    return " ".join(str(text or "").split()) == " ".join(str(default or "").split())


def prompt_override(state: dict | None, key: str, level: int) -> str:
    if not isinstance(state, dict) or int(level) <= 0:
        return ""
    row = _prompt_box(state).get(key)
    if not isinstance(row, (list, tuple)):
        return ""
    index = int(level) - 1
    text = str(row[index] or "").strip() if 0 <= index < len(row) else ""
    if not text:
        return ""
    # 和内置默认一样就当没改（老版本"保存四段"会把没改的也存成覆盖）
    return "" if _same_as_default(text, prompt_for(key, level)) else text


def prompt_of(state: dict | None, key: str, level: int) -> str:
    return prompt_override(state, key, level) or prompt_for(key, level)


def _stage_value(key: str, level: int, text: str) -> str:
    value = str(text or "").strip()[:MOOD_PROMPT_MAX]
    if not value or _same_as_default(value, prompt_for(key, level)):
        return ""
    return value


def set_prompt(state: dict, key: str, level: int, text: str) -> str:
    level = max(1, min(4, int(level)))
    if key not in MOOD_KEYS:
        return ""
    box = _prompt_box(state)
    row = box.get(key)
    row = [str(item or "") for item in row] if isinstance(row, (list, tuple)) else [""] * 4
    while len(row) < 4:
        row.append("")
    row[level - 1] = _stage_value(key, level, text)
    if any(row):
        box[key] = row
    else:
        box.pop(key, None)
    return prompt_of(state, key, level)


def set_prompts(state: dict, key: str, texts) -> list[str]:
    """一次改四段；只把真的改过的段存成覆盖（和默认一样存空）。"""
    values = list(texts or [])[:4]
    while len(values) < 4:
        values.append("")
    box = _prompt_box(state)
    row = [_stage_value(key, index + 1, text) for index, text in enumerate(values)]
    if any(row):
        box[key] = row
    else:
        box.pop(key, None)
    return [prompt_of(state, key, level) for level in (1, 2, 3, 4)]


def reset_prompts(state: dict, key: str | None = None,
                  level: int | None = None) -> int:
    box = _prompt_box(state)
    if not key:
        count = len(box)
        box.clear()
        return count
    if key not in box:
        return 0
    if level is not None:
        row = list(box.get(key) or [])
        index = max(1, min(4, int(level))) - 1
        changed = 1 if index < len(row) and row[index] else 0
        while len(row) < 4:
            row.append("")
        row[index] = ""
        if any(row):
            box[key] = row
        else:
            box.pop(key, None)
        return changed
    box.pop(key, None)
    return 1


def prompts_payload(state: dict) -> list[dict]:
    """设置页「日常情绪」那一栏的数据（两条 × 4 段）。"""
    rows = []
    for key in MOOD_KEYS:
        stages = []
        custom = 0
        for level in (1, 2, 3, 4):
            default = prompt_for(key, level)
            override = prompt_override(state, key, level)
            if override:
                custom += 1
            stages.append({
                "level": level,
                "title": stage_title(key, level),
                "name": stage_name(key, level),
                "default": default,
                "value": override or default,
                "custom": bool(override),
            })
        rows.append({
            "key": key,
            "label": MOOD_LABELS[key],
            "stages": stages,
            "custom_count": custom,
            "stage_custom": custom,
        })
    return rows


# ---------------------------------------------------------------- 面板 / 提示词

def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    settle(state, settings, now)
    mood = mood_of(state)
    stages = {}
    for key in MOOD_KEYS:
        value = util.clamp(util.safe_float(mood.get(key), 0.0), 0.0, MOOD_MAX)
        level = level_of(value)
        stages[key] = {
            "value": round(value, 1),
            "percent": round(value, 1),
            "level": level,
            "name": stage_name(key, level),
            "title": stage_title(key, level),
            "prompt": prompt_of(state, key, level) if level else "",
            "max": MOOD_MAX,
        }
    return {
        "enabled": bool(settings.bool("mood.enabled")),
        "desire": stages["desire"],
        "shame": stages["shame"],
        "shame_period": {
            "active": shame_period_active(state, now),
            "remaining": shame_period_remaining(state, now),
        },
        "full_reset": dict(FULL_RESET),
        "shame_blame": round(tuning.get(state, "mood", "shame_blame",
                                        settings.float("mood.shame_blame", 0.0, 100.0)), 1),
        "shame_blame_config": round(settings.float("mood.shame_blame", 0.0, 100.0), 1),
        "shame_blame_manual": tuning.raw(state, "mood", "shame_blame", None) is not None,
        "apology_blame": round(settings.float("mood.apology_blame", 0.0, 100.0), 1),
        "fish_write": bool(settings.bool("mood.fish_write_enabled")),
    }


def prompt_block(state: dict, settings: Settings, *, now: float | None = None,
                 in_scene: bool = False, daily_active: bool = False) -> str:
    """日常情绪写进提示词：**只在"正在用玩具那一小段"或"羞耻期"里带**。

    平常日子里（没碰玩具、也没在羞耻期）一个字都不给，免得模型凭空写她的羞耻/欲望；
    数值本身还会照常随时间回落，面板上一直能看到。
    """
    if not settings.bool("mood.enabled") or in_scene:
        return ""
    now = now or util.now_ts()
    period_left = shame_period_remaining(state, now)
    if not daily_active and not period_left:
        return ""
    settle(state, settings, now)
    lines = []
    for key in MOOD_KEYS:
        value = util.clamp(util.safe_float(mood_of(state).get(key), 0.0), 0.0, MOOD_MAX)
        level = level_of(value)
        if level <= 0:
            continue
        lines.append(f"- {MOOD_LABELS[key]}（{stage_title(key, level)}，{value:.0f}%）："
                     f"{prompt_of(state, key, level)}。")
    if period_left:
        lines.append(f"- 她刚羞耻过头，正在羞耻期：接下来约 {period_left} 分钟她自己不肯碰玩具。")
    if not lines:
        return ""
    body = "\n".join(lines)
    return ("【日常情绪】\n" + body +
            "\n（这些是她日常里的真实状态：按这个写她的小动作和语气，别报数值。"
            "欲望满了她会自己贴上来、转成正式场景；羞耻满了会进一段不肯碰玩具的羞耻期。）")
