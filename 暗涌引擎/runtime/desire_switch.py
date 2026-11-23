"""欲望归属开关：谁的「欲」说了算。

三种模式：
    longing  默认：暗涌全权（请先关掉「鱼的心」卡片）
    split    分工：鱼之心管九维，暗涌管欲
    fish     只有鱼之心（等价于把「暗涌」卡片关掉）

用法：
    python desire_switch.py           查看当前
    python desire_switch.py 1         切换到：只用心的心
    python desire_switch.py 2         切换到：只用暗涌
    python desire_switch.py 3         切换到：两个都开
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SWITCH = Path(r"C:\DeepSeek\desire_switch.json")
MODES = {"1": ("longing", "默认：暗涌全权"), "2": ("split", "分工：鱼之心九维 + 暗涌欲望"), "3": ("fish", "只有鱼之心（等于关掉暗涌卡片）")}
NAMES = {"longing": "默认：暗涌全权", "split": "分工：鱼之心九维 + 暗涌欲望", "fish": "只有鱼之心"}


def read_owner() -> str:
    try:
        return str(json.loads(SWITCH.read_text(encoding="utf-8")).get("owner") or "fish")
    except Exception:
        return "fish"


def write_owner(owner: str) -> None:
    payload = {"owner": owner, "note": "longing=暗涌全权；split=鱼之心九维+暗涌欲望；fish=只有鱼之心"}
    tmp = SWITCH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SWITCH)


def main() -> int:
    current = read_owner()
    if len(sys.argv) < 2:
        print(f"当前：{current}（{NAMES.get(current, current)}）")
        print("1 = 默认（暗涌全权）    2 = 分工（鱼之心九维 + 暗涌欲望）    3 = 只有鱼之心")
        return 0
    arg = str(sys.argv[1]).strip()
    if arg in MODES:
        owner, label = MODES[arg]
    elif arg in NAMES:
        owner, label = arg, NAMES[arg]
    else:
        print("参数无效：用 1 / 2 / 3")
        return 1
    write_owner(owner)
    print(f"已切换：{owner}（{label}）")
    print("重启 AstrBot 后生效（鱼之心与暗涌都读这个文件）。")
    if owner == "both":
        print("提醒：这一档两套欲望会同时注入，只适合短暂对比。")
    if owner == "split":
        print("提示：想「只用暗涌」就把插件页里的『鱼的心』整个关掉，这一档仍是分工。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
