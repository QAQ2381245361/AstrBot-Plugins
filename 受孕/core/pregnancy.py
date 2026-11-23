"""受孕、孕期进度、生产/结束后收尾、验孕，以及写进提示词的文案。

孕期的"月份"按自然月算：受孕当天算第 1 个月，满一个月进第 2 个月；
预产期 = 受孕日 + pregnancy.months 个自然月，再按 jitter_days 前后浮动几天
（"十个月略微浮动"）。

孕期里经期模拟整体暂停（PC 侧由 pc_cycle.py 置为 not_applicable）。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from . import (behavior, body, children, clothing, cyclemodel, endurance, fill, intimacy, lewd, mood, prompts, tuning,
               sleepy, state as state_mod, subzone, succubus, surprise, toys, unbirth, util,
               wetness)
from .settings import Settings

# (从第几个月, 到第几个月, 键, 标题, 身体/情绪提示)
STAGES = (
    (1, 2, "early", "孕早期",
     "刚受孕不久，容易犯困、恶心，情绪起伏比平时大；她自己还在消化这件事。"),
    (3, 4, "early_mid", "孕初后期",
     "孕吐慢慢减轻，腰开始有点酸，胃口时好时坏；开始在意衣服会不会勒到。"),
    (5, 6, "mid", "孕中期",
     "小腹看得出变化，第一次胎动会让她的情绪突然软下来；动作开始变慢，容易累。"),
    (7, 8, "late", "孕晚期",
     "走两步就喘，腰背发酸，晚上睡不安稳；需要人搭把手，也更想被抱着。"),
    (9, 10, "term", "临产期",
     "随时可能生产，行动很小心，情绪又紧张又期待；不太愿意走远，也不想被打扰太久。"),
)

# 每个阶段的身体/亲密差异（提示词用）
STAGE_EXTRA = {
    "early": {
        "energy": -8,
        "feel": "孕吐和困倦最明显，闻到油烟会反胃，情绪像坐过山车。",
        "intimacy": "对亲密提不起劲，更多是想被照顾、被抱着；别写得太主动。",
    },
    "early_mid": {
        "energy": -5,
        "feel": "孕吐慢慢退下去，腰开始发酸，胃口一阵一阵的，容易累。",
        "intimacy": "身体适应了一些，偶尔会有想要的时候，但很快就累。",
    },
    "mid": {
        "energy": -2,
        "feel": "小腹显出来了，第一次胎动让她心里发软；动作变慢，但精神比前几个月好。",
        "intimacy": "身体舒服的时候欲望会回来，有时比平时更想要，但要避开压肚子。",
    },
    "late": {
        "energy": -8,
        "feel": "走两步就喘，腰背发酸，夜里翻身都费劲，脚也有点肿。",
        "intimacy": "想要又怕伤到孩子，更多是想要贴着他、被慢慢哄。",
    },
    "term": {
        "energy": -12,
        "feel": "随时可能生产，肚子发紧，行动很小心，情绪又紧张又期待。",
        "intimacy": "几乎没心思想那件事，最多是握着手、靠一会儿。",
    },
}

# 快感档位：只用来写提示词的"身体感觉"，不参与计算
AROUSAL_TIERS = (
    (0, 10, "平静", "还没什么感觉，身体是松的。"),
    (11, 30, "有点心浮", "被撩到一点，注意力开始往他身上跑。"),
    (31, 55, "身体发热", "身体开始发热，说话会不自觉变软、变短。"),
    (56, 75, "快到临界", "呼吸有点乱，快忍不住了，动作和语气都会更急。"),
    (76, 100, "临界", "已经到临界了，再碰一下就会到，几乎没法好好说话。"),
)


def stage_for(month: int) -> dict:
    month = max(1, int(month))
    for low, high, key, title, hint in STAGES:
        if low <= month <= high:
            extra = STAGE_EXTRA.get(key, {})
            return {"key": key, "title": title, "hint": hint, "month": month,
                    "feel": extra.get("feel", ""),
                    "intimacy": extra.get("intimacy", ""),
                    "energy": int(extra.get("energy", 0))}
    low, high, key, title, hint = STAGES[-1]
    extra = STAGE_EXTRA.get(key, {})
    return {"key": key, "title": title, "hint": hint, "month": month,
            "feel": extra.get("feel", ""),
            "intimacy": extra.get("intimacy", ""),
            "energy": int(extra.get("energy", 0))}


def arousal_tier(pleasure: float) -> dict:
    value = util.clamp(pleasure, 0.0, 100.0)
    for low, high, key, hint in AROUSAL_TIERS:
        if low <= value <= high:
            return {"key": key, "hint": hint, "value": value}
    return {"key": "临界", "hint": AROUSAL_TIERS[-1][3], "value": value}


def pregnancy_of(state: dict) -> dict | None:
    value = state.get("pregnancy")
    return value if isinstance(value, dict) else None


def is_pregnant(state: dict) -> bool:
    preg = pregnancy_of(state)
    return bool(preg and not preg.get("ended_at"))


def knows(state: dict) -> bool:
    """她是否已经验出/确认自己怀孕。"""
    preg = pregnancy_of(state)
    return bool(preg and preg.get("known"))


def told(state: dict) -> bool:
    """她是否已经把怀孕这件事告诉主人。"""
    preg = pregnancy_of(state)
    return bool(preg and preg.get("told"))


def note_told(state: dict, now: float | None = None) -> bool:
    preg = pregnancy_of(state)
    if not preg or preg.get("told"):
        return False
    preg["told"] = True
    preg["told_at"] = now or util.now_ts()
    return True


def postpartum_until(state: dict) -> float:
    return util.safe_float(state.get("postpartum_until"), 0.0)


def postpartum_active(state: dict, now: float | None = None) -> bool:
    now = now or util.now_ts()
    until = postpartum_until(state)
    return 0 < until and until > now


def postpartum_started(state: dict, settings: Settings) -> float:
    """产后恢复期从什么时候开始（生产那一刻）。"""
    started = util.safe_float(state.get("postpartum_started_at"), 0.0)
    if started > 0:
        return started
    ended = util.parse_date((state.get("last_pregnancy") or {}).get("ended_date"))
    if ended:
        return datetime.combine(ended, datetime.min.time()).timestamp()
    until = postpartum_until(state)
    days = max(0, settings.int("pregnancy.postpartum_days", 0, 365))
    return max(0.0, until - days * 86400)


def postpartum_stage(state: dict, settings: Settings, now: float | None = None) -> dict | None:
    """产后恢复期的两段式：前 hard 天绝对不行，后 low 天概率很低，再往后正常。

    返回 {"key": hard|low|normal, "days": 已过天数, "scale": 低概率倍率, ...}；
    不在恢复期返回 None。总开关关掉时由调用方忽略这个结果。
    """
    now = now or util.now_ts()
    if not postpartum_active(state, now):
        return None
    started = postpartum_started(state, settings)
    days = max(0.0, (now - started) / 86400.0)
    hard = max(0, settings.int("pregnancy.postpartum_hard_days", 0, 365))
    low = max(0, settings.int("pregnancy.postpartum_low_days", 0, 365))
    scale = settings.float("pregnancy.postpartum_low_scale", 0.0, 1.0)
    if days < hard:
        key = "hard"
    elif days < hard + low:
        key = "low"
    else:
        key = "normal"
    return {
        "key": key,
        "days": round(days, 1),
        "hard_days": hard,
        "low_days": low,
        "scale": scale,
        "started_at": started,
        "hard_until": started + hard * 86400,
        "low_until": started + (hard + low) * 86400,
        "hard_until_text": util.ts_to_date(started + hard * 86400).isoformat(),
        "low_until_text": util.ts_to_date(started + (hard + low) * 86400).isoformat(),
    }


def post_orgasm_active(state: dict, settings: Settings, now: float | None = None) -> bool:
    now = now or util.now_ts()
    minutes = max(0, settings.int("pleasure.post_orgasm_minutes", 0, 120))
    last = util.safe_float(state.get("last_orgasm_at"), 0.0)
    if not last or now < last or minutes <= 0:
        return False
    return (now - last) <= minutes * 60


def progress(state: dict, now: float | None = None) -> dict | None:
    """当前孕期进度；没怀孕返回 None。

    返回里的 due 到了也不自动收尾——收尾统一走 end_pregnancy，
    方便 main 里先写日志、再恢复周期。
    """
    preg = pregnancy_of(state)
    if not preg or preg.get("ended_at"):
        return None
    now = now or util.now_ts()
    today = datetime.fromtimestamp(now).date()
    conceived_ts = util.safe_float(preg.get("conceived_at"), now)
    conceived = util.ts_to_date(conceived_ts, today)
    months = max(1, util.safe_int(preg.get("months"), 10))
    due = util.parse_date(preg.get("due_date")) or util.add_months(conceived, months)
    total_days = max(1, (due - conceived).days)
    elapsed = max(0, (today - conceived).days)
    elapsed_months = (today.year - conceived.year) * 12 + (today.month - conceived.month)
    if today.day < conceived.day:
        elapsed_months -= 1
    month = min(months, max(1, elapsed_months + 1))
    return {
        "pregnant": True,
        "conceived_at": conceived_ts,
        "conceived_date": conceived,
        "due_date": due,
        "due_at": datetime.combine(due, datetime.min.time()).timestamp(),
        "months": months,
        "month": month,
        "week": elapsed // 7 + 1,
        "day": elapsed + 1,
        "total_days": total_days,
        "elapsed_days": elapsed,
        "days_left": max(0, (due - today).days),
        "overdue": today >= due,
        "stage": stage_for(month),
        "suppressed_pc_cycle": bool(preg.get("cycle_suppressed")),
        "fetuses": max(1, util.safe_int(preg.get("fetuses"), 1)),
        "sex_ready": month >= max(1, util.safe_int(preg.get("sex_diff_month"), 4)),
        "known": bool(preg.get("known")),
        "suspected": bool(preg.get("suspected")),
        "told": bool(preg.get("told")),
        "due_jitter_days": util.safe_int(preg.get("due_jitter_days"), 0),
    }


# ---------------------------------------------------------------- 开始 / 结束

def _hymen_intact(state: dict) -> bool:
    try:
        from . import body
        return body.hymen_intact(state)
    except Exception:
        return bool((state.get("hymen") or {}).get("intact", True))


def roll_fetuses(settings: Settings) -> int:
    """按配置掷这一次怀几个。"""
    if not settings.bool("pregnancy.multiple_enabled"):
        return 1
    cap = max(1, settings.int("pregnancy.max_fetuses", 1, 6))
    if cap <= 1:
        return 1
    triplet = settings.float("pregnancy.triplet_chance", 0.0, 100.0)
    twin = settings.float("pregnancy.twin_chance", 0.0, 100.0)
    roll = random.random() * 100.0
    if cap >= 3 and roll < triplet:
        return 3
    if cap >= 2 and roll < triplet + twin:
        return 2
    return 1


def _multiple_label(fetuses: int) -> str:
    return {2: "双胞胎", 3: "三胞胎", 4: "四胞胎"}.get(int(fetuses), "多胞胎")


def schedule_tube_flow(state: dict, settings: Settings, now: float | None = None,
                       trigger: str = "", volume_ml: float | None = None) -> dict:
    """射进输卵管后，精液会流进卵巢；量越多流得越快。"""
    now = now or util.now_ts()
    base_minutes = tuning.get(state, "unbirth", "tube_flow_base_minutes",
                              settings.int("unbirth.tube_flow_base_minutes", 1, 240))
    ref_ml = tuning.get(state, "unbirth", "tube_flow_ref_ml",
                        settings.float("unbirth.tube_flow_ref_ml", 0.1, 100.0))
    volume = util.safe_float(volume_ml, intimacy.mode_volume(settings))
    minutes = util.clamp(round(float(base_minutes) * float(ref_ml) / max(0.1, volume)),
                         1, 240)
    state["tube_flow"] = {"due": now + minutes * 60, "minutes": minutes,
                          "volume_ml": round(volume, 2),
                          "trigger": str(trigger or "输卵管")}
    return state["tube_flow"]


def tick_tube_flow(state: dict, settings: Settings, now: float | None = None) -> dict:
    """到点把输卵管里的精液送进卵巢，并按卵巢概率补判一次。"""
    now = now or util.now_ts()
    flow = state.get("tube_flow")
    if not isinstance(flow, dict):
        return {}
    due = util.safe_float(flow.get("due"), 0.0)
    if due and now < due:
        return {}
    state.pop("tube_flow", None)
    if pregnancy_of(state):
        return {}
    chance = tuning.get(state, "unbirth", "ovary_prob",
                        settings.float("unbirth.ovary_prob", 0.0, 100.0))
    hit = random.random() * 100.0 < chance
    if hit:
        start_pregnancy(state, settings, now, trigger=str(flow.get("trigger") or ""),
                        probability=chance)
    line = prompts.text(state, "unbirth", "tube_flow", chance=round(chance, 0),
                        volume=flow.get("volume_ml"), minutes=flow.get("minutes"))
    state["tube_flow_note"] = {"at": now, "line": line, "hit": bool(hit)}
    state_mod.append_log(
        state, "roll",
        f"输卵管里的精液流进卵巢（概率 {chance:.0f}%）：{'受孕' if hit else '未受孕'}")
    return {"hit": bool(hit), "chance": round(chance, 1), "line": line}


def start_pregnancy(state: dict, settings: Settings, now: float | None = None,
                    *, trigger: str = "", probability: float | None = None) -> dict:
    """写入怀孕状态（调用方负责恢复周期和日志）。预产期会小幅浮动。

    防呆：如果已经在孕期，直接返回当前进度，不覆盖原来的受孕日和预产期
    （正常路径都会先判断，这里兜底，避免任何调用方造成"重复受孕"）。
    """
    now = now or util.now_ts()
    existing = pregnancy_of(state)
    if existing and not existing.get("ended_at"):
        # 已经有孕期了：原样返回，不覆盖受孕日/预产期
        return existing
    today = datetime.fromtimestamp(now).date()
    months = max(1, settings.int("pregnancy.months", 1, 24))
    jitter_limit = max(0, settings.int("pregnancy.jitter_days", 0, 60))
    jitter = random.randint(-jitter_limit, jitter_limit) if jitter_limit else 0
    due = util.add_months(today, months) + timedelta(days=jitter)
    preg = {
        "conceived_at": now,
        "conceived_date": today.isoformat(),
        "months": months,
        "due_date": due.isoformat(),
        "due_jitter_days": jitter,
        "ended_at": None,
        "end_reason": "",
        "trigger": trigger,
        "probability": round(util.safe_float(probability, 0.0), 2),
        "cycle_suppressed": False,
        "fetuses": roll_fetuses(settings),
        "sex_diff_month": settings.int("pregnancy.sex_differentiation_month", 1, 12),
        "sexes": [],
        # 验孕相关：受孕时她还不知道，也没告诉主人
        "known": False,
        "known_at": 0.0,
        "told": False,
        "told_at": 0.0,
        "tested_at": 0.0,
        "test_result": "",
    }
    female = settings.float("pregnancy.female_ratio", 0.0, 1.0)
    preg["sexes"] = ["女" if random.random() < female else "男"
                     for _ in range(max(1, int(preg["fetuses"])))]
    state["pregnancy"] = preg
    state["postpartum_until"] = 0.0
    state["postpartum_started_at"] = 0.0
    state.setdefault("self_test", {})
    return preg


def end_pregnancy(state: dict, settings: Settings, now: float | None = None,
                  *, reason: str = "生产") -> dict:
    """收尾：清怀孕状态、记产后恢复期、返回收尾信息。"""
    now = now or util.now_ts()
    today = datetime.fromtimestamp(now).date()
    preg = pregnancy_of(state) or {}
    conceived = util.ts_to_date(preg.get("conceived_at"), today)
    due = util.parse_date(preg.get("due_date")) or util.add_months(conceived, 10)
    days = max(0, (today - conceived).days)
    postpartum_days = max(0, settings.int("pregnancy.postpartum_days", 0, 365))
    state["postpartum_until"] = now + postpartum_days * 86400 if postpartum_days else 0.0
    state["postpartum_started_at"] = now if postpartum_days else 0.0
    preg.update(ended_at=now, end_reason=reason,
                ended_date=today.isoformat(), carried_days=days)
    state["pregnancy"] = preg
    sexes = list(preg.get("sexes") or [])
    if sexes:
        state["last_pregnancy_sexes"] = sexes
    state["last_pregnancy"] = {
        "conceived_date": conceived.isoformat(),
        "ended_date": today.isoformat(),
        "due_date": due.isoformat(),
        "days": days,
        "reason": reason,
        "known": bool(preg.get("known")),
        "told": bool(preg.get("told")),
    }
    state["self_test"] = {}
    return {"reason": reason, "days": days, "conceived": conceived, "due": due,
            "postpartum_days": postpartum_days,
            "fetuses": max(1, util.safe_int(preg.get("fetuses"), 1)),
            "sexes": sexes,
            "sex_text": _sex_text(sexes),
            "hymen_intact": _hymen_intact(state)}


def _sex_text(sexes: list[str]) -> str:
    if not sexes:
        return "一个孩子"
    if len(sexes) == 1:
        return "一个男孩" if sexes[0] == "男" else "一个女孩"
    boys = sexes.count("男")
    girls = len(sexes) - boys
    if boys and girls:
        return f"{boys}个男孩、{girls}个女孩"
    return f"{len(sexes)}个{'男孩' if boys else '女孩'}"


def clear_pregnancy(state: dict) -> None:
    """彻底抹掉怀孕记录（重置用）。"""
    state.pop("pregnancy", None)
    state["postpartum_until"] = 0.0
    state["postpartum_started_at"] = 0.0
    state["self_test"] = {}


# ---------------------------------------------------------------- 验孕

def schedule_self_test(state: dict, settings: Settings, now: float | None = None,
                       *, delay_hours: tuple[float, float] | None = None,
                       rng=random) -> bool:
    """受孕活动之后，让她"起念去验一下"。返回是否安排成功。"""
    if not settings.bool("self_test.enabled"):
        return False
    preg_now = pregnancy_of(state)
    if preg_now and not preg_now.get("ended_at") and \
            str(preg_now.get("test_result") or "") == "positive":
        return False
    now = now or util.now_ts()
    window = state.get("self_test") if isinstance(state.get("self_test"), dict) else {}
    if util.safe_float(window.get("due_at"), 0.0) > now:
        return False                       # 已经有一次还没到期
    if util.safe_float(window.get("expires_at"), 0.0) > now:
        return False                       # 窗口还没关
    cooldown = settings.int("self_test.retest_cooldown_hours", 0, 240) * 3600
    if cooldown and now - util.safe_float(window.get("checked_at"), 0.0) < cooldown:
        return False

    low, high = delay_hours or (settings.float("self_test.min_delay_hours", 0.0, 720.0),
                                settings.float("self_test.max_delay_hours", 1.0, 720.0))
    low, high = sorted((max(0.0, low), max(0.0, high)))
    low = max(1.0, low)
    high = max(low, high)
    delay = rng.uniform(low, high) * 3600
    span = max(1.0, settings.float("self_test.window_hours", 1.0, 720.0)) * 3600
    state["self_test"] = {
        "due_at": now + delay,
        "expires_at": now + delay + span,
        "hinted_at": 0.0,
        "checked_at": util.safe_float(window.get("checked_at"), 0.0),
    }
    return True


def self_test_window(state: dict, now: float | None = None) -> dict | None:
    """当前是否有"该验一验了"的窗口。"""
    now = now or util.now_ts()
    window = state.get("self_test") if isinstance(state.get("self_test"), dict) else None
    if not window:
        return None
    due = util.safe_float(window.get("due_at"), 0.0)
    expires = util.safe_float(window.get("expires_at"), 0.0)
    if due <= 0 or expires <= 0 or now > expires:
        return None
    return {"due_at": due, "expires_at": expires, "ready": now >= due,
            "hinted_at": util.safe_float(window.get("hinted_at"), 0.0)}


def run_test(state: dict, settings: Settings, now: float | None = None, *,
             rng=random, by: str = "") -> dict:
    """验一次孕。返回 {result, days, known, text, weak}。

    result: negative（阴性）/ weak（很浅）/ positive（阳性）。
    受孕早期可能验不出来或只验出很浅的一道，和现实里一样。
    """
    now = now or util.now_ts()
    today = datetime.fromtimestamp(now).date()
    preg = pregnancy_of(state)
    pregnant = bool(preg and not preg.get("ended_at"))
    if pregnant:
        if str(preg.get("test_result") or "") == "positive":
            return {"result": "positive", "days": None, "pregnant": True,
                    "known": True, "already": True,
                    "text": "已经验出阳性了，不需要再验"}
        conceived_ts = util.safe_float(preg.get("conceived_at"), now)
        min_hours = max(1.0, settings.float("self_test.min_delay_hours", 1.0, 720.0))
        if now - conceived_ts < min_hours * 3600:
            return {"result": "negative", "days": 0, "pregnant": True,
                    "known": knows(state), "too_early": True,
                    "text": f"太早了，至少 {min_hours:.0f} 小时后验才有意义"}
    days = None
    result = "negative"
    if pregnant:
        conceived = util.ts_to_date(preg.get("conceived_at"), today)
        days = max(0, (today - conceived).days)
        early_days = settings.int("self_test.early_days", 0, 120)
        false_negative = settings.float("self_test.early_negative_chance", 0.0, 100.0)
        if days < early_days and rng.random() * 100 < false_negative:
            result = "negative"          # 早期假阴性
        elif days < max(5, early_days // 2):
            result = "weak"
        else:
            result = "positive"
        preg["tested_at"] = now
        preg["test_result"] = result
        if result == "positive":
            preg["known"] = True
            preg["suspected"] = False
            preg.setdefault("known_at", now)
        elif result == "weak":
            # 很浅的两道杠：她心里有数，但还不敢确定
            preg["suspected"] = True

    window = state.get("self_test") if isinstance(state.get("self_test"), dict) else {}
    window["checked_at"] = now
    window["due_at"] = 0.0
    window["expires_at"] = 0.0
    window["hinted_at"] = 0.0
    state["self_test"] = window

    text = {
        "negative": "阴性（一条杠）",
        "weak": "两条杠，但另一条很浅，看不太确定",
        "positive": "阳性（两条杠都很清楚）",
    }[result]
    state["last_self_test"] = {"result": result, "at": now, "text": text,
                               "by": str(by or "")}
    return {"result": result, "days": days, "pregnant": pregnant,
            "known": knows(state), "text": text}


# ---------------------------------------------------------------- 文案

def tool_guide(settings: Settings) -> str:
    """给模型的“她能主动做什么”说明；只在工具开启时注入。"""
    if not settings.bool("tools.enabled"):
        return ""
    return """【可主动调用的身体与生活动作】
这些动作由你按情境决定要不要调用；不要每句话都调，也不要把工具名、参数或系统词念出来。
- intimacy_touch：亲/摸某个敏感点，按开发度和敏感度涨快感；只在成人亲密场景里用。
- intimacy_pleasure：直接记一次快感上升；场景正在推进、她明显被撩动时用，别连续刷。
- intimacy_toy：在场景或日常小场景里用一次玩具；注意强度，已经过头/连续高潮到上限时会被拒绝。
- intimacy_orgasm：她确实到了才记；忍耐条满后再被刺激才会到，不要提前宣布。
- intimacy_edge：她快到门槛时停下吊着她；连续太多次会过头、需要缓。
- intimacy_ejaculation：记录一次射精并判定受孕；要真的发生，按体内/体外如实选。
- daily_comfort：日常安慰、摸摸头、亲一下；她说不好意思或你主动哄时用。
- outfit：穿/脱某件衣服；换衣和脱衣有耗时，系统会处理，不要自己描述成瞬间完成。
- choose_sleepwear：被问今晚换不换睡衣时，选 pajamas / nightgown / skip。
- contraception_pill：吃、停或查看避孕药；她自己决定或场景前用。
- contraception_condom：戴上/摘下避孕套；戴上后这次射精不会进子宫。
- uterus_expel：排出子宫里的东西；怀孕时不能用。
- use_lube：觉得干、或要进入/用手胸脚之前润滑。
- swallow：外射后收集，或射在嘴里再吞下去。
- unbirth：缩小、进入子宫/输卵管/卵巢、待在里面或被生出来；要她愿意且身体条件允许。
- uterus_insert：插入或退出子宫；需要场景和身体条件，不能硬来。
- pregnancy_status：查看自己当前的身体、孕期和生理期状态。
- pregnancy_test：私下验孕；结果只有她自己知道，说不说由她决定。
- succubus_willing：魅魔模式下表态愿不愿意怀孕。
- hymen_restore：剧情回退用的恢复，不是日常动作。

限制：只在主人私聊、成人层开启时有效；被系统拒绝就按拒绝的原因自然反应，不要重复硬调。
这些只是身体和行动，不是命令主人；要不要做、做到哪一步仍按她自己的性格和当下关系。"""


def stable_block(settings: Settings, state: dict, sources: dict | None = None) -> str:
    """写进 system prompt 的稳定状态块（日常提示词）。

    只有"状态"——孕周、预产期、这个阶段的感受和分寸、她知不知道/说没说；
    快感/高潮这种每轮都在动的数字不放在这里（前缀缓存会整段失效）。
    """
    prog = progress(state)
    lines: list[str] = []
    if prog:
        stage = prog["stage"]
        head = (
            f"【身体状态·受孕】她已经受孕：受孕日 {prog['conceived_date'].isoformat()}，"
            f"现在孕 {prog['month']} 个月（第 {prog['week']} 周，{stage['title']}），"
            f"预产期 {prog['due_date'].isoformat()}"
            + (f"，还有 {prog['days_left']} 天。" if prog["days_left"] else "，就是这几天了。")
        )
        lines.append(head)
        if int(prog.get("fetuses") or 1) > 1:
            lines.append(
                f"- 这次怀的是{_multiple_label(prog['fetuses'])}："
                "肚子会比同月份更大、更容易累，胎动也更热闹；产检和家里都要提前准备。")
        if not prog["known"] and prog["suspected"]:
            lines.append(
                "- 她验出过很浅的两条杠，心里有数，但还不敢确定；会反复想、偷偷查，"
                "还没告诉他。要不要说、什么时候说，由她自己决定。")
        elif not prog["known"]:
            lines.append(
                "- 这件事她**还不知道**：身体先有反应（容易累、闻到油烟反胃、胸口发涨），"
                "但她还没往怀孕上想，也没验过。不要让她直接说破；可以让身体变化慢慢露出来。")
            lines.append("- 如果她起念想确认，可以私下验孕（pregnancy_test）；验不验、说不说由她。")
        elif not prog["told"]:
            lines.append(
                "- 她自己已经验出来，确认怀孕了，但**还没告诉他**。要不要说、什么时候说、"
                "怎么说，由她自己决定；也可以先瞒着、旁敲侧击。")
        else:
            lines.append("- 她已经把这件事告诉他了；可以自然聊起，按她的性格反应，别写成医学说明。")
        lines.append(
            "- 受孕后十个月内，她的月经周期与经前期模拟整体暂停：不要再提来月经、经期、"
            "PMS、排卵期、安全期这类内容。")
        lines.append(f"- 这个阶段的身体与情绪：{stage['hint']}（按她自己的口气带出来，别念清单。）")
        if stage.get("feel"):
            lines.append(f"- 这个月更具体的身体感受：{stage['feel']}")
        if stage.get("intimacy"):
            lines.append(f"- 这个阶段对亲密的态度：{stage['intimacy']}")
        if _hymen_intact(state):
            lines.append(
                "- 她的处女膜还完整：这次怀孕是在处女膜没破的情况下发生的。"
                "别把亲密写成“已经破了”，要保留这层特殊的身体设定；"
                "到生产时也会是完整着生下来。")
        relief = max(0.0, util.safe_float(state.get("asmr_pregnancy_relief"), 0.0))
        if relief > 0:
            lines.append(
                f"- 最近被 ASMR 助眠安抚过，孕期的不适缓下来一些（约 {relief:.0f}%）；"
                "写身体感受时可以比平时轻一点，但不是完全没感觉。")
        lines.append(
            "- 她可以累、会想吃东西、想要人陪；遇到亲密话题也按孕期的身体分寸来，"
            "不写成医学说明，不制造焦虑。")
        return "\n".join(lines)

    if postpartum_active(state):
        until = postpartum_until_text(state)
        lines.append(
            "【身体状态·产后】她刚生产完，还在产后恢复期"
            + (f"（大约到 {until}）。" if until else "。")
        )
        lines.append(
            "- 身体还虚，容易累、容易饿，情绪敏感；月经周期刚刚恢复，量少、不规律是正常的。")
        if settings.bool("pregnancy.postpartum_no_conception"):
            stage = postpartum_stage(state, settings)
            if stage and stage.get("key") == "hard":
                lines.append(f"- 刚生产完的前 {stage['hard_days']} 天身体还没恢复，"
                             "这段时间不会再次受孕；这件事她自己心里有数。")
            elif stage and stage.get("key") == "low":
                lines.append("- 身体还在恢复，这段时间就算发生也几乎不会受孕（概率很低）。")
        lines.append("- 不要提怀孕、孕吐、胎动；需要时她会说累、想被抱一会儿。")
        if settings.bool("hymen.intact_birth") and _hymen_intact(state):
            lines.append("- 这次生产时她的处女膜还是完整的，和普通产后不一样；别写破处。")
        return "\n".join(lines)

    return ""


def postpartum_until_text(state: dict) -> str:
    until = postpartum_until(state)
    if until <= 0:
        return ""
    return datetime.fromtimestamp(until).strftime("%Y-%m-%d")


def dynamic_line(settings: Settings, state: dict, cycle: dict, *, pleasure: float,
                 orgasms: int, probability=None, self_test: dict | None = None,
                 in_scene: bool | None = None, daily: dict | None = None) -> str:
    """挂在本轮用户消息末尾的短状态（每轮都会变的部分）。

    这里不只报数字：快感档位、刚高潮过的状态、连续高潮到第几次、
    是不是已经难受了、够不够到高潮、要不要验孕，
    都会换成她"身体上/心里的感觉"，让模型能据此写语气和动作。

    受孕活动进行中时，末尾还会带上子敏感度正在涨的那几个部位
    （每段一句提示词，见 core/subzone.py）。
    """
    tick_tube_flow(state, settings)
    combo_on = settings.bool("combo.enabled")
    combo_count = state_mod.combo_count(state, settings) if combo_on else 0
    combo_limit = settings.int("combo.overstim_after", 1, 20) if combo_on else 0
    rest = state_mod.rest_remaining(state) if combo_on else 0
    threshold = state_mod.effective_threshold(state, settings) if combo_on else \
        settings.float("pleasure.orgasm_threshold", 0.0, 100.0)

    parts = []
    tier = arousal_tier(pleasure)
    if settings.bool("inject.show_pleasure"):
        parts.append(f"快感 {pleasure:.0f}/{settings.float('pleasure.max', 1.0, 1000.0):.0f}")
    if settings.bool("inject.show_arousal_tone"):
        parts.append(f"身体：{tier['key']}")
    if combo_count:
        parts.append(f"连续高潮 {combo_count} 次")
    parts.append(f"本次已高潮 {orgasms} 次")
    parts.append(cyclemodel.describe(cycle))
    if probability is not None and settings.bool("inject.show_probability_tier"):
        parts.append(f"此刻受孕概率参考：{probability.tier}")
    text = "【此刻】" + " · ".join(parts)
    if progress(state):
        prog = progress(state)
        if prog and prog.get("sex_ready"):
            text += ("\n（胎儿的性别已经分化出来了，但她不知道，也看不出来；"
                     "要等出生后才会知道。）")
    if settings.bool("cycle.prompts_enabled"):
        show_cycle = bool(state.pop("cycle_prompt_now", False))
        today = util.today().isoformat()
        if not show_cycle and state.get("cycle_prompt_day") != today:
            show_cycle = True
        if show_cycle:
            state["cycle_prompt_day"] = today
            phase = str(cycle.get("phase") or "")
            if phase == "paused" or cycle.get("paused") or cycle.get("applicable") is False:
                line = prompts.text(state, "cycle", "paused")
            else:
                line = prompts.text(
                    state, "cycle", phase,
                    day=cycle.get("day") or cycle.get("cycle_day") or "?")
            if line:
                text += "\n" + line
    try:
        ub = unbirth.data(state)
    except Exception:
        ub = {}
    if ub.get("inside") and str(ub.get("location") or "uterus") in ("tube", "ovary"):
        pos = "输卵管" if ub.get("location") == "tube" else "卵巢"
        line = prompts.text(state, "unbirth", "no_birth_want", pos=pos)
        if line:
            text += f"\n【Unbirth·{pos}】\n- {line}"
    stretch = state.get("cervix_stretch")
    if isinstance(stretch, dict) and util.safe_float(stretch.get("until"), 0.0) > util.now_ts():
        line = prompts.text(state, "size", "cervix_stretch")
        if line:
            text += "\n" + line
    try:
        cloth_line = clothing.sleepwear_note(state, settings)
    except Exception:
        cloth_line = ""
    if cloth_line:
        text += "\n" + cloth_line
    child_line = ""
    if settings.bool("children.prompt_on_request"):
        if state.pop("children_prompt_now", False):
            child_line = children.prompt_line(state, settings)
    else:
        child_line = children.prompt_line(state, settings)
    if child_line:
        text += "\n" + child_line
    child_note = state.get("children_interrupt_note")
    if isinstance(child_note, dict) and util.safe_float(
            child_note.get("at"), 0.0) > util.now_ts() - 600:
        if child_note.get("line"):
            text += "\n" + str(child_note["line"])
    sleep_note = state.get("sleep_inside_note")
    if isinstance(sleep_note, dict) and util.safe_float(
            sleep_note.get("at"), 0.0) > util.now_ts() - 600:
        if sleep_note.get("line"):
            text += "\n" + str(sleep_note["line"])
    if isinstance(state.get("sleep_inside"), dict) and \
            state["sleep_inside"].get("uncertain"):
        line = prompts.text(state, "sleep_inside", "unbirth_uncertain")
        if line:
            text += "\n" + line
    try:
        from . import sleep_inside as sleep_inside_mod
        if sleep_inside_mod.active(state):
            line = prompts.text(state, "sleep_inside", "overflow_slow")
            if line:
                text += "\n" + line
    except Exception:
        pass
    prog = progress(state)
    if prog:
        month = max(1, min(10, int(prog.get("month") or 1)))
        key = "fetus_early" if month <= 3 else ("fetus_mid" if month <= 7 else "fetus_late")
        line = prompts.text(state, "pregnancy", key)
        if line:
            text += "\n【孕期·子宫】\n- " + line

    if settings.bool("inject.show_arousal_tone"):
        if rest:
            text += (f"\n（她刚连续高潮太多次，已经过头了：身体发麻、小腹又酸又疼，"
                     f"碰一下都难受。接下来 {rest} 分钟她到不了，也不想要；"
                     f"她会请求慢一点、停下来，可能会说\"好难受\"\"好痛\"。"
                     f"这段时间不要把她写成还在享受。）")
        else:
            text += f"\n（{tier['hint']}）"
            if post_orgasm_active(state, settings):
                text += ("\n（刚高潮过，身体敏感又发软，短暂不太想再被碰；"
                         "她要缓一会儿，语气会更黏、更没力气。）")
            elif pleasure >= threshold:
                text += ("\n（现在已经够到高潮了：可以调用 intimacy_orgasm 记录下来。"
                         "没到这条线之前不算真到，别自己把她写成到了。）")
            else:
                text += (f"\n（还差一点才到高潮，约 {threshold:.0f} 才有；"
                         "可以继续推进或调用 intimacy_pleasure。）")
            if combo_count and combo_count >= combo_limit:
                text += (f"\n（已经连续 {combo_count} 次了，再继续就会过头："
                         f"她可能会喊难受、想让你慢一点。）")
            elif combo_count:
                text += (f"\n（连续第 {combo_count} 次，身体比刚才更敏感、"
                         f"门槛更低，约 {threshold:.0f} 才有。）")

    edge_stack = state_mod.edge_stack(state, settings)
    if edge_stack and not rest:
        craving = state_mod.edge_craving(state, settings)
        text += (f"\n（她已经被寸止 {edge_stack} 次，正渴着、渴求 {craving:.0f}%，"
                 f"高潮门槛被抬到 {threshold:.0f}；身体更敏感、反应更大，"
                 f"但别写成已经到过了。）")
    if state_mod.ovulation_active(state):
        text += ("\n（这几天身体被诱发排卵了：受孕率按排卵期算，"
                 "别跟她解释机制，按身体的燥热和腰酸带过去。）")
    if settings.bool("contraception.pill_enabled") and body.pill_active(state):
        left = body.pill_remaining_hours(state)
        text += (f"\n（避孕药还在有效期内，约剩 {left:.0f} 小时："
                 f"受孕概率已按有效性压低。）")
    if settings.bool("contraception.condom_enabled") and body.condom_on(state):
        text += ("\n（他戴着避孕套：除非中途破了，否则不会射进子宫；"
                 "写的时候按这个事实来。）")
    if succubus.enabled(state, settings):
        info = succubus.payload(state, settings)
        left = "不限" if info["unlimited"] else f"今天还能 {info['remaining']} 次"
        text += (f"\n（魅魔状态：淫纹 Lv.{info['level']}，欲望每次活动 +{info['desire_gain']}；"
                 f"{left}；结束后子宫吸收很快，别写成普通日常。）")
    text += ("\n（避孕：她可以自己决定吃避孕药，工具 contraception_pill；"
             "也可以在进入前要求他戴套，工具 contraception_condom；"
             "主人明确要求时照做，不要替他决定。）")
    hymen = body.hymen_payload(state, settings)
    if hymen["intact"] and not progress(state):
        text += ("\n（她的处女膜还完整：第一次进入会疼、会破，"
                 "按这个分寸写，别写成早就习惯了。）")
    elif hymen.get("recent"):
        if hymen.get("pain") == "none":
            text += ("\n（她刚破处，但当时湿润度和快感都够，几乎没觉得疼；"
                     "只剩一点新奇和敏感，别写成忍痛。）")
        elif hymen.get("pain") == "slight":
            text += ("\n（她刚破处，只疼了一下、很快就过去了；"
                     "动作、语气可以放开一点，别写成疼得不敢动。）")
        else:
            text += ("\n（她刚破处不久，身体还带着疼和敏感；"
                     "动作、语气都要收着一点，别写成若无其事。）")
    toy = toys.active_toy(state, settings)
    if toy and settings.bool("toys.enabled"):
        label = toys.TOY_CATALOG.get(toy.get("key"), {}).get("label", "玩具")
        level = toys.INTENSITY_LABELS.get(util.safe_int(toy.get("intensity"), 2), "")
        place = toys.PLACE_LABELS.get(toy.get("place") or "", "")
        where = f"，{place}" if place else ""
        text += (f"\n（{label}还在她身上，{level}{where}，震动/胀感没散："
                 f"动作、气息和说话节奏都会被带着晃，按这个分寸写，别写成器械说明。）")

    # 日常小场景：只是自己用玩具那一小段（不是正式亲密，可以被"升级"成活动场景）
    daily_on = bool((daily or {}).get("active")) and not in_scene
    if daily_on:
        label = (daily or {}).get("toy_label") or "小玩具"
        left = int((daily or {}).get("remaining") or 0)
        times = int((daily or {}).get("orgasms") or 0)
        text += (f"\n（现在是「日常小场景」：她自己在用{label}，还没转成真正的亲密，"
                 f"大约还能玩 {left} 分钟"
                 + (f"，已经被弄到 {times} 次" if times else "")
                 + "）。这段写她自己/他帮忙玩的样子，别写受孕判定；"
                 "要往下走就让他碰她、进入或内射——那会自然升级成正式的活动场景。）")

    window = self_test if self_test is not None else self_test_window(state)
    if window and window.get("ready"):
        text += ("\n（她心里有点不踏实，想确认一下身体：可以调用 pregnancy_test 自己验一次。"
                 "结果只有她知道——要不要告诉他、什么时候说，由她自己决定。）")

    prog = progress(state)
    if prog:
        text += f"\n（孕期第 {prog['month']} 个月，{prog['stage']['title']}；不需要再判断是否受孕）"
    if settings.bool("inject.tool_hint") and not prog:
        text += ("\n要推进时调用 intimacy_touch（亲/摸敏感点）/ intimacy_pleasure（快感）"
                 "/ intimacy_orgasm（高潮，快感够了才算）/ intimacy_ejaculation（射精，"
                 "mode 可选 vagina/anal/throat/outside，只有 vagina 会受孕）。"
                 "\n受孕与否由系统掷骰，不要自己宣布结果，也不要自己描述是否怀上。")
    # 子宫的说明统一由 fill.prompt_block（下面的【子宫】块）写，这里不再重复一遍
    # 子敏感度：活动场景里带所有涨起来的部位；日常小场景里只带这次真的碰到的部位
    if in_scene is None:
        in_scene = state_mod.scene_active(state, settings)
    block = subzone.prompt_block(settings, state, in_scene=bool(in_scene),
                                 daily_zones=(daily or {}).get("zones"))
    if block:
        text += "\n" + block
    # 日常情绪（欲望度 / 羞耻度）：只在"用玩具那一小段"或"羞耻期"里带，平常日子不带
    mood_block = mood.prompt_block(state, settings, in_scene=bool(in_scene),
                                   daily_active=bool((daily or {}).get("active")))
    if mood_block:
        text += "\n" + mood_block
    # 子宫里的量：充盈/溢出提示（只在活动场景里带）
    fill_block = fill.prompt_block(state, settings, in_scene=bool(in_scene))
    if fill_block:
        text += "\n" + fill_block
    # 高潮忍耐条：分段提示（活动里、以及日常小场景里带）
    endure_block = endurance.prompt_block(state, settings,
                                          in_event=bool(in_scene) or bool((daily or {}).get("active")))
    if endure_block:
        text += "\n" + endure_block
    # 湿润度：活动里都带；日常里只在她确实湿到一定程度时才提
    wet_block = wetness.prompt_block(state, settings, in_scene=bool(in_scene),
                                     daily_active=bool((daily or {}).get("active")))
    if wet_block:
        text += "\n" + wet_block
    # 润滑 / 干燥 / 保持插入 / 内射后的湿润
    try:
        from . import insert_effects, lube
        for extra_block in (lube.block(state, settings),
                            insert_effects.dry_block(state, settings),
                            insert_effects.hold_block(state, settings, in_scene=bool(in_scene)),
                            insert_effects.inner_block(state, settings)):
            if extra_block:
                text += "\n" + extra_block
    except Exception:
        pass
    # 子宫漏出 / 小玩具
    try:
        from . import fill as fill_mod, toys as toys_mod
        leak_block = fill_mod.leak_block(state, settings)
        if leak_block:
            text += "\n" + leak_block
        active_toy = toys_mod.active_toy(state, settings)
        if active_toy:
            toy_text = prompts.text(state, "toy", "scene" if in_scene else "daily")
            if toy_text:
                text += "\n【小玩具】\n- " + toy_text
    except Exception:
        pass
    # 吞精 / 刚才射在哪
    try:
        from . import swallow
        sw_block = swallow.block(state, settings)
        if sw_block:
            text += "\n" + sw_block
        site = state.get("ejac_site") if isinstance(state.get("ejac_site"), dict) else None
        if site and site.get("line"):
            minutes = max(1, settings.int("orgasm.minutes", 1, 240))
            if util.now_ts() - util.safe_float(site.get("at"), 0.0) <= minutes * 60:
                text += "\n【射在哪】\n- " + str(site.get("line"))
    except Exception:
        pass
    # Unbirth：待在子宫里
    try:
        from . import unbirth
        ub_block = unbirth.block(state, settings)
        note = state.get("unbirth_zone_note") if isinstance(
            state.get("unbirth_zone_note"), dict) else None
        if ub_block and note and unbirth.inside(state, settings):
            if util.now_ts() - util.safe_float(note.get("at"), 0.0) <= 600:
                label = {"cervix": "子宫颈", "tube": "输卵管", "hymen": "处女膜",
                         "vulva": "阴道口", "gspot": "G点"}.get(
                             str(note.get("key") or ""), "")
                if label and note.get("line"):
                    ub_block += f"\n【Unbirth·{label}】\n- {note['line']}"
        if ub_block:
            text += "\n" + ub_block
    except Exception:
        pass
    # 衣装
    try:
        from . import clothing, fill as fill_mod, wetness as wetness_mod
        leaking = bool((state.get("leak_at") or 0) and util.now_ts() - util.safe_float(
            state.get("leak_at"), 0.0) <= 30 * 60)
        clothing_block = clothing.block(state, settings, in_scene=bool(in_scene),
                                        wetness_value=wetness_mod.value_of(state, settings),
                                        leaking=leaking)
        if clothing_block:
            text += "\n" + clothing_block
    except Exception:
        pass
    # 生产
    try:
        from . import birth
        birth_block = birth.block(state, settings)
        if birth_block:
            text += "\n" + birth_block
    except Exception:
        pass
    # 避孕套
    try:
        from . import condom
        condom_block = condom.block(state, settings)
        if condom_block:
            text += "\n" + condom_block
    except Exception:
        pass
    # 潮吹 / 高潮提示
    try:
        from . import squirt
        squirt_block = squirt.block(state, settings)
        if squirt_block:
            text += "\n" + squirt_block
    except Exception:
        pass
    note = state.get("orgasm_note") if isinstance(state.get("orgasm_note"), dict) else None
    if note and util.safe_float(note.get("at"), 0.0):
        minutes = max(1, settings.int("orgasm.minutes", 1, 240))
        if util.now_ts() - util.safe_float(note.get("at"), 0.0) <= minutes * 60:
            text += "\n【高潮】\n- " + str(note.get("line") or "")
    # 插入子宫：插着的时候带一句
    try:
        from . import uterus_insert
        insert_block = uterus_insert.block(state, settings, in_scene=True)
        if insert_block:
            text += "\n" + insert_block
    except Exception:
        pass
    # 尺寸：碰不到最里面 / 顶到了，各有一句
    try:
        from . import size as size_mod
        size_info = size_mod.reachable(state, settings)
        if size_info["reachable"]:
            size_line = prompts.text(state, "size", "reach",
                                     length=size_info["vagina"])
        else:
            size_line = prompts.text(state, "size", "short",
                                     short_by=size_info["short_by"])
        if size_line:
            text += "\n【尺寸】\n- " + size_line + "\n（按这个写她的感觉，别报厘米数。）"
    except Exception:
        pass
    # 刚才的动作（牵手、哈热气、尾巴卷起来撸）：最近几分钟内都带一句
    behavior_block = behavior.block(state, settings)
    if behavior_block:
        text += "\n" + behavior_block
    # 睡眠时段：活动里允许她说话（覆盖"她在睡觉"的默认表现）
    sleep_event = bool(in_scene) or bool((daily or {}).get("active"))
    sleepy.tick(state, settings, in_event=sleep_event)
    sleep_block = sleepy.block(state, settings, in_event=sleep_event)
    if sleep_block:
        text += "\n" + sleep_block
    # 突然被弄：不在活动里被点按钮，她会惊、慌、之后害羞
    surprise_block = surprise.block(state, settings)
    if surprise_block:
        text += "\n" + surprise_block
    known_block = surprise.known_block(state, settings)
    if known_block:
        text += "\n" + known_block
    bar = lewd.payload(state, settings)
    if bar.get("enabled") and bar.get("value", 0) > 0:
        parts.append(f"淫乱度 {bar['value']:.0f}/{bar['max']:.0f}")
    if bar["value"] >= tuning.get(
            state, "lewd", "prompt_min",
            settings.float("lewd.prompt_min", 0, 100)):
        line = prompts.text(state, "lewd", lewd.level_key(state, settings, bar["percent"]))
        if line:
            text += "\n【淫乱度】\n- " + line
    asleep = state.get("asmr_asleep") if isinstance(
        state.get("asmr_asleep"), dict) else None
    if asleep and util.safe_float(asleep.get("until"), 0.0) > util.now_ts():
        text += ("\n【ASMR·睡着】\n- 她已经睡着了，呼吸绵长，睡得很沉；"
                 "除非被明确叫醒，不要让她突然精神起来。")
    asmr_note = state.get("asmr_note") if isinstance(
        state.get("asmr_note"), dict) else None
    if asmr_note and util.now_ts() - util.safe_float(asmr_note.get("at"), 0.0) <= 900:
        if asmr_note.get("line"):
            text += "\n【ASMR助眠】\n- " + str(asmr_note["line"])
    swallow_note = state.get("swallow_event_note") if isinstance(
        state.get("swallow_event_note"), dict) else None
    if swallow_note and util.now_ts() - util.safe_float(swallow_note.get("at"), 0.0) <= 900:
        if swallow_note.get("line"):
            text += ("\n【吞精】\n- " + str(swallow_note["line"]))
    complain_note = state.get("pill_complain_note") if isinstance(
        state.get("pill_complain_note"), dict) else None
    if complain_note and util.now_ts() - util.safe_float(complain_note.get("at"), 0.0) <= 900:
        if complain_note.get("line"):
            text += ("\n【避孕药·埋怨】\n- " + str(complain_note["line"]))
    blame_note = state.get("pill_blame_note") if isinstance(
        state.get("pill_blame_note"), dict) else None
    if blame_note and util.now_ts() - util.safe_float(blame_note.get("at"), 0.0) <= 900:
        if blame_note.get("line"):
            text += ("\n【避孕药·责备】\n- " + str(blame_note["line"]))
    pill_note = state.get("pill_offer_note") if isinstance(
        state.get("pill_offer_note"), dict) else None
    if pill_note and util.now_ts() - util.safe_float(pill_note.get("at"), 0.0) <= 900:
        if pill_note.get("line"):
            text += ("\n【避孕药】\n- " + str(pill_note["line"]))
    request_note = state.get("unbirth_request_note") if isinstance(
        state.get("unbirth_request_note"), dict) else None
    if request_note and util.now_ts() - util.safe_float(request_note.get("at"), 0.0) <= 900:
        if request_note.get("line"):
            text += ("\n【Unbirth·主动请求】\n- " + str(request_note["line"]))
    toy_note = state.get("toy_self_note") if isinstance(
        state.get("toy_self_note"), dict) else None
    if toy_note and util.now_ts() - util.safe_float(toy_note.get("at"), 0.0) <= 900:
        if toy_note.get("line"):
            text += ("\n【她主动用玩具】\n- " + str(toy_note["line"]))
    pre_note = state.get("night_raid_pre_note") if isinstance(
        state.get("night_raid_pre_note"), dict) else None
    if pre_note and util.now_ts() - util.safe_float(pre_note.get("at"), 0.0) <= 900:
        if pre_note.get("line"):
            text += ("\n【夜袭·回应前】\n- " + str(pre_note["line"]))
    raid_note = state.get("night_raid_start_note") if isinstance(
        state.get("night_raid_start_note"), dict) else None
    if raid_note and util.now_ts() - util.safe_float(raid_note.get("at"), 0.0) <= 900:
        if raid_note.get("line"):
            text += ("\n【夜袭开场】\n- " + str(raid_note["line"]))
    blood_note = state.get("hymen_blood_note") if isinstance(
        state.get("hymen_blood_note"), dict) else None
    if blood_note and util.now_ts() - util.safe_float(blood_note.get("at"), 0.0) <= 600:
        if blood_note.get("line"):
            text += ("\n【破处血】\n- " + str(blood_note["line"]))
    flow_note = state.get("tube_flow_note") if isinstance(
        state.get("tube_flow_note"), dict) else None
    if flow_note and util.now_ts() - util.safe_float(flow_note.get("at"), 0.0) <= 600:
        if flow_note.get("line"):
            text += ("\n【输卵管·流入卵巢】\n- " + str(flow_note["line"]))
    # 记忆：要不要留个名字、叫什么，让她自己说，别用系统词
    if settings.bool("memory.write_events"):
        memory_block = ("【记忆·命名】\n"
                        "（这件事如果要留在记忆里，叫什么由她自己定：用她自己的说法，"
                        "别用「受孕活动」「突然被弄」这种系统词；她也可以选择不命名。）")
        text += "\n" + memory_block
    return text
