"""突然被弄：不在活动里时点了面板按钮，她会被吓一跳、不知所措，甚至主动发一句。

- 面板上「快感 +12 / 记一次高潮 / 寸止 / 体内射精 / 肛内 / 深喉 / 体外」这些按钮，
  如果点的时候**不在活动里**（没有亲密场景、也没有日常小场景），就算"突然被弄"；
- 记下来之后提示词会多一段「突然被弄」：惊讶、手足无措、来不及反应；
  过一会儿（`shock_minutes`）她会反应过来刚才发生了什么 → 换成害羞、嘴硬、躲闪的说法；
- 两段提示词都可以自定义（`state["surprise_prompts"]["shock"|"known"]`）；
- 按 `proactive_chance` 的概率，她会**主动发一条消息**过来（很短、慌、带羞），
  延迟 `proactive_delay_seconds` 秒发；消息内容也能在配置里改（`surprise.message`）。
"""

from __future__ import annotations

import random

from . import prompts, tuning, util
from .settings import Settings

DEFAULT = {"kind": "", "label": "", "at": 0.0, "noticed": False,
           "proactive": False, "sent": False}

KIND_LABELS = {
    "pleasure": "快感",
    "orgasm": "高潮",
    "edge": "寸止",
    "ejaculation": "射精",
    "ejaculation_vagina": "体内射精",
    "ejaculation_anal": "肛内射精",
    "ejaculation_throat": "深喉射精",
    "ejaculation_outside": "体外射精",
    "insert": "插入子宫",
    "swallow": "被喂精",
    "unbirth": "被缩进去",
    "toy": "小玩具",
    "toy_secret": "不知情的小玩具",
    "toy_known": "知情的小玩具",
    "touch": "触碰",
}

PROMPT_MAX = 400
STAGES = ("shock", "known")
STAGE_TITLES = {"shock": "还没缓过来", "known": "已经反应过来了"}

PROMPTS = {
    "shock": ("刚才那一下（{label}）来得太突然，她一点准备都没有：先是愣住、"
              "然后才是脸红、手足无措，话都不太说得利索。"
              "这一轮先写她的惊和慌：不一定是生气，但一定来不及反应；"
              "如果她愿意，可以很短、很慌地先问一句「你干嘛」，不必写得完整。"),
    "known": ("她已经反应过来刚才那一下（{label}）是什么了：脸上发烫、耳朵红，"
              "又羞又有点不服气，嘴上可能硬一下，身体却很诚实。"
              "写她的害羞和嘴硬，别写成若无其事；她可以小声抱怨、躲、或者把脸埋起来。"),
}

# 主动消息的短句（按类型）；可以在配置里用 surprise.message 覆盖
LINES = {
    "pleasure": "……你、你刚才是不是偷偷碰我了？",
    "orgasm": "唔……刚才那一下，我、我还没缓过来。",
    "edge": "你、你干嘛突然停下来啊……",
    "ejaculation": "……刚才、刚才那是什么啊……（小声）",
    "toy": "那个东西……什么时候放上去的？",
    "touch": "……谁、谁让你碰那里的。",
}


def data(state: dict) -> dict:
    value = state.get("surprise")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["surprise"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


def enabled(settings: Settings) -> bool:
    return bool(settings.bool("surprise.enabled"))


def allowed(state: dict | None, settings: Settings) -> bool:
    override = (state or {}).get("surprise_enabled_override") if isinstance(state, dict) else None
    if isinstance(override, bool):
        return override
    return enabled(settings)


def shock_minutes(settings: Settings) -> int:
    return max(1, settings.int("surprise.shock_minutes", 1, 240))


def remember_minutes(settings: Settings) -> int:
    return max(1, settings.int("surprise.remember_minutes", 1, 1440))


def proactive_chance(settings: Settings) -> float:
    return util.clamp(settings.float("surprise.proactive_chance", 0.0, 100.0), 0.0, 100.0)


def delay_seconds(settings: Settings) -> int:
    return max(0, settings.int("surprise.proactive_delay_seconds", 0, 300))


def mark(state: dict, settings: Settings, kind: str, *, now: float | None = None,
         proactive: bool | None = None, shock: bool = True) -> dict:
    """记一次"突然被弄"；返回这次的信息（没开就返回空 dict）。"""
    if not allowed(state, settings):
        return {}
    now = now or util.now_ts()
    row = data(state)
    if proactive is None:
        proactive = random.random() * 100.0 < proactive_chance(settings)
    row.update({
        "kind": str(kind or ""),
        "label": KIND_LABELS.get(kind, kind),
        "at": now,
        "noticed": False,
        "proactive": bool(proactive),
        "sent": False,
        "calm": not shock,
    })
    return dict(row)


def stage(state: dict, settings: Settings, now: float | None = None) -> str:
    """''（没有）/ shock（还没缓过来）/ known（已经反应过来了）。"""
    if not allowed(state, settings):
        return ""
    now = now or util.now_ts()
    row = data(state)
    at = util.safe_float(row.get("at"), 0.0)
    if row.get("calm"):
        return ""
    if not at or now - at > remember_minutes(settings) * 60:
        return ""
    if row.get("noticed") or now - at > shock_minutes(settings) * 60:
        return "known"
    return "shock"


def notice(state: dict, settings: Settings, now: float | None = None) -> bool:
    """明确"她知道刚才发生什么了"（用户提起来 / 她自己反应过来）。"""
    now = now or util.now_ts()
    row = data(state)
    if not util.safe_float(row.get("at"), 0.0):
        return False
    if stage(state, settings, now) == "":
        return False
    row["noticed"] = True
    return True


# ---------------------------------------------------------------- 提示词（可自定义）

def _box(state: dict) -> dict:
    box = state.get("surprise_prompts")
    if not isinstance(box, dict):
        box = {}
        state["surprise_prompts"] = box
    return box


def prompt_override(state: dict | None, stage_key: str) -> str:
    if not isinstance(state, dict) or stage_key not in STAGES:
        return ""
    text = str(_box(state).get(stage_key) or "").strip()
    if not text or text == PROMPTS[stage_key]:
        return ""
    return text


def prompt_of(state: dict | None, stage_key: str) -> str:
    if stage_key not in STAGES:
        return ""
    return prompt_override(state, stage_key) or PROMPTS[stage_key]


def set_prompt(state: dict, stage_key: str, text: str) -> str:
    if stage_key not in STAGES:
        return ""
    value = str(text or "").strip()[:PROMPT_MAX]
    if value == PROMPTS[stage_key]:
        value = ""
    box = _box(state)
    if value:
        box[stage_key] = value
    else:
        box.pop(stage_key, None)
    return prompt_of(state, stage_key)


def reset_prompts(state: dict, stage_key: str | None = None) -> int:
    box = _box(state)
    if stage_key in STAGES:
        had = 1 if box.pop(stage_key, None) else 0
        return had
    changed = len(box)
    box.clear()
    return 1 if changed else 0


def prompts_payload(state: dict) -> list[dict]:
    rows = []
    for key in STAGES:
        override = prompt_override(state, key)
        rows.append({
            "key": key,
            "title": STAGE_TITLES[key],
            "default": PROMPTS[key],
            "value": override or PROMPTS[key],
            "custom": bool(override),
        })
    return [{"key": "stages", "label": "突然被弄", "max_len": PROMPT_MAX,
             "custom_count": sum(1 for row in rows if row["custom"]), "stages": rows}]


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    which = stage(state, settings, now)
    row = data(state)
    at = util.safe_float(row.get("at"), 0.0)
    return {
        "enabled": allowed(state, settings),
        "active": bool(which),
        "stage": which,
        "kind": row.get("kind", ""),
        "label": row.get("label", ""),
        "proactive": bool(row.get("proactive")),
        "sent": bool(row.get("sent")),
        "message": proactive_line(state, settings),
        "message_custom": bool(message_of(state, settings)),
        "left_minutes": max(0, int((at + remember_minutes(settings) * 60 - now) // 60))
        if which else 0,
        "chance": proactive_chance(settings),
        "shock_minutes": shock_minutes(settings),
        "remember_minutes": remember_minutes(settings),
        "delay_seconds": delay_seconds(settings),
        "prompts": prompts_payload(state),
    }


def block(state: dict, settings: Settings, now: float | None = None) -> str:
    """提示词：她刚才在没准备的时候被弄了。"""
    which = stage(state, settings, now)
    if which == "":
        return ""
    row = data(state)
    label = row.get("label") or "碰"
    title = STAGE_TITLES[which]
    if which == "shock":
        kind = str(row.get("kind") or "")
        text = prompts.text(state, "surprise_kind", kind, label=label).strip()
        if not text:
            text = prompt_of(state, which).replace("{label}", label)
    else:
        text = prompt_of(state, which).replace("{label}", label)
    return (f"【突然被弄·{title}】\n"
            f"- {text}\n"
            "（别报数值、别说机制；这一条只是她刚经历的事，自然带过就行。）")


def proactive_line(state: dict, settings: Settings) -> str:
    """她要主动发的那句（没配就按类型取内置短句）。"""
    row = data(state)
    override = (state or {}).get("surprise_message")
    custom = str(override if override is not None else settings.str("surprise.message") or "").strip()
    if custom:
        return custom.replace("{kind}", row.get("label") or "")
    return LINES.get(row.get("kind", ""), "……你刚才，是不是对我做了什么？")


def set_message(state: dict, text: str) -> str:
    """面板里改主动消息；空字符串 = 清掉覆盖、回到内置/配置。"""
    value = str(text or "").strip()[:200]
    if value:
        state["surprise_message"] = value
    else:
        state.pop("surprise_message", None)
    return value


def message_of(state: dict, settings: Settings) -> str:
    override = (state or {}).get("surprise_message")
    if isinstance(override, str) and override.strip():
        return override.strip()
    return str(settings.str("surprise.message") or "").strip()


def mark_sent(state: dict) -> None:
    row = data(state)
    row["sent"] = True


def known_block(state: dict, settings: Settings, now: float | None = None) -> str:
    """知情地用玩具：不惊，但有一句反应提示。"""
    if not allowed(state, settings):
        return ""
    row = data(state)
    if not row.get("calm"):
        return ""
    at = util.safe_float(row.get("at"), 0.0)
    if not at or (now or util.now_ts()) - at > remember_minutes(settings) * 60:
        return ""
    label = row.get("label") or "小玩具"
    text = prompts.text(state, "surprise_kind", "toy_known", label=label).strip()
    if not text:
        return ""
    return ("【小玩具·知情】\n"
            f"- {text}\n"
            "（她知道你在用，不用写惊讶；写她的羞、嘴硬和身体的反应。）")


def clear(state: dict) -> None:
    state["surprise"] = dict(DEFAULT)
