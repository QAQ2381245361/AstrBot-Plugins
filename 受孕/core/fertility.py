"""受孕概率模型：把几个来源的数值折成一个百分比，并给出可解释的分解。

公式（除生理期基准外都是倍率相乘，方便在 /受孕状态 里逐项核对）：

    P = 生理期基准概率（5% ~ 40%）
        × 鱼之心「欲」系数  1 + w × 欲/100
        × 暗涌 lust 系数    1 + w × lust/100
        × 快感系数          1 + w × 快感/100
        × 高潮次数系数      1 + w × min(次数, 封顶)/封顶
        × 体内/体外系数
        × 高潮时被射系数    （高潮后 N 分钟内 + 体内）

最后按 max_probability 封顶。所有系数都会回传，面板/命令里能看见
"这一次为什么是这个概率"，而不是一个黑箱数字。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import util
from .settings import Settings

PHASE_NAMES = {
    "menstrual": "月经期",
    "follicular": "卵泡期",
    "pre_ovulation": "排卵前期",
    "ovulation": "排卵期",
    "luteal": "黄体期",
    "pms": "经前期",
    "recovery": "经后恢复期",
    "unknown": "未知",
    "paused": "孕期暂停",
}


@dataclass
class Probability:
    probability: float = 0.0                     # 0–100 的百分数
    factors: dict = field(default_factory=dict)  # 每一项：基准概率/倍率
    phase: str = "unknown"
    notes: list = field(default_factory=list)    # 人话解释

    @property
    def ratio(self) -> float:
        """0–1 的小数，掷骰子用。"""
        return self.probability / 100.0

    @property
    def tier(self) -> str:
        if self.probability <= 0:
            return "无"
        if self.probability < 8:
            return "很低"
        if self.probability < 20:
            return "偏低"
        if self.probability < 40:
            return "中等"
        if self.probability < 60:
            return "较高"
        return "很高"


def compute(settings: Settings, *, phase: str, fish_factor: float, dark_factor: float,
            pleasure: float, orgasms: int, inside: bool, orgasm_recent: bool) -> Probability:
    max_p = settings.float("conception.max_probability", 0.0, 100.0)
    phase_table = settings.phase_probability()

    phase_key = str(phase or "unknown").lower()
    if phase_key not in phase_table:
        phase_key = "unknown"
    phase_base = phase_table.get(phase_key, 15.0)

    pleasure_factor = 1.0 + settings.float("conception.pleasure_weight", 0.0, 5.0) * \
        util.clamp(pleasure, 0.0, 100.0) / 100.0

    cap = max(1, settings.int("conception.orgasm_count_cap", 1, 20))
    counted = min(max(0, int(orgasms)), cap)
    orgasm_factor = 1.0 + settings.float("conception.orgasm_count_weight", 0.0, 5.0) * counted / cap

    inside_factor = settings.float("conception.inside_scale", 0.0, 5.0) if inside else \
        settings.float("conception.outside_scale", 0.0, 5.0)

    now_factor = 1.0
    if inside and orgasm_recent:
        now_factor = settings.float("conception.orgasm_now_multiplier", 1.0, 10.0)

    total = phase_base / 100.0
    factors = {
        "phase": phase_base,
        "fish": fish_factor,
        "dark": dark_factor,
        "pleasure": pleasure_factor,
        "orgasm": orgasm_factor,
        "inside": inside_factor,
        "orgasm_now": now_factor,
    }
    for key in ("fish", "dark", "pleasure", "orgasm", "inside", "orgasm_now"):
        total *= factors[key]

    probability = util.clamp(total * 100.0, 0.0, max_p)

    notes = []
    if not inside:
        notes.append("体外，基本不会受孕")
    if inside and orgasm_recent:
        notes.append("高潮后短时间内被射，概率加成")
    if phase_key in ("pre_ovulation", "ovulation"):
        notes.append("处于易孕期")
    if phase_key in ("menstrual", "pms"):
        notes.append("处于不易孕期")

    return Probability(probability=probability, factors=factors, phase=phase_key, notes=notes)


def describe(p: Probability, show_tier: bool = True) -> list[str]:
    """给命令用的逐项说明。"""
    f = p.factors
    label = PHASE_NAMES.get(p.phase, p.phase)
    lines = [
        f"生理期基准（{label}）：{f.get('phase', 0):.1f}%",
        f"鱼之心「欲」：×{f.get('fish', 1):.2f}",
        f"暗涌 lust：×{f.get('dark', 1):.2f}",
        f"快感：×{f.get('pleasure', 1):.2f}",
        f"高潮次数：×{f.get('orgasm', 1):.2f}",
        f"体内/体外：×{f.get('inside', 1):.2f}",
        f"高潮时被射：×{f.get('orgasm_now', 1):.2f}",
        f"→ 本次受孕概率：{p.probability:.1f}%" + (f"（{p.tier}）" if show_tier else ""),
    ]
    if p.notes:
        lines.append("说明：" + "；".join(p.notes))
    return lines
