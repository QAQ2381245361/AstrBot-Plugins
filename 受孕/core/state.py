"""状态文件：快感值、高潮次数、射精次数、受孕记录、事件日志。

时间相关的数值（快感衰减、本次会话次数）都按"用到的时候才算"处理，
不跑后台定时器：插件被停掉几天再开，数值也能自然回落，不会卡住。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import util
from .settings import Settings, STATE_FILE

STATE_VERSION = 1
SESSION_FIELDS = ("started_at", "last_event_at", "orgasms", "ejaculations")


def new_state() -> dict:
    now = util.now_ts()
    return {
        "version": STATE_VERSION,
        "created_at": util.today().isoformat(),
        "created_ts": now,
        "pleasure": 0.0,
        "pleasure_updated_at": now,
        "orgasms_total": 0,
        "ejaculations_total": 0,
        "ejaculations_inside_total": 0,
        "ejaculations_modes": {"vagina": 0, "anal": 0, "throat": 0, "outside": 0},
        "zones": {},
        # 子敏感度：每个部位一条 0–100 的活动内进度（只在受孕活动里涨）
        "sub_zones": {},
        # 子敏感度三段提示词的自定义（部位 → ["第1段", "第2段", "第3段"]，空=默认）
        "sub_prompts": {},
        "uterus_ml": 0.0,
        "uterus_updated_at": now,
        "hymen": {"intact": True, "ruptured_at": 0.0, "cause": ""},
        "contraception": {"pill_until": 0.0, "pill_at": 0.0, "condom": False, "condom_at": 0.0},
        "succubus": {"date": "", "count": 0, "tattoo_level": None, "willing": None, "last_desire_scene": 0.0, "exp": 0, "enabled_override": None},
        "tuning": {},
        "edge": {"stack": 0, "last_at": 0.0, "craving": 0.0, "total": 0},
        "induced_ovulation_at": 0.0,
        "induced_ovulation_until": 0.0,
        "conception_attempts": 0,
        "last_orgasm_at": 0.0,
        "last_ejaculation_at": 0.0,
        "last_roll": None,
        "session": {"started_at": now, "last_event_at": 0.0, "orgasms": 0, "ejaculations": 0},
        "day": {"date": util.today().isoformat(), "orgasms": 0, "ejaculations": 0},
        "pregnancy": None,
        "postpartum_until": 0.0,
        "own_cycle": {},
        "scene": {"started_at": 0.0, "last_at": 0.0, "events": 0},
        # 日常小场景：只用了日常玩具、还没进入真正的亲密时的小窗口
        "daily": dict(DAILY_DEFAULT),
        # 高潮忍耐条 / 特别敏感点（endurance.py / special.py 里维护）
        "endurance": {},
        "special": {},
        # 日常情绪：欲望度 / 羞耻度（core/mood.py）
        "mood": {},
        "desire_strategy": {},
        "lewd": {"value": 0.0, "at": 0.0, "last_gain_at": 0.0,
                 "last_tick_at": 0.0, "last_settle_at": 0.0},
        "night_raid": {},
        "night_activity": {"at": 0.0, "kind": "", "ejac_at": 0.0, "orgasm_at": 0.0},
        "combo": dict(COMBO_DEFAULT),
        "log": [],
        "adult_consent_until": 0.0,
    }


def normalize(state: dict) -> dict:
    """补齐缺失字段（升级/手改文件后仍然能跑）。"""
    base = new_state()
    if not isinstance(state, dict):
        return base
    for key, value in base.items():
        if key not in state:
            state[key] = value
        elif isinstance(value, dict) and not isinstance(state.get(key), dict):
            state[key] = value
        elif isinstance(value, list) and not isinstance(state.get(key), list):
            state[key] = value
    state["version"] = STATE_VERSION
    return state


class Store:
    """state.json 的读写。写用临时文件替换，读坏了就用新状态。"""

    def __init__(self, path=None):
        self.path = Path(path or STATE_FILE)
        self.state = new_state()

    def load(self) -> dict:
        raw = util.read_json(self.path, None)
        self.state = normalize(raw if isinstance(raw, dict) else {})
        return self.state

    def save(self) -> bool:
        return util.write_json_atomic(self.path, self.state)


# ---------------------------------------------------------------- 数值

def decay_pleasure(state: dict, settings: Settings, now: float | None = None) -> float:
    """一直没人碰：先等 idle_minutes，过了这段才开始按小时往回掉。"""
    now = now or util.now_ts()
    last = util.safe_float(state.get("pleasure_updated_at"), now)
    idle = max(0, settings.int("pleasure.idle_minutes", 0, 1440)) * 60
    hours = max(0.0, (now - last - idle) / 3600.0)
    state["pleasure_updated_at"] = now
    if hours <= 0:
        return util.safe_float(state.get("pleasure"), 0.0)
    per_hour = settings.float("pleasure.decay_per_hour", 0.0, 1000.0)
    cap = settings.float("pleasure.max", 1.0, 1000.0)
    value = util.safe_float(state.get("pleasure"), 0.0) - per_hour * hours
    state["pleasure"] = util.clamp(value, 0.0, cap)
    return state["pleasure"]


def add_pleasure(state: dict, settings: Settings, amount: float,
                 now: float | None = None) -> float:
    now = now or util.now_ts()
    decay_pleasure(state, settings, now)
    cap = settings.float("pleasure.max", 1.0, 1000.0)
    before = util.safe_float(state.get("pleasure"), 0.0)
    state["pleasure"] = util.clamp(before + amount, 0.0, cap)
    # 快感涨的同时也在攒"高潮忍耐"：低于 endurance.gain_at 加得少，到了就加正常量
    from . import endurance  # 局部导入，endurance 不依赖 state，不会循环
    if endurance.enabled(settings) and amount > 0:
        endurance.gain(state, settings, pleasure=state["pleasure"], now=now)
    return state["pleasure"]


def _roll_over(state: dict, settings: Settings, now: float) -> None:
    """跨天/超时：重置当天计数和本次会话。"""
    today = util.today().isoformat()
    day = state.get("day") if isinstance(state.get("day"), dict) else {}
    if day.get("date") != today:
        state["day"] = {"date": today, "orgasms": 0, "ejaculations": 0}

    timeout = max(60, settings.int("pleasure.session_timeout_minutes", 1, 1440)) * 60
    session = state.get("session") if isinstance(state.get("session"), dict) else {}
    last = util.safe_float(session.get("last_event_at"), 0.0)
    if not last or (now - last) > timeout:
        state["session"] = {"started_at": now, "last_event_at": 0.0,
                            "orgasms": 0, "ejaculations": 0}


def session_orgasms(state: dict, settings: Settings, now: float | None = None) -> int:
    now = now or util.now_ts()
    _roll_over(state, settings, now)
    return util.safe_int((state.get("session") or {}).get("orgasms"), 0)


def add_orgasm(state: dict, settings: Settings, now: float | None = None,
               *, extra_gain: float = 0.0) -> dict:
    """记一次高潮：次数 +1，快感先加一点再按不应期比例回落。"""
    now = now or util.now_ts()
    _roll_over(state, settings, now)
    cap = settings.float("pleasure.max", 1.0, 1000.0)
    gain = settings.float("pleasure.orgasm_pleasure_gain", 0.0, 500.0) + max(0.0, extra_gain)
    ratio = settings.float("pleasure.orgasm_afterglow_ratio", 0.0, 1.0)
    before = add_pleasure(state, settings, gain, now)
    after = util.clamp(before * ratio, 0.0, cap)
    state["pleasure"] = after
    state["pleasure_updated_at"] = now
    state["last_orgasm_at"] = now
    state["orgasms_total"] = util.safe_int(state.get("orgasms_total"), 0) + 1
    session = state.setdefault("session", {})
    session["orgasms"] = util.safe_int(session.get("orgasms"), 0) + 1
    session["last_event_at"] = now
    day = state.setdefault("day", {})
    day["orgasms"] = util.safe_int(day.get("orgasms"), 0) + 1
    return {"before": before, "after": after, "session": session["orgasms"],
            "today": day["orgasms"], "total": state["orgasms_total"]}


def add_ejaculation(state: dict, settings: Settings, *, inside: bool | None = None,
                    mode: str = "", now: float | None = None) -> dict:
    """记一次射精。mode 取 vagina/anal/throat/outside；inside 是旧参数兼容。"""
    from . import intimacy

    if not mode:
        mode = "vagina" if (inside is None or inside) else "outside"
    mode = intimacy.normalize_mode(mode) or "vagina"
    now = now or util.now_ts()
    _roll_over(state, settings, now)
    state["last_ejaculation_at"] = now
    state["ejaculations_total"] = util.safe_int(state.get("ejaculations_total"), 0) + 1
    if mode == "vagina":
        state["ejaculations_inside_total"] = util.safe_int(
            state.get("ejaculations_inside_total"), 0) + 1
    modes = state.setdefault("ejaculations_modes", {})
    modes[mode] = util.safe_int(modes.get(mode), 0) + 1
    session = state.setdefault("session", {})
    session["ejaculations"] = util.safe_int(session.get("ejaculations"), 0) + 1
    session["last_event_at"] = now
    day = state.setdefault("day", {})
    day["ejaculations"] = util.safe_int(day.get("ejaculations"), 0) + 1
    return {"mode": mode, "inside": mode == "vagina",
            "session": session["ejaculations"],
            "today": day["ejaculations"], "total": state["ejaculations_total"],
            "modes": dict(modes)}


def orgasm_recent(state: dict, settings: Settings, now: float | None = None) -> bool:
    now = now or util.now_ts()
    window = max(0, settings.int("conception.orgasm_window_minutes", 0, 120)) * 60
    last = util.safe_float(state.get("last_orgasm_at"), 0.0)
    if not last or now < last:
        return False
    return (now - last) <= window


# ---------------------------------------------------------------- 场景

def scene_last_at(state: dict) -> float:
    scene = state.get("scene") if isinstance(state.get("scene"), dict) else {}
    return util.safe_float(scene.get("last_at"), 0.0)


def scene_active(state: dict, settings: Settings, now: float | None = None) -> bool:
    """本插件自己的"亲密场景"是否还在有效期内。

    场景只由明确的亲密动作开启/刷新：工具（快感/高潮/射精）、命令、
    或者 /受孕场景。平常聊天里的关键词不会开启场景，也就不参与判定。
    """
    now = now or util.now_ts()
    window = max(1, settings.int("adult.scene_window_minutes", 1, 720)) * 60
    last = scene_last_at(state)
    if not last or now < last:
        return False
    if (now - last) <= window:
        return True
    try:
        from . import sleep_inside, uterus_insert
        if sleep_inside.active(state, now) or uterus_insert.active(state):
            return True
    except Exception:
        pass
    return False


def touch_scene(state: dict, now: float | None = None, *,
                window_seconds: float = 1800) -> dict:
    """开场/续场：记下最后一次亲密动作的时间。"""
    now = now or util.now_ts()
    scene = state.get("scene") if isinstance(state.get("scene"), dict) else {}
    last = util.safe_float(scene.get("last_at"), 0.0)
    if not scene.get("started_at") or not last or (now - last) > max(1.0, window_seconds):
        scene["started_at"] = now
    scene["last_at"] = now
    scene["events"] = util.safe_int(scene.get("events"), 0) + 1
    state["scene"] = scene
    return scene


def scene_remaining(state: dict, settings: Settings, now: float | None = None) -> int:
    """场景还剩几分钟。"""
    now = now or util.now_ts()
    window = max(1, settings.int("adult.scene_window_minutes", 1, 720)) * 60
    remaining = window - (now - scene_last_at(state))
    if remaining <= 0:
        return 0
    return (int(remaining) + 59) // 60


def clear_scene(state: dict) -> None:
    state["scene"] = {"started_at": 0.0, "last_at": 0.0, "events": 0}


# ---------------------------------------------------------------- 日常小场景
# 不进入亲密场景、只是自己（或他帮忙）用一下日常能用的玩具时，开一个小窗口：
# 这段时间里对应部位的子敏感度会涨、也会注入提示词，还可能被玩具送上高潮；
# 一旦发生真正的亲密动作（碰她/进入/内射…），这个小场景就"升级"成正常场景。

DAILY_DEFAULT = {"started_at": 0.0, "last_at": 0.0, "zone": "", "toy": "",
                 "uses": 0, "orgasms": 0, "escalated_at": 0.0}


def daily_of(state: dict) -> dict:
    value = state.get("daily")
    if not isinstance(value, dict):
        value = dict(DAILY_DEFAULT)
        state["daily"] = value
    for key, default in DAILY_DEFAULT.items():
        value.setdefault(key, default)
    return value


def _daily_window_seconds(settings: Settings) -> float:
    return max(1, settings.int("toys.daily_minutes", 1, 240)) * 60


def daily_last_at(state: dict) -> float:
    return util.safe_float(daily_of(state).get("last_at"), 0.0)


def daily_active(state: dict, settings: Settings, now: float | None = None) -> bool:
    """日常小场景还在有效期内吗（只是一次玩具的小窗口，不是亲密场景）。"""
    now = now or util.now_ts()
    last = daily_last_at(state)
    if not last or now < last:
        return False
    return (now - last) <= _daily_window_seconds(settings)


def daily_remaining(state: dict, settings: Settings, now: float | None = None) -> int:
    now = now or util.now_ts()
    last = daily_last_at(state)
    if not last:
        return 0
    left = _daily_window_seconds(settings) - (now - last)
    return 0 if left <= 0 else (int(left) + 59) // 60


def touch_daily(state: dict, zone: str = "", toy: str = "",
                now: float | None = None, *, window_seconds: float | None = None) -> dict:
    """开/续一个日常小场景：记下这次是哪个部位、哪个玩具。"""
    now = now or util.now_ts()
    daily = daily_of(state)
    last = util.safe_float(daily.get("last_at"), 0.0)
    span = max(1.0, window_seconds or 1200.0)
    if not daily.get("started_at") or not last or (now - last) > span:
        daily["started_at"] = now
        daily["uses"] = 0
        daily["orgasms"] = 0
    daily["last_at"] = now
    if zone:
        daily["zone"] = str(zone)
    if toy:
        daily["toy"] = str(toy)
    daily["uses"] = util.safe_int(daily.get("uses"), 0) + 1
    return daily


def note_daily_orgasm(state: dict, now: float | None = None) -> None:
    daily = daily_of(state)
    daily["last_at"] = now or util.now_ts()
    daily["orgasms"] = util.safe_int(daily.get("orgasms"), 0) + 1


def clear_daily(state: dict, *, escalated: bool = False,
                now: float | None = None) -> None:
    """结束日常小场景（escalated=True 表示是被真正的亲密动作接上了）。"""
    daily = daily_of(state)
    daily["started_at"] = 0.0
    daily["last_at"] = 0.0
    daily["uses"] = 0
    daily["orgasms"] = 0
    daily["zone"] = ""
    daily["toy"] = ""
    daily["escalated_at"] = (now or util.now_ts()) if escalated else 0.0


def daily_payload(state: dict, settings: Settings, now: float | None = None) -> dict:
    """给面板/提示词用的一层摘要。"""
    daily = daily_of(state)
    active = daily_active(state, settings, now)
    return {
        "active": active,
        "zone": str(daily.get("zone") or ""),
        "toy": str(daily.get("toy") or ""),
        "uses": util.safe_int(daily.get("uses"), 0),
        "orgasms": util.safe_int(daily.get("orgasms"), 0),
        "remaining": daily_remaining(state, settings, now) if active else 0,
        "started_at": util.safe_float(daily.get("started_at"), 0.0),
        "last_at": util.safe_float(daily.get("last_at"), 0.0),
        "escalated_at": util.safe_float(daily.get("escalated_at"), 0.0),
    }


# ---------------------------------------------------------------- 连续高潮

COMBO_DEFAULT = {"count": 0, "last_at": 0.0, "peak": 0, "rest_until": 0.0}


def combo_of(state: dict) -> dict:
    combo = state.get("combo")
    if not isinstance(combo, dict):
        combo = dict(COMBO_DEFAULT)
        state["combo"] = combo
    return combo


def _combo_window_seconds(settings: Settings) -> float:
    return max(1, settings.int("combo.window_minutes", 1, 180)) * 60


def combo_count(state: dict, settings: Settings, now: float | None = None) -> int:
    """当前"连续高潮"已经到第几次（窗口过了就算断了）。"""
    now = now or util.now_ts()
    combo = combo_of(state)
    last = util.safe_float(combo.get("last_at"), 0.0)
    if not last or now < last or (now - last) > _combo_window_seconds(settings):
        return 0
    return max(0, util.safe_int(combo.get("count"), 0))


def combo_peak(state: dict) -> int:
    return max(0, util.safe_int(combo_of(state).get("peak"), 0))


def combo_threshold(state: dict, settings: Settings, now: float | None = None) -> float:
    """这一次高潮所需的快感门槛：连续越多越敏感、门槛越低。"""
    base = settings.float("pleasure.orgasm_threshold", 0.0, 100.0)
    if not settings.bool("combo.enabled"):
        return base
    step = settings.float("combo.threshold_step", 0.0, 50.0)
    floor = settings.float("combo.threshold_floor", 0.0, 100.0)
    count = combo_count(state, settings, now)
    return max(min(floor, base), base - step * count)


def add_combo_orgasm(state: dict, settings: Settings, now: float | None = None) -> dict:
    """记一次高潮进"连续"计数；返回 {count, peak, window_minutes}。"""
    now = now or util.now_ts()
    combo = combo_of(state)
    window = _combo_window_seconds(settings)
    last = util.safe_float(combo.get("last_at"), 0.0)
    if not last or now < last or (now - last) > window:
        combo["count"] = 1
    else:
        combo["count"] = util.safe_int(combo.get("count"), 0) + 1
    combo["last_at"] = now
    combo["peak"] = max(util.safe_int(combo.get("peak"), 0), combo["count"])
    return {"count": combo["count"], "peak": combo["peak"],
            "window_minutes": settings.int("combo.window_minutes", 1, 180)}


def overstimulated(state: dict, now: float | None = None) -> bool:
    """她现在是不是"高潮过头、碰一下都难受"的状态。"""
    now = now or util.now_ts()
    return util.safe_float(combo_of(state).get("rest_until"), 0.0) > now


def rest_remaining(state: dict, now: float | None = None) -> int:
    """还要缓几分钟。"""
    now = now or util.now_ts()
    until = util.safe_float(combo_of(state).get("rest_until"), 0.0)
    remaining = until - now
    if remaining <= 0:
        return 0
    return (int(remaining) + 59) // 60


def set_rest(state: dict, settings: Settings, now: float | None = None,
             *, minutes: int | None = None) -> int:
    """进入"过头了、要缓一缓"的状态；返回要缓的分钟数。"""
    now = now or util.now_ts()
    span = max(1, minutes if minutes is not None
               else settings.int("combo.rest_minutes", 1, 240))
    combo = combo_of(state)
    combo["rest_until"] = now + span * 60
    return span


def clear_combo(state: dict) -> None:
    state["combo"] = dict(COMBO_DEFAULT)


# ---------------------------------------------------------------- 寸止

EDGE_DEFAULT = {"stack": 0, "last_at": 0.0, "craving": 0.0, "total": 0,
               "step_override": -1.0}  # -1 = 跟随配置


def edge_of(state: dict) -> dict:
    edge = state.get("edge")
    if not isinstance(edge, dict):
        edge = dict(EDGE_DEFAULT)
        state["edge"] = edge
    return edge


def _edge_window_seconds(settings: Settings) -> float:
    return max(1, settings.int("edge.window_minutes", 1, 240)) * 60


def edge_stack(state: dict, settings: Settings, now: float | None = None) -> int:
    """当前连着被寸止了几次（超过窗口就算消退）。"""
    if not settings.bool("edge.enabled"):
        return 0
    now = now or util.now_ts()
    edge = edge_of(state)
    last = util.safe_float(edge.get("last_at"), 0.0)
    if not last or now < last or (now - last) > _edge_window_seconds(settings):
        edge["stack"] = 0
        return 0
    return max(0, util.safe_int(edge.get("stack"), 0))


def edge_craving(state: dict, settings: Settings, now: float | None = None) -> float:
    """寸止后的渴求（0–100），随时间回落。"""
    now = now or util.now_ts()
    edge = edge_of(state)
    craving = max(0.0, util.safe_float(edge.get("craving"), 0.0))
    updated = util.safe_float(edge.get("craving_at"), now)
    decay = max(0.0, settings.float("edge.craving_decay_per_hour", 0.0, 100.0))
    hours = max(0.0, (now - updated) / 3600.0)
    if decay and hours > 0:
        craving = max(0.0, craving - decay * hours)
    edge["craving"] = craving
    edge["craving_at"] = now
    return craving


def edge_step(state: dict, settings: Settings) -> float:
    """门槛加成的基数：面板可以临时改，-1 表示跟随配置。"""
    override = util.safe_float(edge_of(state).get("step_override"), -1.0)
    if override >= 0:
        return util.clamp(override, 0.0, 50.0)
    return max(0.0, settings.float("edge.threshold_step", 0.0, 50.0))


def set_edge_step(state: dict, value: float | None) -> float:
    """面板调门槛加成；传 None 恢复跟随配置。返回 -1 表示已恢复。"""
    if value is None:
        edge_of(state)["step_override"] = -1.0
        return -1.0
    step = util.clamp(util.safe_float(value, 0.0), 0.0, 50.0)
    edge_of(state)["step_override"] = round(step, 2)
    return round(step, 2)


def edge_next_bonus(state: dict, settings: Settings, now: float | None = None) -> float:
    """下一次寸止会把门槛再抬高多少（按当前层数递减）。"""
    if not settings.bool("edge.enabled"):
        return 0.0
    stack = edge_stack(state, settings, now)
    step = edge_step(state, settings)
    decay = min(1.0, max(0.0, settings.float("edge.step_decay", 0.0, 1.0)))
    return round(step * (decay ** stack), 2)


def edge_threshold_bonus(state: dict, settings: Settings, now: float | None = None) -> float:
    """寸止把门槛暂时抬高多少：每次递减，最多 max_bonus。"""
    if not settings.bool("edge.enabled"):
        return 0.0
    stack = edge_stack(state, settings, now)
    if stack <= 0:
        return 0.0
    step = edge_step(state, settings)
    decay = min(1.0, max(0.0, settings.float("edge.step_decay", 0.0, 1.0)))
    cap = max(0.0, settings.float("edge.max_bonus", 0.0, 50.0))
    total, cur = 0.0, step
    for _ in range(stack):
        total += cur
        cur *= decay
    return min(cap, total)


def effective_threshold(state: dict, settings: Settings, now: float | None = None) -> float:
    """这一次真正的高潮门槛：连续高潮降低 + 寸止抬高。"""
    base = combo_threshold(state, settings, now)
    return util.clamp(base + edge_threshold_bonus(state, settings, now), 1.0, 100.0)


def edge_gain_multiplier(state: dict, settings: Settings, now: float | None = None) -> float:
    """渴求越高，触碰/快感涨得越快。"""
    if not settings.bool("edge.enabled"):
        return 1.0
    craving = edge_craving(state, settings, now)
    bonus = max(0.0, settings.float("edge.craving_gain_bonus", 0.0, 2.0))
    return 1.0 + bonus * craving / 100.0


def add_edge(state: dict, settings: Settings, now: float | None = None) -> dict:
    """记一次寸止：层数 +1、渴求上升。返回 {stack, bonus, craving}。"""
    now = now or util.now_ts()
    edge = edge_of(state)
    stack = edge_stack(state, settings, now)
    edge["stack"] = stack + 1
    edge["last_at"] = now
    edge["total"] = util.safe_int(edge.get("total"), 0) + 1
    gain = max(0.0, settings.float("edge.craving_gain", 0.0, 100.0))
    edge["craving"] = min(100.0, max(0.0, util.safe_float(edge.get("craving"), 0.0)) + gain)
    edge["craving_at"] = now
    return {"stack": edge["stack"], "total": edge["total"],
            "craving": edge_craving(state, settings, now),
            "bonus": edge_threshold_bonus(state, settings, now)}


def clear_edge(state: dict) -> None:
    """清掉层数/渴求，但保留面板设过的门槛加成。"""
    edge = edge_of(state)
    override = util.safe_float(edge.get("step_override"), -1.0)
    state["edge"] = dict(EDGE_DEFAULT)
    state["edge"]["step_override"] = override


def edge_orgasm_bonus(state: dict, settings: Settings, now: float | None = None) -> float:
    """寸止之后终于到的高潮，额外加多少快感。"""
    if not settings.bool("edge.enabled"):
        return 0.0
    stack = edge_stack(state, settings, now)
    if stack <= 0:
        return 0.0
    per = max(0.0, settings.float("edge.orgasm_bonus", 0.0, 100.0))
    cap = max(0.0, settings.float("edge.orgasm_bonus_cap", 0.0, 200.0))
    return min(cap, per * stack)


# ---------------------------------------------------------------- 诱发排卵

def ovulation_until(state: dict) -> float:
    return util.safe_float(state.get("induced_ovulation_until"), 0.0)


def ovulation_active(state: dict, now: float | None = None) -> bool:
    now = now or util.now_ts()
    return ovulation_until(state) > now


def induce_ovulation(state: dict, settings: Settings, now: float | None = None) -> dict:
    """进入"被诱发出来的排卵期"，持续 duration_hours。"""
    now = now or util.now_ts()
    hours = max(1.0, settings.float("ovulation.duration_hours", 1.0, 240.0))
    until = now + hours * 3600.0
    state["induced_ovulation_at"] = now
    state["induced_ovulation_until"] = until
    return {"at": now, "until": until, "hours": hours}


def clear_ovulation(state: dict) -> None:
    state["induced_ovulation_at"] = 0.0
    state["induced_ovulation_until"] = 0.0


# ---------------------------------------------------------------- 日志

def append_log(state: dict, kind: str, text: str, now: float | None = None,
               limit: int = 300) -> None:
    log = state.get("log")
    if not isinstance(log, list):
        log = []
        state["log"] = log
    log.append({"at": now or util.now_ts(), "kind": str(kind), "text": str(text)[:300]})
    if len(log) > limit:
        del log[:-limit]


def recent_log(state: dict, limit: int = 10) -> list[dict]:
    log = state.get("log")
    if not isinstance(log, list):
        return []
    return log[-max(1, limit):]


# ---------------------------------------------------------------- 成人同意（本插件自己的）

def consent_active(state: dict, now: float | None = None) -> bool:
    now = now or util.now_ts()
    return util.safe_float(state.get("adult_consent_until"), 0.0) > now


def grant_consent(state: dict, hours: float, now: float | None = None) -> float:
    now = now or util.now_ts()
    until = now + max(0.0, hours) * 3600 if hours > 0 else 0.0
    state["adult_consent_until"] = until
    return until


def clear_consent(state: dict) -> None:
    state["adult_consent_until"] = 0.0


def dump(state: dict) -> str:
    try:
        return json.dumps(state, ensure_ascii=False, default=str)[:400]
    except (TypeError, ValueError):
        return ""
