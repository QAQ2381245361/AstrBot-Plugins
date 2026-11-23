"""敏感点、触碰、射精方式与子宫容量。

敏感点（zone）按配置逐项独立：是否启用、开发度 0–100、敏感度倍率、每次基础快感。
实际快感 = 基础快感 × (0.4 + 0.8 × 开发度/100) × 敏感度。
开发度越高、敏感度越高，同一次触碰涨得越多。

开发度/敏感度有两层：配置（或面板手动值）是底子，
上面还能叠一层 `dev_bonus` / `sens_bonus`——这一层由"子敏感度条溢出"攒下来
（见 core/subzone.py），封顶值在 `sub_zones.dev_cap` / `sub_zones.sensitivity_cap`。

射精方式：vagina（阴道内）/ anal（肛内）/ throat（深喉）/ outside（体外）。
只有 vagina 参与受孕判定，也只有它会把精液计入子宫容量。
"""

from __future__ import annotations

import random

from . import body, succubus, tuning, util
from .settings import Settings

ZONE_ORDER = ("kiss", "breast", "nipple", "clitoris", "vulva", "vagina", "gspot",
              "cervix", "hymen", "tube", "ovary", "anus", "mouth", "ear", "foot",
              "tail", "hand", "uterus")

ZONE_LABELS = {
    "kiss": "亲吻",
    "breast": "乳房",
    "nipple": "乳头",
    "clitoris": "阴蒂",
    "vulva": "外阴",
    "vagina": "阴道",
    "gspot": "G点",
    "cervix": "子宫颈",
    "hymen": "处女膜",
    "tube": "输卵管",
    "ovary": "卵巢",
    "anus": "肛",
    "mouth": "嘴/喉咙",
    "ear": "耳朵",
    "foot": "脚",
    "tail": "尾巴",
    "hand": "手",
    "uterus": "子宫",
}

ZONE_KEYWORDS = {
    "kiss": ("亲吻", "接吻", "亲亲", "亲了", "吻"),
    "breast": ("揉胸", "摸胸", "胸脯", "乳房", "胸部", "揉着胸", "她的胸", "胸"),
    "nipple": ("乳头", "乳尖", "含住"),
    "vulva": ("外阴", "阴唇", "小穴", "下面湿", "摸下面", "揉下面"),
    "vagina": ("插进去", "抽插", "里面", "阴道", "进入她"),
    "gspot": ("g点", "G点", "敏感的那点"),
    "clitoris": ("阴蒂", "豆豆", "小豆豆", "花核", "那颗小豆"),
    "cervix": ("子宫颈", "宫颈", "顶到最里面", "顶到深处"),
    "hymen": ("处女膜", "那层膜", "薄薄的膜"),
    "tube": ("输卵管", "卵管", "管子深处", "输卵管口"),
    "ovary": ("卵巢", "小腹深处", "肚子深处"),
    "anus": ("后庭", "肛", "后面", "菊"),
    "mouth": ("喉咙", "深喉", "嘴里", "含深"),
    "ear": ("耳朵", "耳垂", "耳廓", "咬耳朵", "舔耳朵", "舔耳", "吻耳", "含耳"),
    # 脚：故意不用裸字"脚"——"脚软/脚步/墙角"太容易误触发，只用明确的部位词
    "foot": ("脚趾", "脚背", "脚踝", "脚心", "脚底", "脚掌", "脚丫", "足尖", "足心",
             "足背", "足趾", "赤足", "光脚", "舔脚", "舔足", "玉足", "把玩脚"),
    "tail": ("尾巴", "尾根", "尾尖", "尾巴尖", "揉尾巴", "摸尾巴"),
    "hand": ("牵手", "十指相扣", "手指", "手心", "手背", "舔手", "吮手指", "手淫",
             "帮他撸", "握着", "手掌"),
    # 子宫：故意避开"最里面/深处"这类会跟子宫颈抢的词
    "uterus": ("子宫", "子宫里", "子宫内", "插进子宫", "顶进子宫", "宫腔"),
}

MODE_ORDER = ("vagina", "anal", "throat", "outside", "tube")
MODE_LABELS = {
    "vagina": "阴道内射",
    "anal": "肛内射精",
    "throat": "深喉射精",
    "outside": "体外射精",
    "tube": "射进输卵管",
}
MODE_CONCEIVE = {"vagina": True, "anal": True, "throat": True, "outside": False,
                 "tube": True}
MODE_SHORT = {"vagina": "体内", "anal": "肛内", "throat": "深喉", "outside": "体外",
              "tube": "输卵管"}


def normalize_zone(value: str) -> str:
    key = str(value or "").strip().lower()
    aliases = {
        "亲": "kiss", "亲吻": "kiss", "吻": "kiss",
        "胸": "breast", "乳房": "breast",
        "乳头": "nipple",
        "阴蒂": "clitoris", "clit": "clitoris", "clitoris": "clitoris",
        "卵巢": "ovary", "ovary": "ovary",
        "处女膜": "hymen", "hymen": "hymen",
        "输卵管": "tube", "tube": "tube", "fallopian": "tube",
        "外阴": "vulva", "阴唇": "vulva", "下面": "vulva",
        "阴道": "vagina", "小穴": "vagina",
        "g点": "gspot", "g": "gspot",
        "子宫颈": "cervix", "宫颈": "cervix",
        "肛": "anus", "后庭": "anus", "菊花": "anus",
        "嘴": "mouth", "喉咙": "mouth", "深喉": "mouth",
        "耳": "ear", "耳朵": "ear", "耳垂": "ear", "耳廓": "ear",
        "咬耳朵": "ear", "舔耳": "ear", "舔耳朵": "ear",
        "脚": "foot", "足": "foot", "脚趾": "foot", "脚背": "foot", "脚踝": "foot",
        "脚心": "foot", "脚底": "foot", "脚掌": "foot", "脚丫": "foot", "玉足": "foot",
        "足心": "foot", "足尖": "foot", "足背": "foot", "足趾": "foot",
        "赤足": "foot", "光脚": "foot", "舔脚": "foot", "舔足": "foot",
        "尾巴": "tail", "尾": "tail", "尾根": "tail", "尾尖": "tail",
        "手": "hand", "手掌": "hand", "手心": "hand", "手指": "hand",
        "牵手": "hand", "十指相扣": "hand", "手淫": "hand",
        "子宫": "uterus", "子宫里": "uterus", "子宫内": "uterus", "宫腔": "uterus",
    }
    if key in ZONE_LABELS:
        return key
    return aliases.get(key, "")


def normalize_mode(value: str | bool) -> str:
    if isinstance(value, bool):
        return "vagina" if value else "outside"
    key = str(value or "").strip().lower()
    aliases = {
        "inside": "vagina", "in": "vagina", "vagina": "vagina", "阴道": "vagina",
        "内射": "vagina", "体内": "vagina",
        "anal": "anal", "肛": "anal", "肛内": "anal", "后庭": "anal",
        "throat": "throat", "深喉": "throat", "喉咙": "throat",
        "outside": "outside", "out": "outside", "体外": "outside", "外面": "outside",
        "tube": "tube", "输卵管": "tube", "fallopian": "tube",
    }
    return aliases.get(key, "")


def zone_enabled(settings: Settings, zone: str) -> bool:
    if not settings.bool("zones.enabled"):
        return False
    return settings.bool(f"zones.{zone}_enabled")


def zone_enabled_effective(state: dict | None, settings: Settings, zone: str) -> bool:
    """面板可以单独关掉某个部位（比如角色没有尾巴）。

    尾巴特例：魅魔尾巴开着时，就算「敏感点·尾巴」关着，尾巴也能用。
    """
    if not settings.bool("zones.enabled"):
        return False
    row = (state.get("zones") or {}).get(zone) if isinstance(state, dict) else None
    if isinstance(row, dict) and isinstance(row.get("enabled_override"), bool):
        base = bool(row["enabled_override"])
    else:
        base = settings.bool(f"zones.{zone}_enabled")
    if not base and zone == "tail" and isinstance(state, dict) \
            and succubus.tail_enabled(state, settings):
        return True
    return base


def set_zone_enabled(state: dict, zone: str, value: bool | None) -> None:
    row = state.setdefault("zones", {}).setdefault(zone, {})
    if value is None:
        row.pop("enabled_override", None)
    else:
        row["enabled_override"] = bool(value)


def zone_dev(settings: Settings, zone: str) -> int:
    return settings.int(f"zones.{zone}_dev", 0, 100)


def zone_sensitivity(settings: Settings, zone: str) -> float:
    return settings.float(f"zones.{zone}_sensitivity", 0.0, 5.0)


def zone_dev_bonus(state: dict | None, zone: str) -> float:
    """子敏感度条溢出攒下来的开发度加成（叠在配置/手动值上面）。"""
    row = (state.get("zones") or {}).get(zone) if isinstance(state, dict) else None
    if not isinstance(row, dict):
        return 0.0
    return max(0.0, util.safe_float(row.get("dev_bonus"), 0.0))


def zone_sens_bonus(state: dict | None, zone: str) -> float:
    """子敏感度条溢出攒下来的敏感度加成。"""
    row = (state.get("zones") or {}).get(zone) if isinstance(state, dict) else None
    if not isinstance(row, dict):
        return 0.0
    return max(0.0, util.safe_float(row.get("sens_bonus"), 0.0))


def add_zone_bonus(state: dict, settings: Settings, zone: str, *,
                   dev: float = 0.0, sens: float = 0.0) -> dict:
    """给某个部位加开发度/敏感度（子敏感度溢出时调用），按上限封顶。

    返回加成前后的值，方便面板和日志显示"这次加了多少"。
    """
    row = state.setdefault("zones", {}).setdefault(
        zone, {"touches": 0, "total": 0.0, "last_at": 0.0})
    dev_cap = settings.float("sub_zones.dev_cap", 0.0, 100.0)
    sens_cap = settings.float("sub_zones.sensitivity_cap", 0.0, 20.0)
    before_dev = zone_dev_effective(state, settings, zone)
    before_sens = zone_sensitivity_effective(state, settings, zone)
    if dev:
        row["dev_bonus"] = round(util.clamp(
            util.safe_float(row.get("dev_bonus"), 0.0) + dev, 0.0, max(0.0, dev_cap)), 2)
    if sens:
        dev_now = zone_dev_effective(state, settings, zone)
        boost = settings.float("size.dev_sens_boost", 0.0, 5.0)
        sens = sens * (1.0 + boost * max(0.0, dev_now) / 100.0)
        row["sens_bonus"] = round(util.clamp(
            util.safe_float(row.get("sens_bonus"), 0.0) + sens, 0.0, max(0.0, sens_cap)), 3)
        row["last_sens_at"] = util.now_ts()
    after_dev = zone_dev_effective(state, settings, zone)
    after_sens = zone_sensitivity_effective(state, settings, zone)
    return {
        "dev": after_dev,
        "dev_gain": round(after_dev - before_dev, 2),
        "sensitivity": after_sens,
        "sensitivity_gain": round(after_sens - before_sens, 3),
    }


def clear_zone_bonus(state: dict, zone: str | None = None) -> int:
    """清掉溢出攒的加成（面板"恢复"或重置时用）。"""
    rows = state.get("zones") if isinstance(state.get("zones"), dict) else {}
    keys = [zone] if zone else list(rows.keys())
    cleared = 0
    for key in keys:
        row = rows.get(key)
        if not isinstance(row, dict):
            continue
        if row.pop("dev_bonus", None) is not None or row.pop("sens_bonus", None) is not None:
            cleared += 1
    return cleared


def _settle_sens_bonus(state: dict, settings: Settings, zone: str,
                       now: float | None = None) -> None:
    """敏感度加成很久没涨时慢慢回落；基础配置值不动。"""
    if not isinstance(state, dict):
        return
    row = (state.get("zones") or {}).get(zone)
    if not isinstance(row, dict):
        return
    bonus = max(0.0, util.safe_float(row.get("sens_bonus"), 0.0))
    if bonus <= 0:
        return
    now = now or util.now_ts()
    last = util.safe_float(row.get("last_sens_at"), 0.0)
    if not last or now < last:
        row["last_sens_at"] = now
        return
    after = max(0, settings.int("zones.sens_decay_after_minutes", 0, 10080)) * 60
    rate = max(0.0, settings.float("zones.sens_decay_per_hour", 0.0, 10.0))
    idle = now - last
    if idle <= after or rate <= 0:
        return
    decay = rate * (idle - after) / 3600.0
    row["sens_bonus"] = round(max(0.0, bonus - decay), 3)
    row["last_sens_at"] = now


def zone_sensitivity_effective(state: dict | None, settings: Settings, zone: str) -> float:
    """尾巴算魅魔尾巴时更敏感（倍率可调）；再加上子敏感度攒的加成（有上限）。

    尾巴算不算魅魔尾巴：魅魔模式开着，或者「魅魔尾巴」开关开着
    （后者让关掉魅魔模式时尾巴只是变回普通尾巴，敏感度也跟着恢复）。
    """
    if isinstance(state, dict):
        _settle_sens_bonus(state, settings, zone)
    base = zone_sensitivity(settings, zone)
    cap = max(base, settings.float("sub_zones.sensitivity_cap", 0.0, 20.0))
    sens = min(cap, base + zone_sens_bonus(state, zone))
    if zone == "tail" and isinstance(state, dict) and succubus.tail_active(state, settings):
        scale = tuning.get(state, "succubus", "tail_sensitivity_scale",
                           settings.float("succubus.tail_sensitivity_scale", 1.0, 5.0))
        sens *= max(1.0, scale)
    return round(sens, 3)


def zone_dev_effective(state: dict, settings: Settings, zone: str) -> int:
    """面板可以临时改开发度；没改就跟随配置。溢出攒的加成叠在上面。"""
    row = (state.get("zones") or {}).get(zone)
    if isinstance(row, dict) and row.get("dev_override") is not None:
        base = util.clamp(util.safe_float(row.get("dev_override"), 0.0), 0.0, 100.0)
    else:
        base = zone_dev(settings, zone)
    cap = settings.float("sub_zones.dev_cap", 0.0, 100.0)
    return int(round(util.clamp(base + zone_dev_bonus(state, zone), 0.0, max(100.0, cap))))


def zone_gain(settings: Settings, zone: str) -> float:
    """按公式算一次触碰涨多少快感。"""
    base = settings.float(f"zones.{zone}_pleasure", 0.0, 100.0)
    dev = zone_dev(settings, zone)
    sens = zone_sensitivity(settings, zone)
    gain = base * (0.4 + 0.8 * dev / 100.0) * sens
    return round(max(0.0, gain), 2)


def zone_formula_gain(state: dict, settings: Settings, zone: str) -> float:
    """用当前（可能被面板改过的）开发度算公式值。"""
    base = settings.float(f"zones.{zone}_pleasure", 0.0, 100.0)
    dev = zone_dev_effective(state, settings, zone)
    sens = zone_sensitivity_effective(state, settings, zone)
    return round(max(0.0, base * (0.4 + 0.8 * dev / 100.0) * sens), 2)


def zone_override(state: dict, zone: str) -> float | None:
    """面板手动设置的每次涨幅；None 表示跟随公式。"""
    row = (state.get("zones") or {}).get(zone)
    if not isinstance(row, dict):
        return None
    value = row.get("gain_override")
    if value is None:
        return None
    return round(max(0.0, util.safe_float(value, 0.0)), 2)


def zone_gain_effective(state: dict, settings: Settings, zone: str) -> float:
    override = zone_override(state, zone)
    return override if override is not None else zone_formula_gain(state, settings, zone)


def set_zone_gain(state: dict, settings: Settings, zone: str,
                  value: float | None) -> float:
    """面板改某个部位的每次涨幅；None = 恢复公式。返回生效值。"""
    row = state.setdefault("zones", {}).setdefault(
        zone, {"touches": 0, "total": 0.0, "last_at": 0.0})
    if value is None:
        row.pop("gain_override", None)
        return zone_formula_gain(state, settings, zone)
    row["gain_override"] = round(util.clamp(util.safe_float(value, 0.0), 0.0, 50.0), 2)
    return row["gain_override"]


def set_zone_dev(state: dict, settings: Settings, zone: str,
                 value: float | None) -> int:
    """面板改开发度（0–100）；None = 恢复跟随配置。返回生效值。"""
    row = state.setdefault("zones", {}).setdefault(
        zone, {"touches": 0, "total": 0.0, "last_at": 0.0})
    if value is None:
        row.pop("dev_override", None)
        return zone_dev(settings, zone)
    dev = int(util.clamp(util.safe_float(value, 0.0), 0.0, 100.0))
    row["dev_override"] = dev
    return dev


def zones_payload(settings: Settings, state: dict | None = None) -> list[dict]:
    rows = []
    for zone in ZONE_ORDER:
        if not settings.bool("zones.enabled"):
            continue
        enabled = zone_enabled_effective(state, settings, zone)
        if isinstance(state, dict):
            dev = zone_dev_effective(state, settings, zone)
            formula = zone_formula_gain(state, settings, zone)
            override = zone_override(state, zone)
        else:
            dev = zone_dev(settings, zone)
            formula = zone_gain(settings, zone)
            override = None
        row = (state.get("zones") or {}).get(zone) if isinstance(state, dict) else None
        rows.append({
            "key": zone,
            "label": ZONE_LABELS[zone],
            "enabled": enabled,
            "enabled_config": settings.bool(f"zones.{zone}_enabled"),
            "dev": dev,
            "dev_config": zone_dev(settings, zone),
            "dev_manual": bool(isinstance(row, dict) and row.get("dev_override") is not None),
            "dev_bonus": round(zone_dev_bonus(state, zone), 1),
            "sensitivity": zone_sensitivity_effective(state, settings, zone),
            "base_sensitivity": round(zone_sensitivity(settings, zone), 2),
            "sens_bonus": round(zone_sens_bonus(state, zone), 3),
            "base": round(settings.float(f"zones.{zone}_pleasure", 0.0, 100.0), 1),
            "gain": (override if override is not None else formula) if enabled else 0.0,
            "formula_gain": formula,
            "manual": override is not None,
        })
    return rows


def apply_touch(state: dict, settings: Settings, zone: str, times: int = 1,
                now: float | None = None) -> dict:
    """记一次（或几次）触碰：返回涨了多少、当前快感值。"""
    now = now or util.now_ts()
    times = max(1, min(20, int(times or 1)))
    from . import state as state_mod  # 避免循环导入

    craving = state_mod.edge_gain_multiplier(state, settings, now)
    gain = zone_gain_effective(state, settings, zone) * times * craving * body.pleasure_scale(settings, state)
    before = util.safe_float(state.get("pleasure"), 0.0)
    value = state_mod.add_pleasure(state, settings, gain, now=now)
    zones = state.setdefault("zones", {})
    row = zones.setdefault(zone, {"touches": 0, "total": 0.0, "last_at": 0.0})
    row["touches"] = util.safe_int(row.get("touches"), 0) + times
    row["total"] = round(util.safe_float(row.get("total"), 0.0) + gain, 2)
    row["last_at"] = now
    return {
        "zone": zone,
        "label": ZONE_LABELS.get(zone, zone),
        "times": times,
        "gain": round(gain, 2),
        "before": before,
        "value": value,
        "dev": zone_dev_effective(state, settings, zone),
        "sensitivity": round(zone_sensitivity_effective(state, settings, zone), 2),
    }


def zone_keywords(state: dict | None, zone: str) -> list[str]:
    rows = (state or {}).get("zone_keywords") if isinstance(state, dict) else None
    if isinstance(rows, dict):
        value = rows.get(zone)
        if isinstance(value, list) and value:
            return [str(word).strip() for word in value if str(word).strip()]
    return list(ZONE_KEYWORDS.get(zone, ()))


def zone_keywords_payload(settings: Settings, state: dict | None = None) -> list[dict]:
    rows = []
    for zone in ZONE_ORDER:
        default = list(ZONE_KEYWORDS.get(zone, ()))
        current = zone_keywords(state, zone)
        rows.append({
            "key": zone,
            "label": ZONE_LABELS.get(zone, zone),
            "default": default,
            "value": current,
            "custom": current != default,
        })
    return rows


def detect_zones(text: str, settings: Settings, state: dict | None = None) -> list[str]:
    """从一句话里认出提到了哪些敏感点（只取已启用的，最多 2 个）。"""
    body = (text or "").lower()
    if not body:
        return []
    found = []
    for zone in ZONE_ORDER:
        if not zone_enabled_effective(state, settings, zone):
            continue
        if any(word.lower() in body for word in zone_keywords(state, zone)):
            found.append(zone)
        if len(found) >= 2:
            break
    return found


def mode_pleasure(settings: Settings, mode: str) -> float:
    return round(settings.float(f"ejaculation.{mode}_pleasure", 0.0, 100.0), 2)


def mode_volume(settings: Settings) -> float:
    return round(settings.float("ejaculation.volume_ml", 0.0, 100.0), 2)


def uterus_capacity(settings: Settings) -> float:
    return round(settings.float("ejaculation.uterus_capacity_ml", 1.0, 500.0), 1)


UTERUS_TIERS = (
    (0.00, "empty", "空", "里面还是干净的"),
    (0.10, "trace", "一点", "里面刚被灌了一点，温温的"),
    (0.30, "some", "一些", "里面已经积了一些，动一下会感觉到"),
    (0.55, "much", "不少", "小腹有点发胀，里面装了不少"),
    (0.80, "near", "快满", "已经快装满了，稍微一动就往外溢"),
    (1.00, "full", "满", "满得发胀，再多就要溢出来了"),
)


def _after_leak_on(state: dict, settings: Settings) -> bool:
    override = state.get("uterus_after_leak_enabled")
    if isinstance(override, bool):
        return override
    return bool(settings.bool("ejaculation.uterus_after_leak_enabled"))


def _in_activity(state: dict, settings: Settings, now: float | None = None) -> bool:
    """正在活动里（亲密场景或日常小场景）就还不算"结束"。"""
    from . import state as state_mod  # 避免循环导入
    try:
        return bool(state_mod.scene_active(state, settings, now=now)) or \
            bool(state_mod.daily_active(state, settings, now=now))
    except Exception:
        return False


def uterus_volume(state: dict, settings: Settings, now: float | None = None) -> dict:
    """读当前子宫里的量（会先"结束后漏出"、再按小时慢慢吸收），返回量/容量/占比/档位。"""
    now = now or util.now_ts()
    capacity = uterus_capacity(settings)
    ml = max(0.0, util.safe_float(state.get("uterus_ml"), 0.0))
    ml_before = ml
    updated = util.safe_float(state.get("uterus_updated_at"), now)
    hours = max(0.0, (now - updated) / 3600.0)
    # 1) 活动结束以后：会渐渐漏出去，漏到设定水平就停（剩下的交给吸收）
    if ml > 0 and hours > 0 and _after_leak_on(state, settings) and not _in_activity(state, settings, now):
        rate = max(0.0, tuning.get(state, "uterus", "after_leak_per_hour",
                                   settings.float("ejaculation.uterus_after_leak_per_hour",
                                                  0.0, 100.0)))
        until = util.clamp(tuning.get(state, "uterus", "after_leak_until",
                                      settings.float("ejaculation.uterus_after_leak_until",
                                                     0.0, 100.0)), 0.0, 100.0)
        floor = capacity * until / 100.0
        if rate and ml > floor:
            ml = max(floor, ml - rate * hours)
    # 2) 原本的吸收：一直在跑
    leak = max(0.0, settings.float("ejaculation.uterus_leak_per_hour", 0.0, 100.0))
    leak *= body.absorption_multiplier(settings, state)
    if leak and hours > 0:
        ml = max(0.0, ml - leak * hours)
    state["uterus_ml"] = round(ml, 2)
    # 时钟回拨/传入更早的 now 时别把时间戳改小，否则下一次读会算出一大段流逝
    state["uterus_updated_at"] = max(updated, now)
    ratio = 0.0 if capacity <= 0 else ml / capacity
    tier = UTERUS_TIERS[0]
    for row in UTERUS_TIERS:
        if ratio >= row[0]:
            tier = row
    return {
        "ml": round(ml, 2),
        "capacity": capacity,
        "ratio": round(min(1.5, ratio), 3),
        "percent": round(min(130.0, ratio * 100), 1),
        "tier": tier[1],
        "tier_label": tier[2],
        "line": tier[3],
        "leaked": round(max(0.0, ml_before - ml), 2),
    }


def uterus_add(state: dict, settings: Settings, ml: float | None = None,
               now: float | None = None) -> dict:
    """把一次阴道内射的量加进去，返回加完后的状态。"""
    now = now or util.now_ts()
    info = uterus_volume(state, settings, now=now)
    amount = mode_volume(settings) if ml is None else max(0.0, util.safe_float(ml, 0.0))
    # 每次量上下浮动 ±35%，更像真的
    import random

    amount *= random.uniform(0.65, 1.35)
    capacity = info["capacity"]
    total = min(capacity * 1.5, info["ml"] + amount)
    state["uterus_ml"] = round(total, 2)
    state["uterus_updated_at"] = now
    after = uterus_volume(state, settings, now=now)
    after["added"] = round(amount, 2)
    return after


def clear_uterus(state: dict) -> None:
    state["uterus_ml"] = 0.0
    state["uterus_updated_at"] = util.now_ts()
