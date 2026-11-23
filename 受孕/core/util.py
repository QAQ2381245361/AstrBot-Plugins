"""小工具：安全读写 JSON、日期运算、数值裁剪。

全部只用标准库，方便自检脚本单独 import。
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import date, datetime
from pathlib import Path

TZ_NAME = "Asia/Shanghai"


# ---------------------------------------------------------------- 数值

def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    if value is None or not math.isfinite(float(value)):
        return lo
    return max(lo, min(hi, float(value)))


def safe_float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def safe_int(value, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def fmt_value(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


# ---------------------------------------------------------------- JSON

def read_json(path, default=None):
    """读 JSON；文件不存在/坏掉都返回 default，绝不抛异常。

    用 utf-8-sig 读：AstrBot 保存插件配置时会带 UTF-8 BOM，
    用 utf-8 直接 json.load 会报 "Unexpected UTF-8 BOM"。
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data
    except (OSError, ValueError, UnicodeDecodeError):
        return default


def read_json_text(raw, default=None):
    """解析一段 JSON 字符串（数据库里存的那种）。"""
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def write_json_atomic(path, data) -> bool:
    """先写 .tmp 再替换，避免被别的进程读到半个文件。"""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- 时间

def now_ts() -> float:
    return time.time()


def today() -> date:
    return datetime.now().date()


def ts_to_date(value, fallback: date | None = None) -> date:
    """把时间戳/ISO 字符串转成 date。"""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(float(value)).date()
    text = str(value or "").strip()
    if text:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
    return fallback or today()


def parse_date(value) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def add_months(value: date, months: int) -> date:
    """按自然月加，日超出目标月天数就压到月末（1-31 → 2-28）。"""
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = value.day
    while day > 1:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, 1)


def days_between(start, end) -> int:
    return max(0, (ts_to_date(end) - ts_to_date(start)).days)


def fmt_gap(seconds: float) -> str:
    minutes = max(0, int(round(seconds / 60)))
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} 小时" + (f" {rest} 分" if rest else "")
    days, hours = divmod(hours, 24)
    return f"{days} 天" + (f" {hours} 小时" if hours else "")


def fmt_date(value) -> str:
    target = ts_to_date(value, fallback=None) if value else None
    return target.isoformat() if target else "—"
