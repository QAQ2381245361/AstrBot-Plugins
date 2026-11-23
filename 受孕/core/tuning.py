"""面板可调的数值覆盖（不改配置文件，存在 state 里）。

配置里的默认值还是 `_conf_schema.json` / DEFAULTS；面板上改过的值放这里，
下次启动还在。0 / 空表示没覆盖。
"""

from __future__ import annotations




def _box(state: dict, section: str) -> dict:
    if not isinstance(state, dict):
        state = {}
    root = state.setdefault("tuning", {})
    if not isinstance(root, dict):
        root = {}
        state["tuning"] = root
    box = root.get(section)
    if not isinstance(box, dict):
        box = {}
        root[section] = box
    return box


def get(state: dict, section: str, key: str, default: float) -> float:
    box = _box(state, section)
    value = box.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def raw(state: dict, section: str, key: str, default):
    box = _box(state, section)
    value = box.get(key)
    return default if value is None else value


def set_value(state: dict, section: str, key: str, value) -> None:
    _box(state, section)[key] = value


def clear(state: dict, section: str, key: str) -> None:
    _box(state, section).pop(key, None)
