"""受孕活动 / 突然被弄 → 记忆插件的桥（尽量软，拿不到就跳过）。

两个记忆插件都在按"对话消息"记东西：
- 蔗糖的记忆中枢（astrbot_plugin_sugarmemory）：L3 存原话、L2 由总结提炼；
  另有一个主动发言联动凭证 `outbound_bridge.json`，发送前把标签挂在
  `message_chain._sugarmemory_bridge` 上，它就不会把这条当成回声；
  面板里还有一条手动写 L2 的通道（`store.add_l2_manual`）。
- 天使之魂（astrbot_plugin_angel_memory）：有自己的 `angel_remember` 工具和内部服务，
  没有稳定的外部写入 API —— 这里只做检测，不硬写。

所以：面板点按钮本身不产生消息，不会被记忆；她说的那句话、以及我们主动发的那条，
才会进记忆。`memory.write_events`（默认关）打开后，这里会额外写一条 L2 事实。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import sources, util
from .settings import Settings

SUGAR = "astrbot_plugin_sugarmemory"
ANGEL = "astrbot_plugin_angel_memory"
BRIDGE_FILE = "outbound_bridge.json"


def _instance(context, key: str):
    try:
        star = sources.plugin_states(context).get(key)
    except Exception:
        return None
    if star is None:
        return None
    return getattr(star, "star_cls", None)


def available(context) -> dict:
    """两个记忆插件在不在；热重载后根据元数据/模块路径兜底识别。"""
    states = sources.plugin_states(context) if context is not None else {}
    angel = states.get(ANGEL)
    angel_ok = bool(angel) and (
        getattr(angel, "activated", True)
        or getattr(angel, "star_cls", None) is not None)
    return {"sugarmemory": _instance(context, SUGAR) is not None,
            "angel": angel_ok}


def bridge_path(state_path) -> Path | None:
    """data/plugin_data/<我们>/state.json → <同目录>/astrbot_plugin_sugarmemory/outbound_bridge.json。"""
    try:
        base = Path(str(state_path)).parent.parent
    except Exception:
        return None
    return base / SUGAR / BRIDGE_FILE


def bridge_tag(state_path) -> dict | None:
    """读它的联动凭证；没开/没 token 就 None。"""
    path = bridge_path(state_path)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("enabled"):
        return None
    token = str(data.get("token") or "").strip()
    if not token:
        return None
    return {"token": token}


def attach_bridge(chain, tag: dict | None, *, label: str, cause: str) -> bool:
    """把标签挂到消息链上（它只认这个属性名）。"""
    if not tag or chain is None:
        return False
    try:
        setattr(chain, "_sugarmemory_bridge",
                {"token": tag.get("token"), "label": str(label or "")[:64],
                 "cause": str(cause or "")[:64]})
        return True
    except Exception:
        return False


def write_enabled(settings: Settings) -> bool:
    return bool(settings.bool("memory.write_events"))


def subject(settings: Settings) -> str:
    return str(settings.str("memory.subject") or "我").strip()[:40] or "我"


def min_seconds(settings: Settings) -> int:
    return max(0, settings.int("memory.min_minutes", 0, 1440)) * 60


def event_name(settings: Settings) -> str:
    """她给这件事起的名字；没配就空着（不硬写系统词）。"""
    value = str(settings.str("memory.event_name") or "").strip()[:40]
    while value.startswith("的"):
        value = value[1:].strip()
    return value


def activity_value(settings: Settings, *, mode_label: str = "") -> str:
    """记忆里写的措辞：优先用她的叫法；没配就用中性说法，绝不写系统词。"""
    name = event_name(settings)
    if name:
        return f"和主人的{name}"[:200]
    if mode_label:
        return f"和主人亲密了一次（{mode_label}）"[:200]
    return "和主人亲密了一次"


def write_child_fact(context, settings: Settings, *, value: str,
                     reason: str = "受孕插件") -> dict:
    """把孩子出生/成年的信息写进蔗糖记忆；没有接口就跳过。"""
    if not settings.bool("memory.write_children"):
        return {"ok": False, "reason": "配置关闭（memory.write_children）"}
    inst = _instance(context, SUGAR)
    store = getattr(inst, "store", None) if inst is not None else None
    if store is None or not hasattr(store, "add_l2_manual"):
        return {"ok": False, "reason": "蔗糖的记忆中枢没加载或没有写入接口"}
    text = str(value or "").strip()[:200]
    if not text:
        return {"ok": False, "reason": "内容为空"}
    try:
        fact_id = store.add_l2_manual(subject=subject(settings),
                                      predicate="孩子",
                                      value=text, reason=reason)
    except Exception as error:
        return {"ok": False, "reason": str(error)}
    return {"ok": True, "id": fact_id, "value": text}


def write_fact(context, settings: Settings, *, value: str, reason: str = "受孕插件",
               now: float | None = None, state: dict | None = None) -> dict:
    """往蔗糖的记忆中枢写一条 L2 事实（受 memory.write_events 与节流控制）。"""
    now = now or util.now_ts()
    if not write_enabled(settings):
        return {"ok": False, "reason": "配置关闭（memory.write_events）"}
    if state is not None:
        last = util.safe_float(state.get("memory_written_at"), 0.0)
        if last and now - last < min_seconds(settings):
            return {"ok": False, "reason": "太频繁，先不写"}
    inst = _instance(context, SUGAR)
    store = getattr(inst, "store", None) if inst is not None else None
    if store is None or not hasattr(store, "add_l2_manual"):
        return {"ok": False, "reason": "蔗糖的记忆中枢没加载或没有写入接口"}
    text = str(value or "").strip()[:200]
    if not text:
        return {"ok": False, "reason": "内容为空"}
    try:
        fact_id = store.add_l2_manual(subject=subject(settings),
                                      predicate="和主人的亲密活动",
                                      value=text, reason=reason)
    except Exception as error:
        return {"ok": False, "reason": str(error)}
    if state is not None:
        state["memory_written_at"] = now
    return {"ok": True, "id": fact_id, "value": text}
