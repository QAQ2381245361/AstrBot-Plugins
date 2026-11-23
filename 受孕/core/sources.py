"""读取别的插件的数值——只读，绝不写它们的数据。

- 鱼之心（astrbot_plugin_fish_heart）：state.json 里的 desire（0–100 的「欲」），
  以及成人层是否打开（adult_consent_standing / adult_consent_until /
  adult_scene_consent_until / adult_paused / sage_until）。
- 暗涌（astrbot_plugin_longing + astrbot_plugin_desire_owner）：
  引擎状态文件里的 lust（0–100），以及引擎是否真的在跑。

设计约定：
- 读不到就是 None，不猜、不用旧值硬撑。
- 是否"已启用"由两部分共同决定：插件有没有被 AstrBot 激活（runtime），
  以及它自己的开关/共享开关文件（data）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import util
from .settings import Settings

# 鱼之心 state.json 里跟「欲 / 成人层」有关的字段
FISH_DESIRE = "desire"
FISH_DESIRE_AWAKENED = "desire_awakened"
FISH_ADULT_STANDING = "adult_consent_standing"
FISH_ADULT_UNTIL = "adult_consent_until"
FISH_SCENE_UNTIL = "adult_scene_consent_until"
FISH_ADULT_PAUSED = "adult_paused"
FISH_SAGE_UNTIL = "sage_until"
FISH_SCENE_INTIMATE = "adult_scene_intimate"


@dataclass
class FishSnapshot:
    """鱼之心当前的可见状态。"""

    available: bool = False
    activated: bool = False          # AstrBot 里插件是否启用
    enabled: bool = False            # 插件自己的总开关
    desire: float = 0.0
    desire_awakened: bool = False
    adult_enabled: bool = False      # desire.adult_enabled（成人向总开关）
    adult_consent: bool = False
    adult_scene: bool = False
    adult_paused: bool = False
    sage: bool = False
    scene_intimate: bool = False
    mode: str = ""
    drives: dict = field(default_factory=dict)
    blame: float = 0.0               # 责怪（blame_pressure，0–100）
    updated_at: float = 0.0
    reason: str = ""

    @property
    def usable(self) -> bool:
        """「欲」这个数值能不能用：插件在跑、开关打开、文件读到了。"""
        return self.available and self.activated and self.enabled

    @property
    def adult_allowed(self) -> bool:
        """成人层总开关是不是开着（面板上那个"允许成人向身体层"）。"""
        return bool(self.activated and self.enabled and self.adult_enabled)

    @property
    def adult_open(self) -> bool:
        """成人层是不是"此刻已经打开"（有同意/场景、没暂停、不在贤者期）。"""
        if not self.adult_allowed:
            return False
        if self.adult_paused or self.sage:
            return False
        return bool(self.adult_consent or self.adult_scene)


@dataclass
class DarkSnapshot:
    """暗涌当前状态。"""

    available: bool = False
    enabled: bool = False             # 归属开关 + 引擎在跑
    engine_want: bool = False
    fresh: bool = False
    lust: float = 0.0
    dims: dict = field(default_factory=dict)
    paused: bool = False
    owner: str = "fish"
    updated_at: float = 0.0
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.available and self.enabled and self.fresh and not self.paused


# ---------------------------------------------------------------- 通用

def plugin_states(context) -> dict[str, object]:
    """把 AstrBot 已加载插件列成 {目录名: StarMetadata}。"""
    result = {}
    try:
        stars = context.get_all_stars() if context is not None else []
    except Exception:
        return result
    for star in stars or []:
        names = [getattr(star, "root_dir_name", None), getattr(star, "name", None),
                 getattr(star, "display_name", None), getattr(star, "module_path", None)]
        for name in names:
            if name:
                result[str(name)] = star
                break
        # 目录名/模块路径/显示名都留一份，热重载后元数据字段可能变化
        for name in names:
            if name:
                result.setdefault(str(name), star)
    return result


def plugin_activated(context, plugin_id: str) -> bool:
    star = plugin_states(context).get(plugin_id)
    return bool(getattr(star, "activated", False))


def desire_owner(settings: Settings) -> str:
    """谁的「欲」说了算：fish / longing / split / both。

    先看共享开关文件（鱼之心和暗涌都读它），读不到再看归属卡片的配置。
    """
    switch_path = Path(settings.str("sources.desire_switch"))
    data = util.read_json(switch_path, None)
    if isinstance(data, dict):
        value = str(data.get("owner") or "").strip().lower()
        if value in ("fish", "longing", "split", "both"):
            return value
    config_path = Path(settings.str("sources.fish_heart_config")).parent / "astrbot_plugin_desire_owner_config.json"
    data = util.read_json(config_path, None)
    if isinstance(data, dict):
        value = str(data.get("owner") or "").strip().lower()
        if value in ("fish", "longing", "split", "both"):
            return value
    return "fish"


# ---------------------------------------------------------------- 鱼之心

def read_fish_heart(settings: Settings, context=None) -> FishSnapshot:
    snap = FishSnapshot()
    state_path = Path(settings.str("sources.fish_heart_state"))
    config_path = Path(settings.str("sources.fish_heart_config"))

    snap.activated = plugin_activated(context, "astrbot_plugin_fish_heart")

    config = util.read_json(config_path, None)
    snap.enabled = bool((config or {}).get("enabled", True)) if isinstance(config, dict) else False
    desire_cfg = (config or {}).get("desire") if isinstance(config, dict) else None
    snap.adult_enabled = bool((desire_cfg or {}).get("adult_enabled", False)) \
        if isinstance(desire_cfg, dict) else False

    state = util.read_json(state_path, None)
    if not isinstance(state, dict):
        snap.reason = "读不到鱼之心 state.json"
        return snap

    snap.available = True
    snap.desire = util.clamp(util.safe_float(state.get(FISH_DESIRE), 0.0), 0.0, 100.0)
    snap.desire_awakened = bool(state.get(FISH_DESIRE_AWAKENED))
    snap.adult_paused = bool(state.get(FISH_ADULT_PAUSED))
    snap.scene_intimate = bool(state.get(FISH_SCENE_INTIMATE))
    now = time.time()
    snap.adult_consent = bool(state.get(FISH_ADULT_STANDING)) or \
        util.safe_float(state.get(FISH_ADULT_UNTIL), 0.0) > now
    snap.adult_scene = util.safe_float(state.get(FISH_SCENE_UNTIL), 0.0) > now
    snap.sage = util.safe_float(state.get(FISH_SAGE_UNTIL), 0.0) > now
    snap.mode = str(state.get("mode") or "")
    drives = state.get("drives")
    snap.drives = drives if isinstance(drives, dict) else {}
    snap.blame = util.clamp(util.safe_float(state.get("blame_pressure"), 0.0), 0.0, 100.0)
    snap.updated_at = util.safe_float(state.get("last_tick"), 0.0)
    return snap


def fish_stay_up(settings: Settings) -> dict:
    """鱼之心今晚是否熬夜；它自己的 sleep.stay_up_enabled 关掉时不算。"""
    state_path = Path(settings.str("sources.fish_heart_state"))
    config_path = Path(settings.str("sources.fish_heart_config"))
    state = util.read_json(state_path, None)
    config = util.read_json(config_path, None) or {}
    sleep = config.get("sleep") if isinstance(config, dict) else {}
    sleep = sleep if isinstance(sleep, dict) else {}
    enabled = bool(sleep.get("enabled", True)) and bool(
        sleep.get("stay_up_enabled", True))
    chance = util.clamp(util.safe_float(sleep.get("stay_up_chance"), 0.2), 0.0, 1.0)
    stay = bool(isinstance(state, dict) and state.get("sleep_stay_up"))
    return {"enabled": enabled, "stay_up": bool(enabled and stay),
            "chance": chance}


def fish_desire_factor(settings: Settings, snap: FishSnapshot) -> tuple[float, str]:
    """「欲」对受孕率的倍率。没启用/没解锁就返回 1.0。"""
    if not snap.usable:
        return 1.0, "鱼之心未启用"
    if not snap.desire_awakened:
        return 1.0, "鱼之心「欲」未解锁"
    weight = settings.float("conception.fish_desire_weight", 0.0, 5.0)
    factor = 1.0 + weight * snap.desire / 100.0
    return factor, f"欲 {snap.desire:.0f} → ×{factor:.2f}"


# ---------------------------------------------------------------- 暗涌

def read_dark(settings: Settings) -> DarkSnapshot:
    snap = DarkSnapshot()
    state_path = Path(settings.str("sources.dark_state"))
    engine_path = Path(settings.str("sources.dark_engine_state"))

    engine = util.read_json(engine_path, None)
    if isinstance(engine, dict):
        snap.engine_want = bool(engine.get("want"))

    snap.owner = desire_owner(settings)

    state = util.read_json(state_path, None)
    if not isinstance(state, dict):
        snap.reason = "读不到暗涌状态文件"
        return snap

    snap.available = True
    snap.lust = util.clamp(util.safe_float(state.get("lust"), 0.0), 0.0, 100.0)
    dims = {key: util.safe_float(state.get(key), 0.0) for key in
            ("lust", "lewd", "possess", "shame", "resist", "fatigue", "affection")}
    snap.dims = dims
    updated_ms = util.safe_float(state.get("updatedAt"), 0.0)
    snap.updated_at = updated_ms / 1000.0 if updated_ms > 1e12 else updated_ms
    max_age = settings.int("sources.dark_max_age_minutes", 1, 1440) * 60
    snap.fresh = bool(snap.updated_at) and (time.time() - snap.updated_at) <= max_age
    paused_until = util.safe_float(state.get("pausedUntil"), 0.0)
    snap.paused = paused_until > time.time() * 1000 if paused_until > 1e12 else paused_until > time.time()
    # 归属：fish 表示暗涌让位给鱼之心，不算"已启用"
    owned = snap.owner in ("longing", "split", "both")
    snap.enabled = bool(owned and (snap.engine_want or snap.fresh))
    if not owned:
        snap.reason = f"欲望归属为 {snap.owner}，暗涌未接管"
    elif not snap.fresh:
        snap.reason = "暗涌状态文件过期（引擎没在跑）"
    return snap


def dark_lust_factor(settings: Settings, snap: DarkSnapshot) -> tuple[float, str]:
    if not snap.usable:
        return 1.0, snap.reason or "暗涌未启用"
    weight = settings.float("conception.dark_lust_weight", 0.0, 5.0)
    factor = 1.0 + weight * snap.lust / 100.0
    return factor, f"暗涌 lust {snap.lust:.0f} → ×{factor:.2f}"


# ---------------------------------------------------------------- 汇总

def read_all(settings: Settings, context=None) -> dict:
    """一次读齐，注入和判定共用，避免一轮里读两次文件。"""
    fish = read_fish_heart(settings, context)
    dark = read_dark(settings)
    return {
        "fish": fish,
        "dark": dark,
        "owner": dark.owner,
        "fish_factor": fish_desire_factor(settings, fish),
        "dark_factor": dark_lust_factor(settings, dark),
    }


def adult_gate(settings: Settings, sources: dict) -> tuple[bool, str]:
    """成人层是否可以参与。

    默认按鱼之心的**总开关**判断（面板上「允许成人向身体层」打开就算允许）；
    鱼之心自己那套"同意/场景/欲≥60"是它的身体层前置条件，不拿来卡受孕插件。
    想更严可以把 adult.fish_gate_mode 设成 scene：那样必须它自己有同意或场景。
    鱼之心没启用/没开成人向时，允许用本插件自己的「/受孕同意」临时授权。
    """
    if not settings.bool("adult_required"):
        return True, "未设成人层门槛"
    fish = sources.get("fish")
    if isinstance(fish, FishSnapshot) and fish.usable and fish.adult_enabled:
        mode = (settings.str("adult.fish_gate_mode") or "switch").lower()
        if mode == "scene" and not fish.adult_open:
            return False, "鱼之心成人层已允许，但还没同意或进场景"
        return True, "鱼之心成人层已允许（总开关开）"
    return False, "鱼之心成人层总开关未开"


def describe_sources(sources: dict) -> list[str]:
    """给 /受孕状态 用的几行说明。"""
    fish = sources.get("fish")
    dark = sources.get("dark")
    lines = []
    if isinstance(fish, FishSnapshot):
        if fish.usable:
            if not fish.adult_enabled:
                state = "总开关关"
            elif fish.adult_open:
                state = "场景中"
            else:
                state = "已允许（总开关开）"
            lines.append(
                f"鱼之心：启用｜欲 {fish.desire:.1f}（解锁={'是' if fish.desire_awakened else '否'}）"
                f"｜成人层 {state}")
        else:
            why = fish.reason or ("插件未激活" if not fish.activated else "开关关闭")
            lines.append(f"鱼之心：未启用（{why}）")
    if isinstance(dark, DarkSnapshot):
        if dark.usable:
            lines.append(f"暗涌：启用｜lust {dark.lust:.1f}｜归属 {dark.owner}")
        else:
            lines.append(f"暗涌：未启用（{dark.reason or '未接管'}）")
    return lines


def dump_for_debug(sources: dict) -> str:
    try:
        return json.dumps(sources, ensure_ascii=False, default=str)[:400]
    except Exception:
        return ""
