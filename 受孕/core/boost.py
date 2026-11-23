"""跨插件加成：PC 精力、鱼之心依恋/亲密/欲（魅魔用）。

PC 走数据库（pc_state）；鱼之心在同一个进程里，直接改它的内存状态再落盘，
比改 state.json 可靠（不会和它的心跳互相覆盖）。
"""

from __future__ import annotations

from . import pc_state, sources, util
from .settings import Settings


def boost_fish(context, settings: Settings, *, attachment: float = 0.0,
               intimacy: float = 0.0, desire: float = 0.0) -> dict:
    """给鱼之心的九维加成；返回 {ok, before/after}。"""
    if not settings.bool("succubus.fish_write_enabled"):
        return {"ok": False, "reason": "配置关闭"}
    star = sources.plugin_states(context).get("astrbot_plugin_fish_heart")
    inst = getattr(star, "star_cls", None)
    state = getattr(inst, "state", None)
    if not isinstance(state, dict):
        return {"ok": False, "reason": "鱼之心没加载或拿不到状态"}
    drives = state.setdefault("drives", {})
    applied = {}
    for key, delta in (("attachment", attachment), ("intimacy", intimacy)):
        if not delta:
            continue
        try:
            before = float(drives.get(key) or 0.0)
        except (TypeError, ValueError):
            before = 0.0
        after = max(0.0, min(100.0, before + float(delta)))
        drives[key] = after
        applied[key] = {"before": round(before, 2), "after": round(after, 2)}
    if desire and state.get("desire_awakened"):
        try:
            before = float(state.get("desire") or 0.0)
        except (TypeError, ValueError):
            before = 0.0
        after = max(0.0, min(100.0, before + float(desire)))
        state["desire"] = after
        applied["desire"] = {"before": round(before, 2), "after": round(after, 2)}
    save = getattr(inst, "_save_state", None)
    if callable(save):
        try:
            save()
        except Exception as error:
            return {"ok": False, "reason": f"保存失败：{error}", "applied": applied}
    return {"ok": True, "applied": applied}


def fish_state_of(context) -> dict | None:
    """拿鱼之心的内存状态（没加载 / 拿不到就 None）。"""
    star = sources.plugin_states(context).get("astrbot_plugin_fish_heart")
    inst = getattr(star, "star_cls", None)
    state = getattr(inst, "state", None)
    return state if isinstance(state, dict) else None


def fish_desire(context) -> float | None:
    """读鱼之心「欲」；没有这个插件 / 没觉醒就是 None。"""
    state = fish_state_of(context)
    if not isinstance(state, dict):
        return None
    try:
        return float(state.get("desire") or 0.0)
    except (TypeError, ValueError):
        return None


def save_fish(context) -> bool:
    star = sources.plugin_states(context).get("astrbot_plugin_fish_heart")
    inst = getattr(star, "star_cls", None)
    save = getattr(inst, "_save_state", None)
    if not callable(save):
        return False
    try:
        save()
        return True
    except Exception:
        return False


def boost_fish_desire(context, settings: Settings, amount: float,
                      enabled: bool | None = None) -> dict:
    """湿润度上涨时同步加一点鱼之心「欲」（单独一个开关，走 wetness.*）。"""
    if not amount:
        return {"ok": False, "reason": "数量为 0"}
    if enabled is None:
        enabled = bool(settings.bool("wetness.fish_write_enabled"))
    if not enabled:
        return {"ok": False, "reason": "配置关闭（wetness.fish_write_enabled）"}
    state = fish_state_of(context)
    if not isinstance(state, dict):
        return {"ok": False, "reason": "鱼之心没加载或拿不到状态"}
    if not state.get("desire_awakened"):
        return {"ok": False, "reason": "鱼之心还没觉醒欲望"}
    try:
        before = float(state.get("desire") or 0.0)
    except (TypeError, ValueError):
        before = 0.0
    after = max(0.0, min(100.0, before + float(amount)))
    state["desire"] = after
    save_fish(context)
    return {"ok": True, "before": round(before, 2), "after": round(after, 2),
            "added": round(after - before, 2)}


def boost_pc(settings: Settings, energy: int) -> dict:
    if not settings.bool("succubus.pc_write_enabled"):
        return {"ok": False, "reason": "配置关闭"}
    return pc_state.adjust_energy(settings, energy)


def boost_fish_blame(context, settings: Settings, amount: float) -> dict:
    """羞耻满溢时给鱼之心加一点「责怪」（它的 blame_pressure，会自己慢慢褪）。

    和 boost_fish 一样直接改它内存里的状态再落盘；只是不经过魅魔那组开关，
    而是用 mood.fish_write_enabled 单独控制。
    """
    if not amount:
        return {"ok": False, "reason": "数量为 0"}
    if not settings.bool("mood.fish_write_enabled"):
        return {"ok": False, "reason": "配置关闭（mood.fish_write_enabled）"}
    star = sources.plugin_states(context).get("astrbot_plugin_fish_heart")
    inst = getattr(star, "star_cls", None)
    state = getattr(inst, "state", None)
    if not isinstance(state, dict):
        return {"ok": False, "reason": "鱼之心没加载或拿不到状态"}
    current = state.get("blame_pressure")
    try:
        before = float(current or 0.0)
    except (TypeError, ValueError):
        before = 0.0
    after = max(0.0, min(100.0, before + float(amount)))
    state["blame_pressure"] = after
    # 它按 blame_noticed_ts 起算"多久没被哄"再褪；没记过就现在记一下
    if not state.get("blame_noticed_ts"):
        state["blame_noticed_ts"] = util.now_ts()
    save = getattr(inst, "_save_state", None)
    if callable(save):
        try:
            save()
        except Exception as error:
            return {"ok": False, "reason": f"保存失败：{error}",
                    "before": round(before, 2), "after": round(after, 2)}
    return {"ok": True, "before": round(before, 2), "after": round(after, 2),
            "added": round(after - before, 2)}
