"""插入相关的附加效果：干燥惩罚、保持不动、内射加湿润。

- 干燥：湿润度低于 `dry.wet_below` 时用生殖器插进阴道/G点/子宫颈/子宫，会掉快感、掉忍耐、
  只多一点点湿润，并有疼痛提示；抹过润滑油就不算干；
- 保持：用生殖器插着以后 `hold.after_seconds` 秒没再动，就按"保持插入不抽插"写；
- 内射：射进去会额外加湿润（`inner.wet_gain`），并有单独的提示词。
"""

from __future__ import annotations

from . import endurance, lube, prompts, util, wetness
from .settings import Settings

DRY_ZONES = ("vagina", "gspot", "cervix", "uterus")
HOLD_ZONES = ("vagina", "gspot", "cervix")
DEFAULT = {"zone": "", "at": 0.0, "dry_zone": "", "dry_at": 0.0, "inner_zone": "", "inner_at": 0.0}


def data(state: dict) -> dict:
    value = state.get("insert_extra")
    if not isinstance(value, dict):
        value = dict(DEFAULT)
        state["insert_extra"] = value
    for key, default in DEFAULT.items():
        value.setdefault(key, default)
    return value


# ---------------------------------------------------------------- 干燥

def dry_enabled(settings: Settings) -> bool:
    return settings.bool("dry.enabled")


def dry_below(settings: Settings) -> float:
    return settings.float("dry.wet_below", 0.0, 100.0)


def dry_touch(state: dict, settings: Settings, zone: str, method: str,
              now: float | None = None) -> dict:
    now = now or util.now_ts()
    if not dry_enabled(settings) or zone not in DRY_ZONES or method != "penis":
        return {}
    if lube.active(state, settings, now=now):
        return {}
    wet = wetness.value_of(state, settings, now=now)
    if wet >= dry_below(settings):
        return {}
    state["pleasure"] = max(0.0, util.safe_float(state.get("pleasure"), 0.0)
                            - settings.float("dry.pleasure_drop", 0.0, 100.0))
    endurance.add_extra(state, settings, -settings.float("dry.endurance_drop", 0.0, 100.0))
    wetness.gain(state, settings, extra=settings.float("dry.wet_gain", 0.0, 100.0), now=now)
    row = data(state)
    row.update({"dry_zone": zone, "dry_at": now})
    return {"applied": True, "zone": zone,
            "prompt": prompts.text(state, "dry", zone),
            "wet": round(wet, 1)}


def dry_block(state: dict, settings: Settings, now: float | None = None) -> str:
    if not dry_enabled(settings):
        return ""
    now = now or util.now_ts()
    row = data(state)
    zone = str(row.get("dry_zone") or "")
    at = util.safe_float(row.get("dry_at"), 0.0)
    minutes = max(1, settings.int("dry.minutes", 1, 240))
    if not zone or not at or now - at > minutes * 60:
        return ""
    line = prompts.text(state, "dry", zone)
    return f"【阴道未足够湿润】\n- {line}\n（太干，进去会疼；提醒他可以先润滑。）"


# ---------------------------------------------------------------- 保持不动

def hold_note(state: dict, zone: str, method: str, now: float | None = None) -> None:
    if zone not in HOLD_ZONES or method != "penis":
        return
    row = data(state)
    row.update({"zone": zone, "at": now or util.now_ts()})


def hold_block(state: dict, settings: Settings, *, in_scene: bool,
               now: float | None = None) -> str:
    if not in_scene:
        return ""
    now = now or util.now_ts()
    row = data(state)
    zone = str(row.get("zone") or "")
    at = util.safe_float(row.get("at"), 0.0)
    if not zone or not at:
        return ""
    idle = now - at
    if idle < max(0, settings.int("hold.after_seconds", 0, 600)):
        return ""
    if idle > max(1, settings.int("hold.minutes", 1, 240)) * 60:
        return ""
    line = prompts.text(state, "hold", zone)
    if not line:
        return ""
    return f"【保持插入】\n- {line}\n（现在没有在抽插，写被填满/悬着的感觉，别写抽送。）"


# ---------------------------------------------------------------- 内射加湿

def inner(state: dict, settings: Settings, zone: str, now: float | None = None) -> dict:
    now = now or util.now_ts()
    gain = settings.float("inner.wet_gain", 0.0, 100.0)
    before = wetness.value_of(state, settings, now=now)
    after = wetness.gain(state, settings, extra=gain, now=now) if gain > 0 else before
    row = data(state)
    row.update({"inner_zone": zone, "inner_at": now})
    return {"zone": zone, "wet_gain": round(after - before, 2),
            "line": prompts.text(state, "inner", "wet")}


def inner_block(state: dict, settings: Settings, now: float | None = None) -> str:
    now = now or util.now_ts()
    row = data(state)
    zone = str(row.get("inner_zone") or "")
    at = util.safe_float(row.get("inner_at"), 0.0)
    minutes = max(1, settings.int("inner.minutes", 1, 240))
    if not zone or not at or now - at > minutes * 60:
        return ""
    line = prompts.text(state, "inner", "wet")
    return f"【内射后的湿润】\n- {line}" if line else ""
