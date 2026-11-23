"""衣装：槽位、冲突、穿脱、遮挡与提示词。

槽位（每槽只能穿一件）：
- `coat` 外套；`top` 上装（衬衫/连衣裙/吊带/胸罩）；`bottom` 下装（裤子/短裙/长裙）；
- `underwear` 内裤；`legs` 袜类；`feet` 鞋。
- 连衣裙独占上下装：穿裙子时不能穿下装；下装也穿不上（要先脱裙子）。
- 默认穿搭（首次使用）：女仆连衣裙（藏青+白围裙）+ 胸罩 + 内裤 + 白色及膝袜 + 深蓝玛丽珍鞋
  （照 DeepSeek 鲸鱼娘的参考图；腿/鞋/内衣都在衣柜里，随时可换）。

遮挡：内裤没脱 → 阴道/G点/子宫颈/子宫/肛不能直接来；上装没脱 → 胸/乳头不能直接来，
但可以隔着衣物舔/捏（`through` 方法），提示词单独一套。
"""

from __future__ import annotations

from . import mood, prompts, tuning, util, wetness
from .settings import Settings

SLOTS = ("coat", "under_top", "top", "bottom", "bra", "underwear", "pad", "legs", "feet")
SLOT_LABELS = {"coat": "外套", "under_top": "内衬（穿在里面）",
               "top": "上装", "bottom": "下装",
               "bra": "胸罩（看不见）", "underwear": "内裤（看不见）",
               "pad": "卫生巾（看不见）",
               "legs": "腿/袜", "feet": "鞋"}
DRESS_KEYS = ("dress", "maid_dress", "nightgown")
PAD_KEYS = ("pad", "pad_liner", "pad_regular", "pad_night")

# key: (slot, label, group)  group 用来分"上/下装"显示
CATALOG = {
    # 外套
    "coat": ("coat", "外套", "outer"),
    # 上装
    "shirt": ("top", "衬衫", "upper"),
    "dress": ("top", "连衣裙", "upper"),
    "maid_dress": ("top", "女仆连衣裙", "upper"),
    "pajamas": ("top", "睡衣", "upper"),
    "nightgown": ("top", "睡裙", "upper"),
    "camisole": ("under_top", "内衬", "under"),
    "bra": ("bra", "胸罩", "underwear"),
    # 下装
    "pants": ("bottom", "裤子", "lower"),
    "skirt": ("bottom", "短裙", "lower"),
    "long_skirt": ("bottom", "长裙", "lower"),
    "pajama_pants": ("bottom", "睡裤", "lower"),
    # 内裤
    "panties": ("underwear", "内裤", "underwear"),
    "pad": ("pad", "卫生巾", "underwear"),
    "pad_liner": ("pad", "护垫", "underwear"),
    "pad_regular": ("pad", "日用卫生巾", "underwear"),
    "pad_night": ("pad", "夜用卫生巾", "underwear"),
    "pad_pants": ("pad", "安睡裤", "underwear"),
    # 腿
    "short_socks": ("legs", "短丝袜", "legs"),
    "mid_socks": ("legs", "中筒丝袜", "legs"),
    "knee_socks": ("legs", "及膝丝袜", "legs"),
    "thigh_high": ("legs", "大腿丝袜", "legs"),
    "over_knee": ("legs", "过膝丝袜", "legs"),
    "pantyhose": ("legs", "连裤丝袜", "legs"),
    "garter": ("legs", "吊带丝袜", "legs"),
    # 鞋
    "sneakers": ("feet", "休闲鞋", "feet"),
    "slippers": ("feet", "拖鞋", "feet"),
    "heels": ("feet", "高跟鞋", "feet"),
    "mary_janes": ("feet", "玛丽珍鞋", "feet"),
}

DEFAULT_OUTFIT = {"coat": "", "under_top": "", "top": "maid_dress", "bottom": "",
                  "bra": "bra", "underwear": "panties", "pad": "",
                  "legs": "knee_socks", "feet": "mary_janes"}

BLOCK_UNDER = ("vagina", "gspot", "cervix", "uterus", "anus")
KEYWORD_DEFAULT = {
    "remove_underwear": ["脱内裤", "脱下内裤", "扒内裤", "把内裤脱"],
    "wear_underwear": ["穿内裤", "穿上内裤", "换内裤"],
}


def _clean_words(value) -> list[str]:
    if isinstance(value, str):
        value = value.replace("，", ",").split(",")
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        word = str(item).strip()
        if word and word not in out:
            out.append(word)
    return out[:30]


def keyword_words(state: dict) -> dict:
    row = state.get("clothing_keywords")
    if isinstance(row, dict):
        return {
            "remove_underwear": _clean_words(row.get("remove_underwear")) or
            list(KEYWORD_DEFAULT["remove_underwear"]),
            "wear_underwear": _clean_words(row.get("wear_underwear")) or
            list(KEYWORD_DEFAULT["wear_underwear"]),
        }
    # 兼容旧版的文本格式
    legacy = state.get("clothing_keywords_text")
    if isinstance(legacy, str) and legacy.strip():
        parsed = {}
        for line in legacy.splitlines():
            if "=" not in line:
                continue
            action, _, body = line.partition("=")
            parsed[action.strip()] = _clean_words(body)
        if parsed:
            return {
                "remove_underwear": parsed.get("remove_underwear") or
                list(KEYWORD_DEFAULT["remove_underwear"]),
                "wear_underwear": parsed.get("wear_underwear") or
                list(KEYWORD_DEFAULT["wear_underwear"]),
            }
    return {key: list(words) for key, words in KEYWORD_DEFAULT.items()}


def keyword_payload(state: dict) -> dict:
    return keyword_words(state)


def set_keyword_words(state: dict, remove_words, wear_words) -> dict:
    rows = {
        "remove_underwear": _clean_words(remove_words),
        "wear_underwear": _clean_words(wear_words),
    }
    state["clothing_keywords"] = rows
    state.pop("clothing_keywords_text", None)
    return rows


def detect_action(state: dict, text: str) -> str:
    body = str(text or "")
    if not body:
        return ""
    for action, words in keyword_words(state).items():
        if any(word in body for word in words):
            return action
    return ""


PANTIES_DEFAULT = {"wet_cause": "", "wet_at": 0.0,
                   "dirty_cause": "", "dirty_at": 0.0}
BOTTOM_WET_DEFAULT = {"cause": "", "at": 0.0}
WET_CAUSE_LABELS = {"love": "爱液", "semen": "精液", "lube": "润滑", "squirt": "潮吹"}


def panties_data(state: dict) -> dict:
    row = state.get("panties")
    if not isinstance(row, dict):
        row = dict(PANTIES_DEFAULT)
        state["panties"] = row
    for key, default in PANTIES_DEFAULT.items():
        row.setdefault(key, default)
    return row


def mark_panties_wet(state: dict, cause: str, now: float | None = None) -> None:
    row = panties_data(state)
    row["wet_cause"] = str(cause or "")
    row["wet_at"] = now or util.now_ts()


def panties_cause(state: dict) -> str:
    row = panties_data(state)
    return str(row.get("dirty_cause") or row.get("wet_cause") or "")


def bottom_wet_data(state: dict) -> dict:
    row = state.get("bottom_wet")
    if not isinstance(row, dict):
        row = dict(BOTTOM_WET_DEFAULT)
        state["bottom_wet"] = row
    for key, default in BOTTOM_WET_DEFAULT.items():
        row.setdefault(key, default)
    return row


def mark_bottom_wet(state: dict, cause: str, now: float | None = None) -> None:
    row = bottom_wet_data(state)
    row["cause"] = str(cause or "")
    row["at"] = now or util.now_ts()


def bottom_cause(state: dict) -> str:
    return str(bottom_wet_data(state).get("cause") or "")


def refresh(state: dict, settings: Settings, slot: str,
            now: float | None = None) -> dict:
    """把当前这件换成干净的新一件（只清湿痕/脏污，不改变款式）。"""
    now = now or util.now_ts()
    row = worn(state, settings)
    item = row.get(str(slot) or "")
    if not item:
        return {"ok": False, "reason": "这一格现在没穿衣服"}
    if slot == "underwear":
        state["panties"] = dict(PANTIES_DEFAULT)
    if slot == "bottom":
        state["bottom_wet"] = dict(BOTTOM_WET_DEFAULT)
    line = prompts.text(state, "clothing", "replace_fresh",
                        item=label_of(str(item.get("key") or "")) or "衣服")
    state["clothing_note"] = {"at": now, "line": line}
    return {"ok": True, "slot": slot, "item": item, "line": line}
BLOCK_UPPER = ("breast", "nipple")


def enabled(settings: Settings) -> bool:
    return settings.bool("clothing.enabled")


def label_of(key: str) -> str:
    row = CATALOG.get(str(key) or "")
    return row[1] if row else ""


def slot_of(key: str) -> str:
    row = CATALOG.get(str(key) or "")
    return row[0] if row else ""


def data(state: dict, settings: Settings | None = None) -> dict:
    value = state.get("outfit")
    if not isinstance(value, dict):
        value = dict(DEFAULT_OUTFIT) if (settings is None or settings.bool(
            "clothing.default_outfit")) else {slot: "" for slot in SLOTS}
        state["outfit"] = value
    for slot in SLOTS:
        value.setdefault(slot, "")
    return value


def worn_key(state: dict, settings: Settings, slot: str) -> str:
    return str(data(state, settings).get(slot) or "")


def worn(state: dict, settings: Settings) -> dict:
    row = data(state, settings)
    return {slot: {"key": str(row.get(slot) or ""),
                   "label": label_of(str(row.get(slot) or ""))} for slot in SLOTS}


def summary(state: dict, settings: Settings) -> dict:
    row = worn(state, settings)
    top = row["top"]
    dress = top["key"] in DRESS_KEYS
    upper = [row["coat"]["label"], top["label"]]
    upper = [item for item in upper if item]
    if not upper:
        # 只剩内衣的时候不算"裸着"
        upper = [row["under_top"]["label"] or row["bra"]["label"] or "裸着"]
    lower = [top["label"]] if dress else [row["bottom"]["label"]]
    lower = [item for item in lower if item]
    return {
        "upper": "、".join(upper),
        "lower": "、".join(lower) or "裸着",
        "legs": row["legs"]["label"] or "裸着",
        "feet": row["feet"]["label"] or "裸着",
        "dress": dress,
        "underwear": row["underwear"]["label"] or "没穿",
        "bra": row["bra"]["label"] or "没穿",
        "under_top": row["under_top"]["label"] or "没穿",
    }


def _conflict(state: dict, settings: Settings, slot: str, key: str) -> str:
    row = data(state, settings)
    if slot == "top" and key in DRESS_KEYS and row.get("bottom"):
        return "穿着连衣裙时不能同时穿下装（先脱掉下装）"
    if slot == "bottom" and str(row.get("top") or "") in DRESS_KEYS:
        return "现在穿着连衣裙，下装穿不进去（先脱连衣裙）"
    if slot == "coat" and row.get("coat"):
        return "外套只能穿一件"
    return ""


def wear(state: dict, settings: Settings, slot: str, key: str,
         now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings):
        return {"ok": False, "reason": "衣装系统关着"}
    if slot not in SLOTS:
        return {"ok": False, "reason": "没有这个部位"}
    key = str(key or "")
    if key and key not in CATALOG:
        return {"ok": False, "reason": "没有这件衣服"}
    if key and slot_of(key) != slot:
        slot = slot_of(key)
    conflict = _conflict(state, settings, slot, key)
    if conflict:
        return {"ok": False, "reason": conflict}
    row = data(state, settings)
    if key in PAD_KEYS and not str(row.get("underwear") or ""):
        return {"ok": False, "reason": "没穿内裤，不能垫卫生巾"}
    if key == "nightgown":
        missing = []
        if not str(row.get("bra") or ""):
            missing.append("内衣")
        if not str(row.get("underwear") or ""):
            missing.append("内裤")
        if missing:
            return {"ok": False,
                    "reason": "睡裙里面要先穿好" + "和".join(missing)}
    before = str(row.get(slot) or "")
    row[slot] = key
    if slot == "top" and key in DRESS_KEYS:
        row["bottom"] = ""
    relief = 0.0
    if key and key != before and settings.bool("clothing.shame_relief_enabled"):
        relief = settings.float("clothing.wear_shame_relief", 0.0, 100.0)
        mood.adjust(state, settings, "shame", delta=-relief, now=now)
    line = prompts.text(state, "clothing", "wear") if key else ""
    if key in DRESS_KEYS:
        line = prompts.text(state, "clothing", "wear_dress",
                            item=label_of(key)) or line
    if key == "pajamas":
        line = prompts.text(state, "clothing", "pajamas_wear") or line
    if key == "pajama_pants":
        line = prompts.text(state, "clothing", "pajama_pants_wear") or line
    if key == "nightgown":
        line = prompts.text(state, "clothing", "nightgown_wear") or line
    if key in ("pad", "pad_liner", "pad_regular", "pad_night", "pad_pants"):
        line = prompts.text(state, "clothing", f"wear_{key}") or \
            prompts.text(state, "clothing", "pad_wear") or line
    if slot == "underwear" and key == "panties":
        cause = panties_cause(state)
        if cause:
            line = prompts.text(state, "clothing", f"wear_underwear_{cause}") or line
            row_state = panties_data(state)
            row_state.update(PANTIES_DEFAULT)
        else:
            line = prompts.text(state, "clothing", "wear_underwear") or line
    return {"ok": True, "slot": slot, "before": before, "key": key,
            "label": label_of(key) or "脱掉", "shame_relief": round(relief, 1),
            "line": line}


def remove(state: dict, settings: Settings, slot: str, now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not enabled(settings):
        return {"ok": False, "reason": "衣装系统关着"}
    if slot not in SLOTS:
        return {"ok": False, "reason": "没有这个部位"}
    row = data(state, settings)
    key = str(row.get(slot) or "")
    if not key:
        return {"ok": False, "reason": "这里本来就没穿"}
    row[slot] = ""
    if slot == "underwear" and str(row.get("pad") or "") in PAD_KEYS:
        row["pad"] = ""
    shame = max(0.0, tuning.get(
        state, "clothing", "remove_shame",
        settings.float("clothing.remove_shame", 0.0, 100.0)))
    cap = max(0.0, tuning.get(
        state, "clothing", "remove_shame_max",
        settings.float("clothing.remove_shame_max", 0.0, 100.0)))
    desire = max(0.0, tuning.get(
        state, "clothing", "remove_desire",
        settings.float("clothing.remove_desire", 0.0, 100.0)))
    if settings.bool("clothing.remove_adds_mood"):
        before = mood.value_of(state, settings, "shame", now=now)
        shame = max(0.0, min(shame, cap - before))
        mood.adjust(state, settings, "shame", delta=shame, now=now)
        mood.adjust(state, settings, "desire", delta=desire, now=now)
    line_key = f"remove_{slot}" if f"remove_{slot}" in {
        key for key, _ in prompts.items("clothing")} else "remove_default"
    if slot == "pad":
        from . import menstrual
        line_key = "pad_remove_wet" if menstrual.pad_percent(state, settings) > 0 else "pad_remove_dry"
        return {"ok": True, "slot": slot, "key": key, "label": label_of(key),
                "shame": round(shame, 1), "desire": round(desire, 1),
                "line": prompts.text(state, "clothing", line_key,
                                     source=menstrual.pad_source_text(state))}
    source = ""
    if slot == "underwear":
        cause = panties_cause(state)
        if not cause and key == "panties":
            floor = wetness.base_effective(state, settings, now=now)
            if wetness.value_of(state, settings, now) >= max(20.0, floor + 10.0):
                cause = "love"
        if cause:
            line_key = f"remove_underwear_{cause}"
            row_state = panties_data(state)
            row_state["dirty_cause"] = cause
            row_state["dirty_at"] = now
            try:
                from . import menstrual
                source = menstrual.pad_source_text(state)
            except Exception:
                source = ""
    return {"ok": True, "slot": slot, "key": key, "label": label_of(key),
            "shame": round(shame, 1), "desire": round(desire, 1),
            "line": prompts.text(state, "clothing", line_key,
                                 item=label_of(key), source=source)}


def blocked(state: dict, settings: Settings, zone: str) -> tuple[bool, str]:
    """这个部位是不是被衣服挡着（挡着就只能隔着衣物）。"""
    if not enabled(settings):
        return False, ""
    row = data(state, settings)
    if zone in BLOCK_UNDER and row.get("underwear"):
        return True, row.get("underwear") or ""
    if zone in BLOCK_UPPER and (row.get("top") or row.get("coat") or row.get("under_top")):
        return True, (row.get("under_top") or row.get("top") or row.get("coat") or "")
    return False, ""


def through_prompt(state: dict, zone: str) -> str:
    key = "through_lower" if zone in BLOCK_UNDER else "through_upper"
    return prompts.text(state, "clothing", key, zone=prompts.key_label("clothing", key))


def footjob_prompt(state: dict, settings: Settings) -> str:
    row = data(state, settings)
    socks = bool(row.get("legs"))
    shoes = bool(row.get("feet"))
    key = "footjob_shoes" if (socks and shoes) else "footjob_socks" if socks else "footjob_bare"
    return prompts.text(state, "clothing", key)


def ejac_prompt(state: dict, settings: Settings, zone: str, *, in_shoe: bool = False) -> str:
    row = data(state, settings)
    if zone == "foot":
        key = "ejac_shoe_in" if in_shoe else "ejac_shoe_out"
        return prompts.text(state, "clothing", key)
    if zone in BLOCK_UNDER and row.get("underwear"):
        key = "ejac_lower"
        if str(row.get("bottom") or "") == "pajama_pants":
            key = "ejac_pajama_pants"
        return prompts.text(state, "clothing", key)
    if zone in BLOCK_UPPER and (row.get("top") or row.get("coat")):
        top = str(row.get("top") or "")
        key = {"pajamas": "ejac_pajamas", "nightgown": "ejac_nightgown",
               "dress": "ejac_dress", "maid_dress": "ejac_dress"}.get(top, "ejac_upper")
        return prompts.text(state, "clothing", key)
    return ""


def panties_prompt(state: dict, settings: Settings, *, leaking: bool = False) -> str:
    row = data(state, settings)
    if not row.get("underwear"):
        return ""
    cause = panties_cause(state)
    key = ("panties_leak" if leaking else "panties_wet")
    if cause:
        key = f"{key}_{cause}"
    return prompts.text(state, "clothing", key)


def bottom_wet_prompt(state: dict, settings: Settings) -> str:
    row = data(state, settings)
    if not row.get("bottom"):
        return ""
    cause = bottom_cause(state)
    if not cause:
        return ""
    return prompts.text(state, "clothing", f"bottom_wet_{cause}")


def sleepwear_note(state: dict, settings: Settings, now: float | None = None) -> str:
    """睡衣相关的当前提示：刚换/穿着睡衣时给模型一句。"""
    now = now or util.now_ts()
    note = state.get("sleepwear_note")
    if isinstance(note, dict):
        if now - util.safe_float(note.get("at"), 0.0) < 180 * 60:
            return str(note.get("line") or "")
    if worn(state, settings)["top"]["key"] == "pajamas":
        return prompts.text(state, "clothing", "pajamas_inside")
    return ""


def payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    now = now or util.now_ts()
    row = worn(state, settings)
    info = summary(state, settings)
    wet = []
    panties = panties_cause(state)
    if row.get("underwear") and panties:
        wet.append({"slot": "underwear", "label": info.get("underwear") or "内裤",
                    "cause": panties,
                    "cause_label": WET_CAUSE_LABELS.get(panties, panties)})
    bottom = bottom_cause(state)
    if row.get("bottom") and bottom:
        wet.append({"slot": "bottom", "label": info.get("lower") or "下装",
                    "cause": bottom,
                    "cause_label": WET_CAUSE_LABELS.get(bottom, bottom)})
    change = state.get("clothing_change") if isinstance(
        state.get("clothing_change"), dict) else {}
    pending = {}
    if change.get("items"):
        pending = {
            "label": str(change.get("label") or ""),
            "slots": [str(slot) for slot, _key in (change.get("items") or [])],
            "keys": [str(key) for _slot, key in (change.get("items") or [])],
            "left_minutes": max(0, int((util.safe_float(
                change.get("until"), 0.0) - now + 59) // 60)),
        }
    slots = []
    for slot in SLOTS:
        slots.append({
            "slot": slot,
            "label": SLOT_LABELS[slot],
            "worn": row[slot],
            "items": [{"key": key, "label": label}
                      for key, (item_slot, label, _group) in CATALOG.items()
                      if item_slot == slot],
        })
    return {
        "enabled": enabled(settings),
        "slots": slots,
        "summary": info,
        "wet": wet,
        "pending": pending,
        "remove_shame": settings.float("clothing.remove_shame", 0.0, 100.0),
        "remove_desire": settings.float("clothing.remove_desire", 0.0, 100.0),
        "wear_relief": settings.float("clothing.wear_shame_relief", 0.0, 100.0),
        "footjob": footjob_prompt(state, settings),
        "sleepwear_pending": bool((state.get("sleepwear_pending") or {}).get("day")),
    }


def block(state: dict, settings: Settings, *, in_scene: bool, wetness_value: float = 0.0,
          leaking: bool = False) -> str:
    if not enabled(settings):
        return ""
    info = summary(state, settings)
    lines = [f"上：{info['upper']}｜下：{info['lower']}｜腿：{info['legs']}｜脚：{info['feet']}"]
    wet = panties_prompt(state, settings, leaking=leaking)
    if wet:
        lines.append(wet)
    bottom_wet = bottom_wet_prompt(state, settings)
    if bottom_wet:
        lines.append(bottom_wet)
    if in_scene:
        foot = footjob_prompt(state, settings)
        if foot:
            lines.append(foot)
        row = data(state, settings)
        top = str(row.get("top") or "")
        bottom = str(row.get("bottom") or "")
        if top == "nightgown":
            scene = prompts.text(state, "clothing", "scene_nightgown")
        elif top == "pajamas" and bottom == "pajama_pants":
            scene = prompts.text(state, "clothing", "scene_pajamas_pants")
        elif top == "pajamas":
            scene = prompts.text(state, "clothing", "scene_pajamas")
        elif bottom == "pajama_pants":
            scene = prompts.text(state, "clothing", "scene_pajama_pants")
        else:
            scene = ""
        if scene:
            lines.append(scene)
    return "【衣装】\n- " + "\n- ".join(lines)


def clear(state: dict) -> None:
    state["outfit"] = {slot: "" for slot in SLOTS}
