"""行为：正在被怎么弄（牵手、十指相扣、哈热气、尾巴卷起来撸……）。

- 只记最近一次"带方式"的触碰，`behavior.minutes` 分钟内有效；
- 提示词从 `core/prompts.py` 的 hand / tail / ear 组里取（可自定义）；
- 面板「此刻」下面会显示一行；不在活动里也照常（她就是刚被这样弄过）。
"""

from __future__ import annotations

from . import prompts, subzone, util
from .settings import Settings

DEFAULT = {"zone": "", "method": "", "at": 0.0}

GROUP_OF = {
    "hand": "hand",
    "tail": "tail",
    "ear": "ear",
}

BEHAVIOR_METHODS = {
    "hand": ("interlock", "hold", "lick", "suck", "tongue", "masturbate"),
    "tail": ("wrap",),
    "ear": ("blow",),
}


def data(state: dict) -> dict:
    value = state.get("behavior")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["behavior"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def minutes(settings: Settings) -> int:
    return max(1, settings.int("behavior.minutes", 1, 240))


def mark(state: dict, zone: str, method: str, *, now: float | None = None) -> dict:
    zone = str(zone or "")
    method = str(method or "")
    if method not in BEHAVIOR_METHODS.get(zone, ()):
        return {}
    now = now or util.now_ts()
    row = data(state)
    row.update({"zone": zone, "method": method, "at": now})
    group = GROUP_OF.get(zone, zone)
    return {
        "zone": zone,
        "method": method,
        "label": prompts.key_label(group, method),
        "prompt": prompts.prompt_of(state, group, method),
        "at": now,
    }


def current(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = data(state)
    at = util.safe_float(row.get("at"), 0.0)
    if not at or now - at > minutes(settings) * 60:
        return {}
    zone = str(row.get("zone") or "")
    method = str(row.get("method") or "")
    if method not in BEHAVIOR_METHODS.get(zone, ()):
        return {}
    group = GROUP_OF.get(zone, zone)
    return {
        "zone": zone,
        "zone_label": {
            "hand": "手", "tail": "尾巴", "ear": "耳朵",
        }.get(zone, zone),
        "method": method,
        "label": prompts.key_label(group, method),
        "prompt": prompts.prompt_of(state, group, method),
        "left_minutes": max(0, int((at + minutes(settings) * 60 - now) // 60)),
    }


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    current_info = current(state, settings, now)
    return {
        "active": bool(current_info),
        "minutes": minutes(settings),
        **current_info,
    }


def block(state: dict, settings: Settings, now: float | None = None) -> str:
    info = current(state, settings, now)
    if not info:
        return ""
    return (f"【刚才的动作】\n"
            f"- {info['zone_label']}·{info['label']}：{info['prompt']}\n"
            "（这是她刚经历过的动作，别报机制、别重复一遍动作，接着写她的反应就好。）")


def clear(state: dict) -> None:
    state["behavior"] = dict(DEFAULT)
