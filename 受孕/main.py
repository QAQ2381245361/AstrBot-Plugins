"""受孕 —— 让她会怀孕的插件（AstrBot）。

它不抢别人管的事，只做四件：
1. 记录「快感值」和「高潮次数」（工具 / 关键词 / 命令三种入口）；
2. 每次体内射精掷一次受孕概率，概率由**鱼之心的欲**、**暗涌的 lust**、
   当前**生理期阶段**、快感与高潮次数共同决定，高潮后短时间被射再加一档；
3. 受孕成功后把「受孕状态」写进日常提示词（system prompt），
   并把 private_companion 的月经周期置为"不生效"，持续十个月；
4. 判断当前人格性别是否适合：男性/其他/关闭时不生效，绝不硬套。

设计约定（和这套系统里别的自写插件一致）：
- 只在主人私聊里工作；群聊永远不处理。
- 成人层没打开时什么都不做（鱼之心的成人层，或 /受孕同意 的临时授权）。
- 只读鱼之心/暗涌的数据；写 private_companion 的只有 cycle_clock 一个字段，
  并且带 revision 保护 + 原值备份。
- 受孕结果只由这里的掷骰决定，提示词里明确要求模型不要自己宣布怀上。
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from pathlib import Path
from datetime import datetime, timedelta

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register

from .core import (
    asmr,
    body,
    boost,
    cyclemodel,
    endurance,
    fertility,
    fill,
    intimacy,
    mood,
    pc_cycle,
    pc_state,
    subzone,
    succubus,
    tuning,
    special,
    persona as persona_mod,
    pregnancy,
    sources,
    state as state_mod,
    toys,
    util,
    wetness,
    behavior,
    birth,
    children,
    clothing,
    condom,
    desire,
    insert_effects,
    lewd,
    lube,
    memory_link,
    menstrual,
    night,
    prompts,
    size,
    sleepy,
    sleep_inside,
    squirt,
    swallow,
    unbirth,
    uterus_insert,
    surprise,
)
from .core.settings import (
    PLUGIN_AUTHOR,
    PLUGIN_NAME,
    PLUGIN_VERSION,
    CONFIG_DIR,
    Settings,
)

try:  # 老版本 AstrBot 没有这个类时退回 system_prompt
    from astrbot.core.agent.message import TextPart
except Exception:  # pragma: no cover - 运行环境相关
    TextPart = None

# 比鱼之心（-10）低，保证"当前身体状态"排在所有状态块最后
INJECT_PRIORITY = -60
TICK_SECONDS = 1800
SUPPRESS_RECHECK_SECONDS = 300
CYCLE_CACHE_SECONDS = 60
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

HELP_TEXT = """受孕插件 · 命令
/受孕状态    看人格适配、场景、生理期、快感、高潮、敏感点、子宫、受孕概率分解、孕期、验孕情况
/受孕同意    给本插件一个成人层临时授权（默认 24 小时）
/受孕关闭    撤掉临时授权
/受孕场景    手动进入/续上亲密场景（30 分钟）；加"关闭"结束
/受孕测试    按当前状态算一次概率（不掷骰、不受孕）
/受孕快感 [数值]   快感值 +N（默认按配置，同时续场）
/受孕触碰 <部位> [次数] [方式]   亲/摸敏感点（亲吻、乳房、乳头、外阴、阴道、G点、子宫颈、肛、嘴、耳朵、脚、尾巴；
                         方式如 乳交/舔/吮吸/揉搓/逗弄/手指/生殖器/小玩具/抚摸/揉捏玩弄/舔耳，能填就填）
/受孕敏感点  看所有敏感点的开发度、敏感度和每次涨幅（面板里还有子敏感度板块）
/受孕玩具 <名字> [强度]   用一次小玩具（跳蛋/振动棒/吸吮器/按摩棒/肛塞/乳夹；不带参数看列表）
/受孕情绪              看欲望度 / 羞耻度，以及羞耻期还剩多久
/受孕高潮 [强制]   记一次高潮（快感到门槛才算；加"强制"跳过门槛）
/受孕寸止    快到的时候停下来：之后更渴、门槛暂时抬高，最后到的时候更强烈
/受孕内射    记一次阴道内射精并掷受孕骰（需成人层，同时续场，计入子宫容量）
/受孕肛内    记一次肛内射精（不会受孕，快感加成不同）
/受孕深喉    记一次深喉射精（不会受孕，快感加成不同）
/受孕体外    记一次体外射精（基本不会受孕）
/受孕排出    排出子宫里的东西（孕期会拒绝）
/受孕避孕药 [吃/停]   避孕药；/受孕避孕套 [戴/摘]   /受孕避孕状态
/受孕处女膜 [恢复]  看状态 / 恢复完整
/受孕魅魔 [等级 N|愿意|不愿意|重置]  魅魔状态与设置
/受孕强制    直接置为受孕（测试用）
/受孕重置 确认   结束/清除孕期并恢复 PC 周期
/受孕记录    看最近事件
说明：关键词识别只在"亲密场景"里生效（工具、命令或 /受孕场景 开的窗口，
或鱼之心正处于成人场景），平常聊天里出现关键词不会误判。
子敏感度：面板「子敏感度」板块只在受孕活动里生效——碰一下涨那里的条（三段：初起/发烫/将溢，
每段一句提示词），条满了给她主敏感点加开发度和敏感度、再补一笔快感，然后几秒内回落到 0。"""


def _clamp_amount(value, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


@register(PLUGIN_NAME, PLUGIN_AUTHOR,
          "受孕：快感/高潮/内射概率 + 孕期状态写进提示词 + 孕期暂停生理期", PLUGIN_VERSION)
class ConceptionPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.settings = Settings(config)
        self.store = state_mod.Store()
        self.state = self.store.load()

        self._task = None
        self._gender = None
        self._gender_at = 0.0
        self._cycle_cache = None
        self._cycle_cache_at = 0.0
        self._pc_checked_at = 0.0
        self._last_sources = None
        self._last_sources_at = 0.0
        self._last_umo = str(self.state.get("last_umo") or "")
        # 面板旧开关优先读 state；启动时让配置页成为唯一来源，避免两边显示不一致。
        for state_key in ("unbirth_enabled", "unbirth_request_enabled",
                          "toy_self_use_enabled", "pill_proactive_enabled",
                          "pill_blame_enabled", "asmr_enabled",
                          "wetness_base_float_enabled", "hymen_blood_enabled",
                          "surprise_enabled_override", "sleep_allow_override",
                          "wetness_fish_write", "uterus_overflow_enabled",
                          "uterus_after_leak_enabled"):
            self.state.pop(state_key, None)
        body = self.state.pop("user_body", None)
        if isinstance(body, dict):
            self._persist_config_value("unbirth.user_height",
                                       util.clamp(util.safe_float(body.get("height_cm"), 170), 50, 250))
            self._persist_config_value("unbirth.user_weight",
                                       util.clamp(util.safe_float(body.get("weight_kg"), 60), 20, 300))
        tuning_rows = self.state.get("tuning")
        if isinstance(tuning_rows, dict) and tuning_rows and \
                type(self.context).__name__ != "StubContext":
            migrated = True
            for section, rows in tuning_rows.items():
                if not isinstance(rows, dict):
                    continue
                for key, value in rows.items():
                    if not self._persist_config_value(self._config_path(section, key), value):
                        migrated = False
            if migrated:
                self.state["tuning"] = {}

    # ================================================================ 生命周期

    async def initialize(self) -> None:
        try:
            self.store.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            logger.warning("[受孕] 无法创建数据目录：%s", error)

        # 面板接口先注册：即使总开关关着，页面也要能打开
        self._register_web_apis()
        self._refresh_gender(force=True)
        logger.info("[受孕] 已加载：人格=%s｜总开关=%s｜PC 周期暂停=%s",
                    self._gender.get("gender") if self._gender else "?",
                    "开" if self.settings.bool("enabled") else "关",
                    "开" if self.settings.bool("pregnancy.suppress_pc_cycle") else "关")
        if not (self._gender or {}).get("suitable", True):
            logger.info("[受孕] 当前人格不适合启用，插件保持静默：%s",
                        (self._gender or {}).get("evidence", ""))

        self._tick()
        self._task = asyncio.create_task(self._loop(), name="conception-loop")

    async def terminate(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        try:
            self._save()
        except Exception:
            pass
        logger.info("[受孕] 已停止")

    async def _loop(self) -> None:
        await asyncio.sleep(30)
        while True:
            try:
                self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # 后台循环不能把插件带崩
                logger.warning("[受孕] 定时检查异常：%s", error)
            await asyncio.sleep(TICK_SECONDS)

    # ================================================================ 小工具

    def _save(self) -> bool:
        """落盘。先把当前状态对象挂回 store，免得两者引用漂移。"""
        self.store.state = self.state
        return self.store.save()

    def _active(self, event=None) -> bool:
        """总开关 + 人格适配 + 主人配置齐全。"""
        if not self.settings.bool("enabled"):
            return False
        gender = self._refresh_gender(event)
        return bool(gender.get("suitable"))

    def _owner_qq(self) -> str:
        return self.settings.str("owner_qq")

    def _owner_private(self, event) -> bool:
        try:
            if not event.is_private_chat():
                return False
        except Exception:
            return False
        owner = self._owner_qq()
        if not owner:
            self._remember_session(event)
            return True
        try:
            if str(event.get_sender_id()) == owner:
                self._remember_session(event)
                return True
            return False
        except Exception:
            return False

    def _remember_session(self, event) -> None:
        """记住最近一次主人私聊的会话，面板点按钮时可以主动发消息过去。"""
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        if umo:
            changed = umo != self._last_umo
            self._last_umo = umo
            if self.state.get("last_umo") != umo:
                self.state["last_umo"] = umo
                if changed:
                    self._save()

    def _refresh_gender(self, event=None, force: bool = False) -> dict:
        """判断当前人格性别。

        AstrBot 在请求阶段会把本会话实际人格 id 记在 event 的
        `_trace_persona_id` 上；有就用它，没有才退回配置里的 persona_name。
        """
        persona_name = self.settings.str("persona_name")
        if event is not None:
            try:
                traced = str(event.get_extra("_trace_persona_id") or "").strip()
            except Exception:
                traced = ""
            if traced and traced not in ("[%None]", "_chatui_default_"):
                persona_name = traced

        now = time.time()
        if not force and self._gender and (now - self._gender_at) < 600 \
                and self._gender.get("persona_name") == persona_name:
            return self._gender
        try:
            result = persona_mod.resolve(self.context, self.settings, name=persona_name)
        except Exception as error:
            logger.warning("[受孕] 判断人格性别失败：%s", error)
            result = {"gender": "unknown", "suitable": True, "source": "error",
                      "evidence": str(error), "policy": "allow",
                      "persona_name": persona_name}
        if self._gender is None or result.get("gender") != self._gender.get("gender") \
                or result.get("suitable") != self._gender.get("suitable") \
                or result.get("persona_name") != self._gender.get("persona_name"):
            logger.info("[受孕] 人格适配：%s", persona_mod.describe(result))
        self._gender = result
        self._gender_at = now
        return result

    # ---------------------------------------------------------------- 数据源

    def _read_sources(self, force: bool = False) -> dict:
        now = time.time()
        if not force and self._last_sources and (now - self._last_sources_at) < 5:
            return self._last_sources
        data = sources.read_all(self.settings, self.context)
        self._last_sources = data
        self._last_sources_at = now
        return data

    def _pc_clock(self) -> dict | None:
        now = time.time()
        if self._cycle_cache is not None and (now - self._cycle_cache_at) < CYCLE_CACHE_SECONDS:
            return self._cycle_cache
        try:
            self._cycle_cache = cyclemodel.read_pc_clock(
                pc_cycle.db_path(self.settings),
                self.settings.str("pregnancy.pc_role_name"))
        except Exception as error:
            logger.debug("[受孕] 读 PC 周期失败：%s", error)
            self._cycle_cache = None
        self._cycle_cache_at = now
        return self._cycle_cache

    def _gate(self, data: dict | None = None) -> tuple[bool, str]:
        """成人层是否允许参与。"""
        data = data or self._read_sources()
        if not self.settings.bool("adult_required"):
            return True, "未设成人层门槛"
        ok, why = sources.adult_gate(self.settings, data)
        if ok:
            return True, why
        if state_mod.consent_active(self.state):
            return True, "本插件已临时授权"
        return False, why

    def _cycle(self) -> dict:
        prog = pregnancy.progress(self.state)
        cycle = cyclemodel.resolve(
            self.settings, self.state,
            pregnant=bool(prog),
            postpartum=pregnancy.postpartum_active(self.state),
            pc_clock=(self._pc_clock() or {}).get("clock"),
        )
        # 诱发排卵：这几天按排卵期算（受孕率也按排卵期基准）
        if not prog and state_mod.ovulation_active(self.state):
            cycle = dict(cycle)
            cycle["phase"] = "ovulation"
            cycle["label"] = "排卵期（诱发）"
            cycle["induced"] = True
        return cycle

    def _pleasure(self) -> float:
        return state_mod.decay_pleasure(self.state, self.settings)

    # ================================================================ 周期与孕期维护

    def _asmr_allow_speech(self) -> None:
        row = asmr.data(self.state)
        until = util.safe_float(row.get("until"), 0.0)
        if until > util.now_ts():
            pc_state.set_night_raid_bypass(self.settings, until + 300)

    def _asmr_note(self, line: str, now: float | None = None) -> None:
        if line:
            self.state["asmr_note"] = {"at": now or util.now_ts(), "line": line}

    def _asmr_pc_note(self, text: str) -> None:
        if type(self.context).__name__ == "StubContext":
            return
        try:
            pc_state.add_condition(self.settings, text, marker="ASMR助眠")
        except Exception as error:
            logger.warning("[受孕] 写 PC 助眠条件失败：%s", error)

    def _asmr_tick(self) -> None:
        row = asmr.data(self.state)
        if not row.get("active"):
            return
        now = util.now_ts()
        if util.safe_float(row.get("until"), 0.0) > now:
            return
        info = asmr.finish(self.state, self.settings, now=now)
        if info.get("ok"):
            self._asmr_note(info.get("line") or "")
            self._asmr_pc_note("刚结束一段 ASMR 助眠，这一觉会睡得更沉，醒来精力恢复得更多，但不超过原来的 100 上限。")
            try:
                sleepy.tick(self.state, self.settings, in_event=False)
            except Exception as error:
                logger.warning("[受孕] 结束助眠睡眠例外失败：%s", error)
            pc_state.clear_night_raid_bypass()
            state_mod.append_log(self.state, "asmr", "助眠到点结束")
            self._save()

    def _asmr_night_key(self, at: datetime | None = None) -> str:
        """按请求时段把跨午夜的夜晚归到同一个 key。"""
        moment = at or datetime.now()
        start = self.settings.int("asmr.request_start_hour", 0, 23)
        end = self.settings.int("asmr.request_end_hour", 0, 23)
        day = moment.date()
        hour = moment.hour
        if start > end and hour < end:
            day -= timedelta(days=1)
        return day.isoformat()

    def _asmr_request_tick(self) -> None:
        now = util.now_ts()
        row = asmr.data(self.state)
        if row.get("request_until") and util.safe_float(row["request_until"], 0.0) > now:
            return
        if asmr.active(self.state, self.settings, now):
            return
        if not self.settings.bool("asmr.request_enabled"):
            return
        if self.settings.bool("asmr.request_requires_known") and \
                not self.state.get("asmr_known"):
            return
        if not asmr.enabled(self.state, self.settings):
            return
        hour = datetime.now().hour
        start = self.settings.int("asmr.request_start_hour", 0, 23)
        end = self.settings.int("asmr.request_end_hour", 0, 23)
        in_window = start <= hour < end if start <= end else (hour >= start or hour < end)
        if not in_window:
            return
        defer_until = util.safe_float(self.state.get("asmr_request_defer_until"), 0.0)
        if defer_until and now < defer_until:
            return
        self.state.pop("asmr_request_defer_until", None)
        night = self._asmr_night_key()
        last_request_at = util.safe_float(row.get("request_at"), 0.0)
        last_start_at = util.safe_float(row.get("started_at"), 0.0)
        requested_tonight = bool(
            last_request_at and
            self._asmr_night_key(datetime.fromtimestamp(last_request_at)) == night)
        done_tonight = bool(
            last_start_at and
            self._asmr_night_key(datetime.fromtimestamp(last_start_at)) == night)
        if self.settings.bool("asmr.request_once_per_night") and (
                self.state.get("asmr_request_night") == night or
                self.state.get("asmr_done_night") == night or
                requested_tonight or done_tonight):
            return
        last = util.safe_float(row.get("request_at"), 0.0)
        if last and now - last < 60 * 60:
            return
        chance = self.settings.float("asmr.request_chance", 0.0, 100.0)
        if random.random() * 100 >= chance:
            return
        line = prompts.text(self.state, "asmr", "request")
        if not line:
            return
        try:
            sleep = sleepy.sleeping(self.settings, now=now)
            asleep = bool(sleep.get("sleeping", sleep.get("asleep")))
        except Exception:
            asleep = False
        line = prompts.text(self.state, "asmr",
                            "request_bed" if asleep else "request_awake") or line
        say = prompts.text(self.state, "asmr", "request_say") or line
        wait = max(1, self.settings.int("asmr.request_wait_minutes", 1, 120))
        row["request_at"] = now
        row["request_until"] = now + wait * 60
        self._schedule_asmr_request(line, say)
        self._save()

    async def _recent_dialogue(self, limit: int = 8, max_chars: int = 1200) -> str:
        """取最近几轮私聊，给“适不适合开口”的判断用。"""
        manager = getattr(self.context, "conversation_manager", None)
        umo = str(getattr(self, "_last_umo", "") or "")
        if manager is None or not umo:
            return ""
        try:
            cid = await manager.get_curr_conversation_id(umo)
            if not cid:
                return ""
            conv = await manager.get_conversation(umo, cid)
            raw = getattr(conv, "history", "") or ""
            history = json.loads(raw) if isinstance(raw, str) and raw.strip() else list(raw or [])
        except Exception as error:
            logger.debug("[受孕] 读取最近对话失败：%s", error)
            return ""
        rows = []
        for item in history[-max(1, limit):]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            if role not in ("user", "assistant"):
                continue
            content = item.get("content")
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "".join(
                    str(part.get("text") or "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text")
            text = " ".join(text.split()).strip()
            if not text:
                continue
            rows.append(("主人" if role == "user" else "她") + "：" + text[:300])
        body = "\n".join(rows)
        return body[-max_chars:]

    def _asmr_judge_context(self) -> str:
        """给判断用的当前场景事实，不写具体数值。"""
        now = util.now_ts()
        facts = [f"现在 {datetime.now().strftime('%H:%M')}。"]
        if state_mod.scene_active(self.state, self.settings):
            facts.append("当前正在亲密活动中。")
        if state_mod.daily_active(self.state, self.settings):
            facts.append("当前在日常小场景里。")
        last_scene = state_mod.scene_last_at(self.state)
        if last_scene and now - last_scene < 30 * 60:
            facts.append("活动刚结束不久。")
        try:
            sleep = sleepy.sleeping(self.settings, now=now)
            if sleep.get("sleeping", sleep.get("asleep")):
                facts.append("现在这个时段她/主人可能已经睡下。")
        except Exception:
            pass
        if self.state.get("asmr_asleep"):
            facts.append("她刚在 ASMR 后睡着了。")
        return "".join(facts)

    def _proactive_deferred(self, cause: str, now: float | None = None) -> bool:
        row = self.state.get("proactive_defer")
        if not isinstance(row, dict):
            return False
        until = util.safe_float(row.get(cause), 0.0)
        return bool(until and (now or util.now_ts()) < until)

    def _defer_proactive(self, cause: str, minutes: int) -> None:
        row = self.state.get("proactive_defer")
        if not isinstance(row, dict):
            row = {}
            self.state["proactive_defer"] = row
        row[cause] = util.now_ts() + max(1, minutes) * 60

    async def _judge_proactive_request(self, note: str, kind: str) -> tuple[bool, str]:
        """通用主动请求判断：看时间、场景、最近对话，不适合就先不提。"""
        try:
            getter = getattr(self.context, "get_using_provider", None)
            provider = getter() if callable(getter) else None
            if provider is None:
                logger.warning("[受孕] 主动请求判断失败：没有可用模型")
                return False, ""
            recent = await self._recent_dialogue()
            facts = self._asmr_judge_context()
            prompt = (
                facts + "\n\n"
                + (f"最近对话（按时间顺序，只用于判断气氛）：\n{recent}\n\n"
                   if recent else "")
                + f"她考虑主动提出：{note}\n\n"
                "请判断此刻是否适合她开口。考虑主人是否在忙、情绪如何、"
                "是否正在活动或刚结束、是否刚说过要睡/别打扰、对话气氛是否合适。"
                "不要为了触发而勉强提出。\n"
                "只返回 JSON："
                '{"suitable": true/false, "text": "适合时写她真正说出口的 1-2 句话；不适合时留空"}。'
                "text 必须是她的第一人称，不要旁白、括号或解释。")
            response = await asyncio.wait_for(
                provider.text_chat(
                    prompt=prompt, contexts=[],
                    system_prompt=f"你是她。判断主动提出「{kind}」是否合适，并只输出 JSON。",
                    request_max_retries=1), timeout=30)
            raw = str(getattr(response, "completion_text", "") or "").strip()
            match = re.search(r"\{.*\}", raw, re.S)
            if match:
                try:
                    data = json.loads(match.group(0))
                    suitable = bool(data.get("suitable"))
                    text = str(data.get("text") or "").strip("「」\"'")
                    if suitable and text:
                        return True, text
                    if not suitable:
                        return False, ""
                except Exception:
                    pass
            if any(word in raw for word in ("不适合", "不合适", "别问", "先不问")):
                return False, ""
            if raw:
                text = raw.strip("「」\"'")
                return (True, text) if text else (False, "")
        except Exception as error:
            logger.warning("[受孕] 主动请求判断失败：%s", error)
        return False, ""


    async def _judge_asmr_request(self, note: str) -> tuple[bool, str]:
        """让她判断现在适不适合开口；返回 (是否适合, 要说的话)。"""
        return await self._judge_proactive_request(note, "ASMR 助眠")

    def _schedule_asmr_request(self, note: str, fallback: str) -> None:
        """让模型按她的口吻写请求；生成失败就用固定第一人称。"""
        umo = str(getattr(self, "_last_umo", "") or "")
        if not umo:
            return
        if not self.settings.bool("asmr.request_generate"):
            self._schedule_notice(fallback, "受孕·助眠", "asmr_request")
            return

        async def job() -> None:
            judge = self.settings.bool("asmr.request_judge")
            text = ""
            if judge:
                suitable, text = await self._judge_asmr_request(note)
                if not suitable:
                    row = asmr.data(self.state)
                    row["request_at"] = 0.0
                    row["request_until"] = 0.0
                    minutes = max(1, self.settings.int(
                        "asmr.request_defer_minutes", 1, 1440))
                    self.state["asmr_request_defer_until"] = \
                        util.now_ts() + minutes * 60
                    state_mod.append_log(
                        self.state, "asmr",
                        f"她觉得此刻不适合开口请求助眠，{minutes} 分钟后再判断")
                    self._save()
                    logger.info("[受孕] ASMR 请求暂缓：她觉得此刻不适合")
                    return
            else:
                try:
                    getter = getattr(self.context, "get_using_provider", None)
                    provider = getter() if callable(getter) else None
                    if provider is not None:
                        prompt = (
                            f"{note}\n"
                            "请只用她自己的第一人称，写一句直接对主人说出口的请求；"
                            "不要旁白、括号、动作描写、解释或元指令。")
                        response = await asyncio.wait_for(
                            provider.text_chat(
                                prompt=prompt, contexts=[],
                                system_prompt="你是她。现在由她主动向主人开口请求 ASMR 助眠。"
                                              "只输出她直接说出的 1–2 句中文，不要旁白或括号。",
                                request_max_retries=1), timeout=30)
                        text = str(getattr(response, "completion_text", "")
                                   or "").strip()
                except Exception as error:
                    logger.warning("[受孕] 生成 ASMR 请求失败：%s", error)
            if not text:
                text = fallback
            text = text.strip().strip("「」\"'")
            if not text:
                text = fallback
            self.state["asmr_request_night"] = self._asmr_night_key()
            self.state.pop("asmr_request_defer_until", None)
            self._asmr_note(note)
            state_mod.append_log(self.state, "asmr", "她夜里主动请求助眠")
            await self._send_notice_later(umo, text, "受孕·助眠",
                                          "asmr_request", 0)

        try:
            asyncio.create_task(job())
        except Exception as error:
            logger.warning("[受孕] 安排 ASMR 请求失败：%s", error)
            self._schedule_notice(fallback, "受孕·助眠", "asmr_request")

    def _sleep_inside_detect(self, text: str) -> None:
        mode = sleep_inside.detect_mode(text, self.state, self.settings)
        if mode:
            self.state["sleep_inside_mode_hint"] = mode

    def _cycle_request(self, text: str) -> None:
        body = str(text or "")
        if any(word in body for word in ("生理期", "月经", "姨妈", "经期", "周期",
                                         "第几天", "排卵", "黄体", "卵泡", "安全期")):
            self.state["cycle_prompt_now"] = True

    def _children_request(self, text: str) -> None:
        if not self.settings.bool("children.prompt_on_request"):
            return
        body = str(text or "")
        if any(word in body for word in ("孩子", "宝宝", "儿子", "女儿", "小孩", "娃")):
            self.state["children_prompt_now"] = True

    def _asmr_known_words(self) -> list[str]:
        stored = self.state.get("asmr_known_keywords")
        if isinstance(stored, list):
            words = [str(word).strip() for word in stored if str(word).strip()]
            if words:
                return words
        return self.settings.list("asmr.known_keywords") or ["助眠", "ASMR", "asmr", "哄睡"]

    def _asmr_learn(self, text: str) -> None:
        body = str(text or "")
        if not body:
            return
        words = self._asmr_known_words()
        if any(word in body for word in words):
            if not self.state.get("asmr_known"):
                self.state["asmr_known"] = True
                state_mod.append_log(self.state, "asmr", "她知道主人愿意给她助眠")
                self._save()

    def _asmr_wake(self, text: str) -> bool:
        if not str(text or "").strip():
            return False
        asleep = self.state.get("asmr_asleep")
        if not isinstance(asleep, dict) or not asleep:
            return False
        body = str(text)
        wake_words = ("醒醒", "醒来", "起床", "叫醒", "别睡", "起来")
        gentle_words = ("亲", "吻", "摸摸头", "摸头", "抱", "揉", "蹭", "拍")
        if self._match_any(body, wake_words):
            self.state.pop("asmr_asleep", None)
            self._asmr_note("（她被叫醒了，慢慢睁开眼，声音还带着困意。）")
            self._save()
            return True
        if self._match_any(body, gentle_words):
            line = prompts.text(self.state, "asmr", "asleep_gentle")
            if line:
                self._asmr_note(line)
            self._save()
        return False

    def _asmr_response(self, text: str) -> bool:
        row = asmr.data(self.state)
        until = util.safe_float(row.get("request_until"), 0.0)
        if not until or until <= util.now_ts() or not str(text or "").strip():
            return False
        row["request_until"] = 0.0
        info = asmr.start(self.state, self.settings, minutes=asmr.duration(
            self.state, self.settings))
        if info.get("ok"):
            self.state["asmr_known"] = True
            self.state["asmr_done_night"] = self._asmr_night_key()
            self.state.pop("asmr_pc_noted", None)
            self._asmr_note(info.get("line") or "")
            self._sleep_note()
            self._asmr_allow_speech()
            state_mod.append_log(self.state, "asmr", "回应请求，开始助眠")
        self._save()
        return bool(info.get("ok"))

    def _children_memory_tick(self) -> None:
        children.prune(self.state)
        pending = self.state.get("children_adult_pending")
        if not isinstance(pending, list) or not pending:
            return
        destination = str(self.settings.str("children.adult_destination")
                          or "已经独立生活、自己成家了")
        for row in list(pending):
            sex = str(row.get("sex") or "孩子")
            memory_link.write_child_fact(
                self.context, self.settings,
                value=f"我的{sex}孩子满 20 岁了，{destination}，从孩子列表里移出。",
                reason="受孕·孩子成年")
            self.state["children_adult_count"] = util.safe_int(
                self.state.get("children_adult_count"), 0) + 1
            state_mod.append_log(self.state, "children",
                                 f"{sex}孩子满 20 岁，{destination}")
        self.state["children_adult_pending"] = []

    def _sleepwear_tick(self) -> None:
        """到点自己换睡衣，早上换回日常服。只在没有活动时做。"""
        if type(self.context).__name__ == "StubContext":
            return
        if not self.settings.bool("clothing.auto_sleepwear"):
            return
        if not clothing.enabled(self.settings):
            return
        if state_mod.scene_active(self.state, self.settings) or \
                state_mod.daily_active(self.state, self.settings):
            return
        now = datetime.now()
        hour = now.hour
        if 8 <= hour < 18:
            self.state["sleepwear_pending"] = {}
        night_hour = max(0, min(23, self.settings.int("clothing.sleepwear_night_hour", 0, 23)))
        morning_hour = max(0, min(23, self.settings.int("clothing.sleepwear_morning_hour", 0, 23)))
        top = clothing.worn(self.state, self.settings).get("top", {}).get("key", "")
        bottom = clothing.worn(self.state, self.settings).get("bottom", {}).get("key", "")
        day = now.strftime("%Y-%m-%d")
        is_night = hour >= night_hour or hour < 6
        needs_night = top not in ("pajamas", "nightgown") or (
            top == "pajamas" and bottom != "pajama_pants")
        if is_night and needs_night and self.state.get("sleepwear_asked_day") != day \
                and not self._proactive_deferred("sleepwear_ask"):
            saved = {slot: value for slot, value in clothing.data(self.state, self.settings).items()
                     if slot in clothing.SLOTS and value and slot != "coat"}
            self.state["sleepwear_saved"] = saved
            self.state["sleepwear_asked_day"] = day
            self.state["sleepwear_pending"] = {"at": util.now_ts(), "day": day}
            line = prompts.text(self.state, "clothing", "sleepwear_ask")
            say = prompts.text(self.state, "clothing", "sleepwear_ask_say") or line
            self.state["sleepwear_note"] = {
                "at": util.now_ts(), "key": "sleepwear_ask", "line": line}
            state_mod.append_log(self.state, "clothing", "到点问她今晚要不要换睡衣")
            chance = self.settings.float("clothing.sleepwear_notice_chance", 0.0, 100.0)
            if chance > 0 and random.random() * 100 < chance:
                self._schedule_notice(
                    say, "受孕·衣装", "sleepwear_ask", judge=True,
                    rollback=lambda: (
                        self.state.pop("sleepwear_asked_day", None),
                        self.state.pop("sleepwear_pending", None),
                        self.state.pop("sleepwear_note", None)))
        elif (hour >= morning_hour and not is_night
              and top in ("pajamas", "nightgown")
              and self.state.get("sleepwear_morning_day") != day):
            saved = self.state.get("sleepwear_saved")
            restored = 0
            if isinstance(saved, dict):
                for slot, value in saved.items():
                    if slot in clothing.SLOTS and value:
                        if clothing.wear(self.state, self.settings, slot, value).get("ok"):
                            restored += 1
            if not restored:
                clothing.wear(self.state, self.settings, "top",
                              str(clothing.DEFAULT_OUTFIT.get("top") or "shirt"))
            self.state["sleepwear_morning_day"] = day
            self.state["sleepwear_pending"] = {}
            self.state["sleepwear_note"] = {
                "at": util.now_ts(), "key": "pajamas_morning",
                "line": prompts.text(self.state, "clothing", "pajamas_morning")}
            state_mod.append_log(self.state, "clothing", "早上换下睡衣，穿回日常服")
            self._announce_sleepwear_change(self.state["sleepwear_note"]["line"])

    def _begin_outfit_change(self, items: list[tuple[str, str]], label: str,
                             *, immediate: bool = False, undress: bool = False,
                             refresh_slots: list[str] | None = None) -> str:
        """记下一次换衣；有耗时就先挂着，到点由 _outfit_change_tick 穿上。"""
        key = "clothing.undress_minutes" if undress else "clothing.change_minutes"
        minutes = max(0, self.settings.int(key, 0, 60))
        if immediate or type(self.context).__name__ == "StubContext":
            minutes = 0
        if minutes <= 0:
            self._apply_outfit_change(items, label, refresh_slots=refresh_slots)
            return f"换好了：{label}"
        self.state["clothing_change"] = {
            "at": util.now_ts(), "until": util.now_ts() + minutes * 60,
            "items": [[slot, key] for slot, key in items], "label": label,
            "refresh": list(refresh_slots or [])}
        self._save()
        return f"开始换{label}，大约 {minutes} 分钟"

    def _apply_outfit_change(self, items: list[tuple[str, str]], label: str,
                             *, refresh_slots: list[str] | None = None) -> str:
        lines = []
        errors = []
        for slot, key in items:
            if refresh_slots and slot in refresh_slots:
                continue
            info = clothing.wear(self.state, self.settings, slot, key) if key else \
                clothing.remove(self.state, self.settings, slot)
            if info.get("ok"):
                if info.get("line"):
                    lines.append(info["line"])
            else:
                errors.append(str(info.get("reason") or "换不了"))
        for slot in (refresh_slots or []):
            info = clothing.refresh(self.state, self.settings, slot)
            if info.get("ok") and info.get("line"):
                lines.append(info["line"])
        line = " ".join(lines) or f"换好了：{label}"
        if errors:
            line = "；".join(errors)
        self.state["clothing_note"] = {"at": util.now_ts(), "line": line}
        self._save()
        return line

    def _outfit_change_tick(self) -> None:
        row = self.state.get("clothing_change")
        if not isinstance(row, dict) or not row:
            return
        if util.safe_float(row.get("until"), 0.0) > util.now_ts():
            return
        items = [(str(slot), str(key)) for slot, key in (row.get("items") or [])]
        label = str(row.get("label") or "")
        refresh_slots = [str(slot) for slot in (row.get("refresh") or [])]
        self.state["clothing_change"] = {}
        self._apply_outfit_change(items, label, refresh_slots=refresh_slots)
        state_mod.append_log(self.state, "clothing", f"换好衣服：{label}")

    def _choose_sleepwear(self, style: str) -> str:
        """按她的选择换睡衣/睡裙/不换；不选就保持原样。"""
        style = str(style or "").strip().lower()
        style = {"sleepwear": "pajamas", "pajama": "pajamas",
                 "gown": "nightgown", "none": "skip", "no": "skip"}.get(style, style)
        if style not in ("pajamas", "nightgown", "skip"):
            return "要选睡衣、睡裙，或者今晚不换"
        day = datetime.now().strftime("%Y-%m-%d")
        if style == "skip":
            self.state["sleepwear_asked_day"] = day
            self.state["sleepwear_pending"] = {}
            line = prompts.text(self.state, "clothing", "sleepwear_skip")
            self.state["sleepwear_note"] = {
                "at": util.now_ts(), "key": "sleepwear_skip", "line": line}
            state_mod.append_log(self.state, "clothing", "今晚不换睡衣")
            self._save()
            return line or "那今晚先不换"
        saved = self.state.get("sleepwear_saved")
        if not isinstance(saved, dict) or not saved:
            saved = {slot: value for slot, value in clothing.data(self.state, self.settings).items()
                     if slot in clothing.SLOTS and value and slot != "coat"}
            self.state["sleepwear_saved"] = saved
        row = clothing.data(self.state, self.settings)
        if style == "nightgown" and not (row.get("bra") and row.get("underwear")):
            return "睡裙里面要先穿好内衣和内裤"
        result = clothing.wear(self.state, self.settings, "top", style)
        if not result.get("ok"):
            return f"换不了：{result.get('reason') or ''}"
        if style == "pajamas":
            clothing.wear(self.state, self.settings, "bottom", "pajama_pants")
        if str(clothing.worn(self.state, self.settings).get("feet", {}).get("key") or "") != "slippers":
            clothing.wear(self.state, self.settings, "feet", "slippers")
        self.state["sleepwear_asked_day"] = day
        self.state["sleepwear_night_day"] = day
        self.state["sleepwear_pending"] = {}
        key = "nightgown_wear" if style == "nightgown" else "pajamas_night"
        line = prompts.text(self.state, "clothing", key)
        self.state["sleepwear_note"] = {
            "at": util.now_ts(), "key": key, "line": line}
        state_mod.append_log(self.state, "clothing",
                             f"她选了{'睡裙' if style == 'nightgown' else '睡衣睡裤'}")
        self._announce_sleepwear_change(line)
        self._save()
        return line or ("换好睡裙了" if style == "nightgown" else "换好睡衣睡裤了")

    def _announce_sleepwear_change(self, line: str) -> None:
        """换睡衣/睡裙时告知；有概率被看见，被看见加羞耻/欲望/湿润。"""
        seen = False
        seen_line = ""
        chance = self.settings.float("clothing.sleepwear_seen_chance", 0.0, 100.0)
        if chance > 0 and random.random() * 100 < chance:
            seen = True
            mood.adjust(self.state, self.settings, "shame",
                        delta=self.settings.float("clothing.sleepwear_seen_shame", 0.0, 100.0))
            mood.adjust(self.state, self.settings, "desire",
                        delta=self.settings.float("clothing.sleepwear_seen_desire", 0.0, 100.0))
            wetness.gain(self.state, self.settings,
                         extra=self.settings.float("clothing.sleepwear_seen_wet", 0.0, 100.0))
            fish_gain = self.settings.float("clothing.sleepwear_seen_fish_desire", 0.0, 100.0)
            if fish_gain > 0 and self._fish_write_on():
                try:
                    boost.boost_fish_desire(self.context, self.settings, fish_gain, enabled=True)
                except Exception as error:
                    logger.warning("[受孕] 写鱼之心「欲」失败：%s", error)
            seen_line = prompts.text(self.state, "clothing", "sleepwear_seen")
            if seen_line:
                self.state["sleepwear_seen"] = {"at": util.now_ts(), "line": seen_line}
                line = f"{line}\n{seen_line}" if line else seen_line
            state_mod.append_log(self.state, "clothing", "换衣服时被看见了")
        notice = self.settings.float("clothing.sleepwear_notice_chance", 0.0, 100.0)
        if line and (seen or (notice > 0 and random.random() * 100 < notice)):
            self._schedule_notice(line, "受孕·衣装", "sleepwear_change")

    def _auto_edge_tick(self) -> None:
        """忍耐满了却一直没高潮：过一段时间自动算一次寸止。"""
        if not endurance.enabled(self.settings):
            self.state.pop("endurance_full_since", None)
            self.state.pop("endurance_auto_edge_done", None)
            return
        if not endurance.is_full(self.state, self.settings):
            self.state.pop("endurance_full_since", None)
            self.state.pop("endurance_auto_edge_done", None)
            return
        if self.state.get("endurance_auto_edge_done"):
            return
        minutes = max(0, self.settings.int("edge.auto_full_minutes", 0, 240))
        if minutes <= 0:
            return
        now = util.now_ts()
        since = util.safe_float(self.state.get("endurance_full_since"), 0.0)
        if not since:
            self.state["endurance_full_since"] = now
            return
        if now - since < minutes * 60:
            return
        info = state_mod.add_edge(self.state, self.settings, now=now)
        self.state["endurance_auto_edge_done"] = True
        state_mod.append_log(
            self.state, "edge",
            f"忍耐满了 {minutes} 分钟没高潮，自动算一次寸止"
            f"（层数 {info.get('stack', 0)}，渴求 {info.get('craving', 0):.0f}）")

    def _tick(self) -> None:
        """轻量日常维护：快感衰减、到点生产、周期暂停兜底。"""
        state_mod.decay_pleasure(self.state, self.settings)
        lewd.settle(self.state, self.settings)
        self._auto_edge_tick()
        self._maybe_self_toy()
        self._pill_offer_tick()
        self._asmr_tick()
        self._asmr_request_tick()
        self._unbirth_request_tick()
        self._unbirth_overnight_invite_tick()
        self._unbirth_overnight_request_tick()
        self._sleep_inside_overnight_request_tick()
        self._outfit_change_tick()
        self._sleepwear_tick()
        menses = menstrual.tick(self.state, self.settings,
                                phase=(self._cycle() or {}).get("phase"))
        if menses.get("pre_notice"):
            chance = self.settings.float("menstrual.pad_notice_chance", 0.0, 100.0)
            if random.random() * 100 < chance:
                self._schedule_notice(menses["pre_notice"], "受孕·生理期", "pad_change")
        if menses.get("changed"):
            line = menses.get("line") if menses.get("seen") else menses.get("notice")
            chance = self.settings.float("menstrual.pad_notice_chance", 0.0, 100.0)
            if line and random.random() * 100 < chance:
                self._schedule_notice(line, "受孕·生理期", "pad_change")
        self._children_memory_tick()
        self._night_raid_tick()
        self._sync_pregnancy_stage()
        self._birth_tick()
        self._maybe_deliver()
        self._ensure_pc_cycle_state()
        self._save()

    def _combo_limit(self) -> int:
        """连续高潮"几连之后算过头"的上限（面板 ± 改的就是这个）。"""
        value = tuning.get(self.state, "combo", "overstim_after",
                           self.settings.int("combo.overstim_after", 1, 20))
        return int(max(1, min(20, util.safe_int(value, 3))))

    def _birth_tick(self, notify: bool = True) -> dict:
        """推进生产阶段；阶段变化主动发一条（不受睡眠限制）。"""
        if not birth.enabled(self.settings):
            return {}
        info = birth.tick(self.state, self.settings)
        for event in info.get("events") or []:
            state_mod.append_log(self.state, "birth",
                                 f"{event.get('label') or event.get('stage')}"
                                 f"{('：' + event['line']) if event.get('line') else ''}")
            if notify and event.get("line"):
                self._schedule_notice(event["line"], "受孕·生产", "birth")
        if birth.needs_finish(self.state):
            result = self._finish_pregnancy(reason="生产", trigger="生产完成")
            birth.mark_finished(self.state)
            state_mod.append_log(self.state, "birth", "生产完成，进入产后恢复")
            if notify:
                line = prompts.text(self.state, "birth", "done")
                if result.get("sex_text"):
                    line += "\n" + prompts.text(
                        self.state, "birth", "reveal",
                        sex_text=result["sex_text"])
                self._schedule_notice(line, "受孕·生产", "birth_done")
            return {"finished": True, "result": result, **info}
        if info.get("changed"):
            self._save()
        return info

    def _maybe_deliver(self) -> None:
        if birth.enabled(self.settings) and (birth.in_progress(self.state)
                                             or birth.stage_of(self.state) == "done"):
            return
        prog = pregnancy.progress(self.state)
        if prog and prog["overdue"]:
            self._finish_pregnancy(reason="生产", trigger="到期")

    def _finish_pregnancy(self, *, reason: str, trigger: str = "") -> dict:
        info = pregnancy.end_pregnancy(self.state, self.settings, reason=reason)
        # 周期恢复：PC 的锚点后移；插件自己的周期从今天重新开始
        cycle_msg = ""
        if self.settings.bool("pregnancy.suppress_pc_cycle"):
            result = pc_cycle.restore(self.settings)
            if not result.get("ok"):
                logger.warning("[受孕] 恢复 PC 周期失败：%s", result.get("reason"))
            cycle_msg = result.get("reason", "")
        self.state.setdefault("own_cycle", {})["anchor_date"] = util.today().isoformat()
        self._cycle_cache = None      # 周期刚恢复，别让缓存里的旧相位顶 60 秒
        fetuses = int(info.get("fetuses") or 1)
        extra = f"，{fetuses} 胎" if fetuses > 1 else ""
        if info.get("hymen_intact") and self.settings.bool("hymen.intact_birth"):
            extra += "，处女膜完整"
        text = (f"{reason}：孕 {info['days']} 天（{info['conceived'].isoformat()} → "
                f"{util.today().isoformat()}）{extra}")
        if info.get("sex_text"):
            text += f"；出生 {info['sex_text']}"
        if info.get("sexes"):
            born = children.add_birth(self.state, self.settings,
                                      info.get("sexes") or [])
            total = util.safe_int(self.state.get("children_born_total"), 0)
            for row in born:
                care = children.CARE_LABELS.get(
                    str(row.get("care_mode") or "family"), "家人带")
                memory_link.write_child_fact(
                    self.context, self.settings,
                    value=f"我的{row.get('sex') or '孩子'}出生了，{care}；这是第 {total} 个孩子。",
                    reason="受孕·孩子出生")
            roster = children.summary(self.state, self.settings)
            if roster:
                text += f"；孩子：{roster}"
        state_mod.append_log(self.state, "delivery", text)
        self.state["pc_stage_key"] = ""
        try:
            pc_state.clear_pregnancy(self.settings)
        except Exception as error:
            logger.warning("[受孕] 清除 PC 孕期状态失败：%s", error)
        self._save()
        logger.info("[受孕] %s；%s", text, cycle_msg or "周期未处理")
        return info

    def _ensure_pc_cycle_state(self) -> None:
        """孕期把 PC 周期持续压成 not_applicable；结束后若还有残留备份就还原。"""
        if not self.settings.bool("pregnancy.suppress_pc_cycle"):
            return
        now = time.time()
        if now - self._pc_checked_at < SUPPRESS_RECHECK_SECONDS:
            return
        self._pc_checked_at = now
        pregnant = pregnancy.is_pregnant(self.state)
        preg = self.state.get("pregnancy") if isinstance(self.state.get("pregnancy"), dict) else {}
        try:
            if pregnant:
                if not self.settings.bool("pregnancy.pc_write_enabled"):
                    preg["cycle_suppressed"] = False   # 只靠提示词，别谎报已暂停
                elif self._write_paused():
                    preg["cycle_suppressed"] = True
                else:
                    result = pc_cycle.suppress(self.settings)
                    if result.get("ok"):
                        preg["cycle_suppressed"] = True
                        if result.get("mode") != "already":
                            logger.info("[受孕] 已暂停 private_companion 的月经周期")
                    else:
                        preg["cycle_suppressed"] = False
                        logger.warning("[受孕] 暂停 PC 周期失败（用提示词兜底）：%s",
                                       result.get("reason"))
            elif pc_cycle.has_backup():
                # 孕期记录被外部清掉了，别让 PC 周期一直停着
                result = pc_cycle.restore(self.settings)
                logger.info("[受孕] 清理残留的周期暂停：%s", result.get("reason"))
        except Exception as error:
            logger.warning("[受孕] 周期状态维护失败：%s", error)

    def _write_paused(self) -> bool:
        try:
            return pc_cycle.is_suppressed(self.settings)
        except Exception:
            return False

    # ================================================================ 概率与受孕

    def _probability(self, data: dict, cycle: dict, *, inside: bool,
                     orgasm_recent: bool | None = None) -> fertility.Probability:
        if orgasm_recent is None:
            orgasm_recent = state_mod.orgasm_recent(self.state, self.settings)
        fish_factor = data["fish_factor"][0]
        dark_factor = data["dark_factor"][0]
        mood_factor = 1.0
        mode = desire.strategy(self.state, self.settings, "conception")
        if mode == "fish":
            dark_factor = 1.0
        elif mode == "dark":
            fish_factor = 1.0
        elif mode in ("mood", "max"):
            fish_value = float(getattr(data.get("fish"), "desire", 0.0) or 0.0)
            dark_value = float(getattr(data.get("dark"), "lust", 0.0) or 0.0)
            mood_value = mood.value_of(self.state, self.settings, "desire")
            source = {"mood": mood_value, "fish": fish_value, "dark": dark_value}
            if mode == "max":
                best = max(source, key=source.get) if source else "mood"
                fish_factor = 1.0
                dark_factor = 1.0
                if best == "fish":
                    fish_factor = data["fish_factor"][0]
                elif best == "dark":
                    dark_factor = data["dark_factor"][0]
                else:
                    mood_factor = 1.0 + self.settings.float(
                        "conception.mood_desire_weight", 0.0, 5.0) * mood_value / 100.0
            else:
                fish_factor = 1.0
                dark_factor = 1.0
                mood_factor = 1.0 + self.settings.float(
                    "conception.mood_desire_weight", 0.0, 5.0) * mood_value / 100.0
        p = fertility.compute(
            self.settings,
            phase=str(cycle.get("phase") or "unknown"),
            fish_factor=fish_factor,
            dark_factor=dark_factor,
            pleasure=util.safe_float(self.state.get("pleasure"), 0.0),
            orgasms=state_mod.session_orgasms(self.state, self.settings),
            inside=inside,
            orgasm_recent=bool(orgasm_recent),
        )
        if mood_factor != 1.0:
            p.probability = round(p.probability * mood_factor, 3)
            p.factors["mood_desire"] = round(mood_factor, 3)
        if inside:
            session = self.state.get("session") if isinstance(self.state.get("session"), dict) else {}
            count = max(0, util.safe_int(session.get("ejaculations"), 0))
            count_cap = max(1, self.settings.int("conception.ejaculation_count_cap", 1, 20))
            count_factor = 1.0 + min(max(0, count - 1), count_cap) * \
                self.settings.float("conception.ejaculation_count_weight", 0.0, 5.0)
            last_ej = util.safe_float(self.state.get("last_ejaculation_at"), 0.0)
            session_timeout = max(60, self.settings.int(
                "pleasure.session_timeout_minutes", 1, 1440)) * 60
            has_ejaculation = bool(
                last_ej and util.now_ts() - last_ej <= session_timeout and count > 0)
            volume = util.safe_float(
                self.state.get("last_ejaculation_volume"), 0.0) if has_ejaculation else 0.0
            volume_cap = max(0.1, self.settings.float("conception.volume_cap", 0.1, 100.0))
            volume_factor = 1.0 + min(max(0.0, volume), volume_cap) * \
                self.settings.float("conception.volume_weight", 0.0, 1.0)
            sim_window = max(0, self.settings.int(
                "conception.simultaneous_window_seconds", 0, 600))
            last_orgasm = util.safe_float(self.state.get("last_orgasm_at"), 0.0)
            sim = bool(
                last_orgasm and last_ej and sim_window
                and abs(last_ej - last_orgasm) <= sim_window)
            sim_cap = max(0.0, self.settings.float("conception.simultaneous_cap", 0.0, 5.0))
            sim_factor = 1.0 + min(
                sim_cap, self.settings.float("conception.simultaneous_weight", 0.0, 5.0)) if sim else 1.0
            if count_factor != 1.0:
                p.probability = round(p.probability * count_factor, 3)
                p.factors["ejaculation_count"] = round(count_factor, 3)
                p.notes.append(f"同一次活动已射 {count} 次（×{count_factor:.2f}）")
            if volume_factor != 1.0:
                p.probability = round(p.probability * volume_factor, 3)
                p.factors["ejaculation_volume"] = round(volume_factor, 3)
                p.notes.append(f"本次精液量 {volume:.1f} ml（×{volume_factor:.2f}）")
            if sim_factor != 1.0:
                p.probability = round(p.probability * sim_factor, 3)
                p.factors["simultaneous"] = round(sim_factor, 3)
                p.notes.append(f"高潮同时被射（×{sim_factor:.2f}）")
            if sleep_inside.active(self.state):
                try:
                    semen = max(0.0, util.safe_float(
                        fill.volume(self.state, self.settings).get("semen_ml"), 0.0))
                except Exception:
                    semen = 0.0
                if semen > 0:
                    started = util.safe_float(
                        (self.state.get("sleep_inside") or {}).get("started_at"), 0.0)
                    hours = max(0.0, (util.now_ts() - started) / 3600.0) if started else 0.0
                    amt_cap = max(0.1, self.settings.float(
                        "conception.sleep_semen_volume_cap", 0.1, 100.0))
                    time_cap = max(0.1, self.settings.float(
                        "conception.sleep_semen_time_cap_hours", 0.1, 24.0))
                    bonus = max(0.0, self.settings.float(
                        "conception.sleep_semen_bonus", 0.0, 5.0))
                    amount_ratio = min(1.0, semen / amt_cap)
                    time_ratio = min(1.0, hours / time_cap)
                    sleep_factor = 1.0 + bonus * amount_ratio * time_ratio
                    if sleep_factor != 1.0:
                        p.probability = round(p.probability * sleep_factor, 3)
                        p.factors["sleep_semen"] = round(sleep_factor, 3)
                        p.notes.append(
                            f"插着入睡、子宫内有精液（{semen:.1f} ml，×{sleep_factor:.2f}）")
        # 产后两段式：低概率窗口里把概率按倍率压低（面板和掷骰用同一个数）
        if inside and self.settings.bool("pregnancy.postpartum_no_conception"):
            stage = pregnancy.postpartum_stage(self.state, self.settings)
            if stage and stage.get("key") == "low":
                scale = util.clamp(util.safe_float(stage.get("scale"), 0.0), 0.0, 1.0)
                if scale < 1.0:
                    p.probability = round(min(15.0, p.probability * scale), 2)
                    p.factors["postpartum"] = scale
                    p.notes.append(f"产后恢复期，概率被压低到 ×{scale:.2f}")
        if inside:
            factor, notes = body.contraception_multiplier(self.state, self.settings)
            if factor < 1.0:
                p.probability = round(p.probability * factor, 2)
                p.factors["contraception"] = factor
                p.notes.extend(notes)
            if succubus.enabled(self.state, self.settings):
                factor, note = succubus.conception_factor(self.state, self.settings)
                if abs(factor - 1.0) > 1e-9:
                    p.probability = round(p.probability * factor, 3)
                    p.factors["succubus"] = factor
                    p.notes.append(f"{note}（×{factor:.3f}）")
        max_p = self.settings.float("conception.max_probability", 0.0, 100.0)
        p.probability = round(min(max_p, max(0.0, p.probability)), 2)
        p.factors["max_probability"] = max_p
        return p

    def _start_pregnancy(self, probability: float, trigger: str) -> dict:
        preg = pregnancy.start_pregnancy(self.state, self.settings,
                                         trigger=trigger, probability=probability)
        # 先把"受孕"落盘，再动 PC 的库：中途失败也不会出现"周期停了但没怀孕"
        self._save()
        fetuses = int(preg.get("fetuses") or 1)
        label = f"，{fetuses} 胎" if fetuses > 1 else ""
        text = (f"受孕成功（触发：{trigger or '未知'}，当时概率 {probability:.1f}%）{label}；"
                f"预产期 {preg['due_date']}")
        state_mod.append_log(self.state, "conception", text)
        logger.info("[受孕] %s", text)
        try:
            if self.settings.bool("pregnancy.backup_pc_db"):
                result = pc_cycle.backup_db(self.settings)
                if result.get("ok"):
                    logger.info("[受孕] 已备份 private_companion 的库：%s", result.get("path"))
                elif result.get("reason") != "配置里关掉了备份":
                    logger.warning("[受孕] 备份 PC 库失败：%s", result.get("reason"))
            if self.settings.bool("pregnancy.suppress_pc_cycle") and \
                    self.settings.bool("pregnancy.pc_write_enabled"):
                result = pc_cycle.suppress(self.settings)
                if result.get("ok"):
                    self.state["pregnancy"]["cycle_suppressed"] = True
                    logger.info("[受孕] 已暂停 private_companion 的月经周期")
                else:
                    logger.warning("[受孕] 暂停 PC 周期失败（靠提示词兜底）：%s",
                                   result.get("reason"))
        except Exception as error:
            logger.warning("[受孕] 处理 PC 周期时出错：%s", error)
        bonus = self._succubus_conception_bonus()
        if bonus:
            logger.info("[受孕] %s", bonus.get("text", ""))
        self._save()
        self._cycle_cache = None
        self._sync_pregnancy_stage(force=True)
        return preg

    def _sync_pregnancy_stage(self, *, force: bool = False) -> None:
        """月份/阶段变了就把孕期写进 PC 状态（尽力而为，失败不影响插件）。"""
        prog = pregnancy.progress(self.state)
        if not prog:
            # 孕期结束、流产、或 state.json 被重置/清空时，PC 里的「怀孕」条件
            # 不会自己消失，必须在这里补一刀：不清的话陪伴插件会一直带着它，
            # 模型也会照「怀孕」演（旧版本还会因为它是字符串而整段状态降级）。
            if self.state.get("pc_stage_key"):
                self.state["pc_stage_key"] = ""
            try:
                result = pc_state.clear_pregnancy(self.settings)
                reason = str((result or {}).get("reason") or "")
                if result and not result.get("ok") and reason not in ("本来就没有", "没有 PC 角色记录"):
                    # 写库失败（revision 冲突/库忙）以前是静默的，标记会一直留着
                    logger.warning("[受孕] 清理 PC 孕期标记未成功：%s", reason)
            except Exception as error:
                logger.warning("[受孕] 清理 PC 孕期标记失败：%s", error)
            return
        stage = prog["stage"]
        key = f"{prog['month']}:{stage['key']}"
        if not force and str(self.state.get("pc_stage_key") or "") == key:
            return
        self.state["pc_stage_key"] = key
        try:
            result = pc_state.sync_pregnancy(
                self.settings, prog["month"], stage["title"],
                int(prog.get("fetuses") or 1))
            if not result.get("ok"):
                logger.info("[受孕] PC 孕期状态未写入：%s", result.get("reason"))
        except Exception as error:
            logger.warning("[受孕] 写 PC 孕期状态出错：%s", error)
        if self.settings.bool("pregnancy.stage_energy_enabled"):
            delta = int(stage.get("energy") or 0)
            if delta:
                try:
                    pc_state.adjust_energy(self.settings, delta)
                except Exception as error:
                    logger.warning("[受孕] 调整 PC 精力失败：%s", error)

    def _roll_conception(self, *, inside: bool, trigger: str,
                         scale: float = 1.0) -> dict:
        """掷一次受孕骰。返回 {"p": Probability, "hit": bool, ...}。"""
        prog = pregnancy.progress(self.state)
        if prog:
            return {"pregnant": True, "rolled": False, "hit": False,
                    "reason": f"已在孕期（第 {prog['month']} 个月）"}
        if inside and self.settings.bool("pregnancy.postpartum_no_conception"):
            stage = pregnancy.postpartum_stage(self.state, self.settings)
            if stage and stage.get("key") == "hard":
                until = pregnancy.postpartum_until_text(self.state)
                self.state["last_roll"] = {
                    "at": util.now_ts(), "probability": 0.0, "hit": False,
                    "phase": (self._cycle() or {}).get("phase"), "inside": True,
                    "blocked": "postpartum_hard",
                }
                self._save()
                where = f"（大约到 {until}）" if until else ""
                return {"rolled": False, "hit": False, "postpartum": True,
                        "postpartum_stage": "hard",
                        "reason": f"产后前 {stage['hard_days']} 天{where}，这段时间不会受孕"}
        if not inside:
            p = self._probability(self._read_sources(), self._cycle(), inside=False,
                                  orgasm_recent=False)
            self.state["last_roll"] = {
                "at": util.now_ts(), "probability": 0.0, "hit": False,
                "phase": p.phase, "inside": False,
            }
            self._save()
            return {"p": p, "hit": False, "rolled": False, "reason": "体外"}

        data = self._read_sources()
        cycle = self._cycle()
        p = self._probability(data, cycle, inside=True)
        if scale != 1.0:
            p.probability = round(max(0.0, p.probability * max(0.0, scale)), 3)
            p.factors["route_scale"] = scale
        self.state["conception_attempts"] = util.safe_int(
            self.state.get("conception_attempts"), 0) + 1
        hit = random.random() < p.ratio
        self.state["last_roll"] = {
            "at": util.now_ts(), "probability": round(p.probability, 2), "hit": bool(hit),
            "phase": p.phase, "inside": True, "factors": p.factors,
        }
        if hit:
            self._start_pregnancy(p.probability, trigger)
        else:
            state_mod.append_log(
                self.state, "roll",
                f"未受孕（{trigger or '未知'}，概率 {p.probability:.1f}%）")
        self._save()
        return {"p": p, "hit": bool(hit), "rolled": True}

    # ================================================================ 事件记录

    def _record_pleasure(self, amount: float, trigger: str) -> dict | None:
        ok, why = self._gate()
        if not ok:
            return {"refused": why}
        self._surprise_note("pleasure")
        self._touch_scene("快感")
        combo_on = self.settings.bool("combo.enabled")
        painful = combo_on and state_mod.overstimulated(self.state)
        amount = amount * body.pleasure_scale(self.settings, self.state)
        if painful:
            amount = amount * self.settings.float("combo.pain_gain_scale", 0.0, 1.0)
        craving = state_mod.edge_gain_multiplier(self.state, self.settings)
        if craving > 1.0:
            amount = amount * craving
        cap = self.settings.float("pleasure.max", 1.0, 1000.0)
        before = util.safe_float(self.state.get("pleasure"), 0.0)
        full_before = endurance.is_full(self.state, self.settings)
        value = state_mod.add_pleasure(self.state, self.settings, amount)
        if painful:
            state_mod.append_log(self.state, "pleasure",
                                 f"快感 +{amount:.0f}（难受中，涨得很慢）："
                                 f"{before:.0f} → {value:.0f}（{trigger}）")
        elif craving > 1.0:
            state_mod.append_log(self.state, "pleasure",
                                 f"快感 +{amount:.0f}（被寸止得渴，涨得更快 ×{craving:.2f}）："
                                 f"{before:.0f} → {value:.0f}（{trigger}）")
        else:
            state_mod.append_log(self.state, "pleasure",
                                 f"快感 +{amount:.0f}：{before:.0f} → {value:.0f}（{trigger}）")
        self._sleep_note()
        self._size_float_note()
        self._maybe_size_notice()
        self._gain_wetness(pleasure=max(0.0, amount))
        orgasm = self._endurance_orgasm(trigger, was_full=full_before)
        self._save()
        return {"before": before, "value": value, "cap": cap, "pain": painful,
                "rest": state_mod.rest_remaining(self.state) if painful else 0,
                "endurance": endurance.payload(self.state, self.settings),
                "wetness": self._wetness_payload(),
            "sleep": {**sleepy.awake_payload(self.state, self.settings),
                      "note": sleepy.sleeping(self.settings)},
            "surprise": surprise.payload(self.state, self.settings),
            "memory": {**memory_link.available(self.context),
                       "write": memory_link.write_enabled(self.settings),
                       "bridge": bool(memory_link.bridge_tag(
                           getattr(self.store, "path", ""))),
                       "written": bool(util.safe_float(self.state.get("memory_written_at"), 0.0))},
                "orgasm": orgasm}

    def _wake_after_orgasm(self) -> None:
        """高潮会把她弄醒：清掉助眠睡着标记，并尽量给 PC 留出醒着的窗口。"""
        self.state.pop("asmr_asleep", None)
        try:
            info = sleepy.sleeping(self.settings)
            if not info.get("sleeping", info.get("asleep")):
                return
        except Exception:
            return
        now = util.now_ts()
        sleep_id = str(info.get("sleep_id") or "")
        minutes = max(1, self.settings.int("sleep.wake_grace_minutes", 1, 240))
        try:
            sleepy.note_activity(self.state, self.settings, now=now)
        except Exception:
            pass
        self.state["sleep_awake_until"] = now + minutes * 60
        self.state["sleep_awake_sleep"] = sleep_id
        self.state["sleep_awake_at"] = now
        self.state["sleep_in_event"] = True
        if sleep_id:
            try:
                sleepy.mark_gate_awake(self.settings, sleep_id=sleep_id,
                                       minutes=minutes, now=now)
            except Exception as error:
                logger.warning("[受孕] 高潮唤醒 PC 失败：%s", error)

    def _schedule_orgasm_message(self, note: str) -> None:
        """高潮后让她自己发一条；生成失败就不发，不退回固定模板。"""
        if not self.settings.bool("orgasm.message_enabled"):
            return
        if type(self.context).__name__ == "StubContext":
            return
        umo = str(getattr(self, "_last_umo", "") or "")
        if not umo:
            logger.info("[受孕] 高潮消息没有可发送的私聊会话（重启后还没收到过私聊）")
            return
        if not note:
            return

        async def job() -> None:
            text = await self._compose_proactive(note)
            if not text:
                logger.info("[受孕] 高潮消息未生成，跳过发送")
                return
            await self._send_notice_later(umo, text, "受孕·高潮", "orgasm", 0)

        try:
            asyncio.create_task(job())
        except Exception as error:
            logger.warning("[受孕] 安排高潮消息失败：%s", error)

    def _schedule_notice(self, line: str, label: str, cause: str = "notice",
                         delay: int | None = None, *, judge: bool = False,
                         rollback=None) -> None:
        """发一条主动消息（带记忆联动标签）；默认让模型按她的口吻重写。"""
        umo = str(getattr(self, "_last_umo", "") or "")
        if not umo or not line:
            return
        judge = bool(judge and self.settings.bool("schedule.proactive_judge"))
        if judge and self._proactive_deferred(cause):
            return
        wait = max(0, self.settings.int("schedule.notice_delay_seconds", 0, 300)) \
            if delay is None else max(0, delay)
        if not self.settings.bool("schedule.generate_proactive") and not judge:
            try:
                self._notice_task = asyncio.create_task(
                    self._send_notice_later(umo, line, label, cause, wait))
            except Exception as error:
                logger.warning("[受孕] 安排主动消息失败：%s", error)
            return

        async def job() -> None:
            if judge:
                suitable, text = await self._judge_proactive_request(line, cause)
                if not suitable:
                    if callable(rollback):
                        try:
                            rollback()
                        except Exception as error:
                            logger.warning("[受孕] 主动请求回滚失败：%s", error)
                    minutes = max(1, self.settings.int(
                        "schedule.proactive_defer_minutes", 1, 1440))
                    self._defer_proactive(cause, minutes)
                    state_mod.append_log(
                        self.state, "proactive",
                        f"{label}：她觉得此刻不适合提出，{minutes} 分钟后再判断")
                    self._save()
                    logger.info("[受孕] 主动请求暂缓：%s", cause)
                    return
                text = text or line
            else:
                text = await self._compose_proactive(line)
            await self._send_notice_later(umo, text or line, label, cause, wait)

        try:
            self._notice_task = asyncio.create_task(job())
        except Exception as error:
            logger.warning("[受孕] 安排主动消息失败：%s", error)

    async def _compose_proactive(self, line: str) -> str:
        """把固定事件/旁白交给模型，用她的第一人称写成一条私聊消息。"""
        try:
            getter = getattr(self.context, "get_using_provider", None)
            provider = getter() if callable(getter) else None
            if provider is None:
                logger.warning("[受孕] 生成主动消息失败：没有可用模型")
                return ""
            prompt = (
                "下面是刚刚发生在她身上的事，或她原本想说的内容：\n"
                f"{line}\n\n"
                "请用她自己的第一人称，把这件事写成一条直接发给主人的自然私聊消息。"
                "保留全部事实和感受，但不要照抄旁白，不要括号、动作描写、解释、"
                "元指令，也不要提插件或提示词；只输出要发送的消息本身。")
            response = await asyncio.wait_for(
                provider.text_chat(
                    prompt=prompt, contexts=[],
                    system_prompt="你是她，正在主动给主人发私聊消息。"
                                  "自然、口语化，只输出她真正会发出去的那段文字。",
                    request_max_retries=1), timeout=30)
            text = str(getattr(response, "completion_text", "") or "").strip()
            text = text.strip("「」\"'")
            return text[:500]
        except Exception as error:
            logger.warning("[受孕] 生成主动消息失败，使用原文：%s", error)
            return ""

    async def _send_notice_later(self, umo: str, line: str, label: str,
                                 cause: str, delay: int) -> None:
        try:
            if delay:
                await asyncio.sleep(delay)
            from astrbot.core.message.message_event_result import MessageChain
            from astrbot.api.message_components import Plain

            chain = MessageChain([Plain(line)])
            tag = memory_link.bridge_tag(getattr(self.store, "path", ""))
            memory_link.attach_bridge(chain, tag, label=label, cause=cause)
            await self.context.send_message(umo, chain)
            self._save()
        except Exception as error:
            logger.warning("[受孕] 主动消息发送失败：%s", error)

    def _maybe_size_notice(self) -> dict:
        """首次见到 / 明显变化：按概率让她主动发一条（走记忆桥）。"""
        try:
            info = size.notice_check(self.state, self.settings)
        except Exception as error:
            logger.warning("[受孕] 尺寸提示失败：%s", error)
            return {}
        if not info or not info.get("line"):
            return info or {}
        umo = str(getattr(self, "_last_umo", "") or "")
        if not umo:
            return info
        delay = max(0, self.settings.int("size.notice_delay_seconds", 0, 300))
        try:
            self._size_task = asyncio.create_task(
                self._send_size_later(umo, info["line"], delay))
        except Exception as error:
            logger.warning("[受孕] 安排尺寸提示失败：%s", error)
        return info

    async def _send_size_later(self, umo: str, line: str, delay: int) -> None:
        try:
            if delay:
                await asyncio.sleep(delay)
            if self.settings.bool("schedule.generate_proactive"):
                line = await self._compose_proactive(line) or line
            from astrbot.core.message.message_event_result import MessageChain
            from astrbot.api.message_components import Plain

            chain = MessageChain([Plain(line)])
            tag = memory_link.bridge_tag(getattr(self.store, "path", ""))
            memory_link.attach_bridge(chain, tag, label="受孕·尺寸", cause="size")
            await self.context.send_message(umo, chain)
            state_mod.append_log(self.state, "size", f"她主动说了一句尺寸的话：{line}")
            self._save()
        except Exception as error:
            logger.warning("[受孕] 尺寸提示发送失败：%s", error)

    def _maybe_condom_remove_ask(self) -> dict:
        info = condom.maybe_ask_remove(self.state, self.settings)
        if not info:
            return {}
        state_mod.append_log(
            self.state, "condom",
            "她主动提出想脱掉避孕套" + ("，并自己动手脱了" if info.get("helped") else ""))
        self._save()
        return info

    def _tube_available(self) -> bool:
        if unbirth.inside(self.state, self.settings):
            return True
        try:
            info = uterus_insert.data(self.state)
            return bool(info.get("active")) and uterus_insert.stage_of(
                self.state, self.settings) >= 2
        except Exception:
            return False

    def _ovary_available(self, method: str = "") -> bool:
        if method in ("knead", "rub", "press"):
            return True
        if unbirth.inside(self.state, self.settings):
            return True
        opened = util.safe_float(self.state.get("ovary_open_at"), 0.0)
        if opened and util.now_ts() - opened <= 180:
            return True
        try:
            info = uterus_insert.data(self.state)
            if info.get("active") and uterus_insert.stage_of(self.state, self.settings) >= 3:
                return True
        except Exception:
            pass
        return False

    def _zone_extra(self, zone: str, method: str) -> dict:
        """耳朵（哈热气/舔耳）/ 舌吻：加敏感、快感、羞耻、忍耐、湿润；耳朵低概率高潮。"""
        table = {"ear": ("ear", {"earlick": "lick", "blow": "blow", "earsuck": "lick"}),
                 "kiss": ("kiss", {"french": "french"})}
        if zone not in table:
            return {}
        section, methods = table[zone]
        if method not in methods or not self.settings.bool(f"{section}.enabled"):
            return {}
        bonus = intimacy.add_zone_bonus(
            self.state, self.settings, zone,
            dev=self.settings.float(f"{section}.dev_gain", 0.0, 10.0),
            sens=self.settings.float(f"{section}.sens_gain", 0.0, 1.0))
        pleasure = self.settings.float(f"{section}.pleasure_gain", 0.0, 100.0)
        if zone == "kiss" and method == "french":
            pleasure += self.settings.float("kiss.french_pleasure", 0.0, 100.0)
        if pleasure:
            state_mod.add_pleasure(self.state, self.settings, pleasure)
        mood.adjust(self.state, self.settings, "shame",
                    delta=self.settings.float(f"{section}.shame_gain", 0.0, 100.0))
        endurance.add_extra(self.state, self.settings,
                            self.settings.float(f"{section}.endurance_gain", 0.0, 100.0))
        wetness.gain(self.state, self.settings,
                     extra=self.settings.float(f"{section}.wet_gain", 0.0, 100.0))
        line = prompts.text(self.state, section, methods[method])
        result = {"zone": zone, "method": method, "pleasure": round(pleasure, 1),
                  "dev": bonus.get("dev"), "sensitivity": bonus.get("sensitivity"),
                  "line": line}
        if zone == "ear":
            chance = self.settings.float("ear.orgasm_chance", 0.0, 100.0)
            if chance > 0 and random.random() * 100.0 < chance:
                orgasm = self._record_orgasm("耳朵", force=True)
                if orgasm and not orgasm.get("refused"):
                    result["orgasm"] = True
                    result["orgasm_line"] = prompts.text(self.state, "ear", "orgasm")
        return result

    def _size_float_note(self) -> None:
        """按当前快感/忍耐，记一次"会让她变长"的浮动。"""
        try:
            pleasure = util.safe_float(self.state.get("pleasure"), 0.0)
            at = self.settings.float("size.pleasure_at", 0.0, 1000.0)
            if pleasure >= at and not size.float_active(self.state, self.settings, "pleasure"):
                size.note(self.state, self.settings, "pleasure")
            end = endurance.payload(self.state, self.settings)
            if end.get("enabled") and end.get("percent", 0) >= self.settings.float(
                    "size.endurance_at", 0.0, 100.0):
                if not size.float_active(self.state, self.settings, "endurance"):
                    size.note(self.state, self.settings, "endurance")
        except Exception:
            pass

    def _hymen_note(self, info: dict) -> str:
        """破处的回执：按减痛比例写疼不疼。"""
        pain = str((info or {}).get("pain") or "normal")
        if pain == "none":
            return "第一次（处女膜破了，但几乎没觉得疼）"
        if pain == "slight":
            return "第一次（处女膜破了，只疼了一下）"
        return "第一次（处女膜破裂）"

    def _surprise_note(self, kind: str, shock: bool = True) -> dict:
        """不在活动里点面板按钮：记一次"突然被弄"，并按概率让她主动发消息。"""
        if not surprise.allowed(self.state, self.settings):
            return {}
        in_scene, _ = self._scene_active()
        if in_scene or state_mod.daily_active(self.state, self.settings):
            return {}
        info = surprise.mark(self.state, self.settings, kind, shock=shock)
        if not info:
            return {}
        if not shock:
            state_mod.append_log(
                self.state, "surprise",
                f"她知道的情况下用了小玩具（{info.get('label') or kind}）")
            return info
        state_mod.append_log(
            self.state, "surprise",
            f"她没准备的时候被弄了一下（{info.get('label') or kind}）"
            + ("：会主动发消息" if info.get("proactive") else ""))
        if info.get("proactive"):
            self._schedule_surprise_send()
        self._maybe_write_memory(
            f"被主人突然碰了一下（{info.get('label') or kind}），吓了一跳",
            reason="受孕·突然被弄")
        return info

    def _schedule_surprise_send(self) -> None:
        umo = str(getattr(self, "_last_umo", "") or "")
        if not umo:
            return
        delay = surprise.delay_seconds(self.settings)
        try:
            self._surprise_task = asyncio.create_task(self._send_surprise_later(umo, delay))
        except Exception as error:
            logger.warning("[受孕] 安排主动消息失败：%s", error)

    async def _send_surprise_later(self, umo: str, delay: int) -> None:
        try:
            if delay:
                await asyncio.sleep(delay)
            line = surprise.proactive_line(self.state, self.settings)
            if not line:
                return
            if self.settings.bool("schedule.generate_proactive"):
                line = await self._compose_proactive(line) or line
            from astrbot.core.message.message_event_result import MessageChain
            from astrbot.api.message_components import Plain

            chain = MessageChain([Plain(line)])
            tag = memory_link.bridge_tag(getattr(self.store, "path", ""))
            if memory_link.attach_bridge(chain, tag, label="受孕·突然被弄",
                                         cause="surprise"):
                logger.info("[受孕] 主动消息已挂记忆联动标签")
            await self.context.send_message(umo, chain)
            surprise.mark_sent(self.state)
            self._save()
            logger.info("[受孕] 已经主动发了一句（突然被弄）")
        except Exception as error:
            logger.warning("[受孕] 主动消息发送失败：%s", error)

    def _fish_desire(self) -> float | None:
        try:
            return boost.fish_desire(self.context)
        except Exception:
            return None

    def _maybe_write_memory(self, value: str, reason: str = "受孕插件") -> dict:
        """按开关往记忆插件写一条长期记忆（默认关、带节流）。"""
        try:
            info = memory_link.write_fact(self.context, self.settings, value=value,
                                          reason=reason, state=self.state)
        except Exception as error:
            logger.warning("[受孕] 写记忆失败：%s", error)
            return {"ok": False, "reason": str(error)}
        if info.get("ok"):
            state_mod.append_log(self.state, "memory", f"写进记忆：{value}")
        return info

    def _sleep_note(self) -> dict:
        """活动进行中：她要是正在睡，就记一段"暂时醒着"（允许发言）。"""
        try:
            info = sleepy.tick(self.state, self.settings, in_event=True)
        except Exception as error:
            logger.warning("[受孕] 睡眠时段例外处理失败：%s", error)
            return {"sleeping": False, "reason": "处理失败"}
        if info.get("marked") and not info.get("cached"):
            state_mod.append_log(
                self.state, "sleep",
                f"睡眠时段里开始活动：暂时允许她发言 {info.get('minutes')} 分钟"
                + ("（已同步 PC 休息门）" if (info.get("gate") or {}).get("ok") else ""))
        return info

    def _fish_write_on(self) -> bool:
        override = self.state.get("wetness_fish_write")
        if isinstance(override, bool):
            return override
        return bool(self.settings.bool("wetness.fish_write_enabled"))

    def _wetness_payload(self) -> dict:
        """湿润度面板数据：带上鱼之心「欲」和它带来的涨幅加成。"""
        self._sync_fish_wetness()
        data = wetness.payload(self.state, self.settings)
        chosen, source, parts = self._desire_pick("wetness")
        scale = self.settings.float("wetness.fish_desire_scale", 0.0, 10.0)
        data["fish_available"] = "fish" in parts
        data["fish_desire"] = parts.get("fish")
        data["desire_value"] = round(chosen, 1)
        data["desire_source"] = source
        data["desire_parts"] = parts
        data["fish_gain_mult"] = round(1.0 + max(0.0, scale) * chosen / 100.0, 2)
        data["fish_write"] = self._fish_write_on()
        bonus = 0.0
        if lube.active(self.state, self.settings):
            bonus += self.settings.float("lube.wet_gain", 0.0, 100.0)
        if lube.hand_active(self.state, self.settings):
            bonus += self.settings.float("lube.hand_wet_gain", 0.0, 100.0)
        data["lube_bonus"] = round(bonus, 1)
        data["night_wet"] = round(lube.natural_wetness(self.state, self.settings), 1)
        return data

    def _sync_fish_wetness(self) -> dict:
        """鱼之心「欲」自己涨了（不是我们写的）→ 湿润度也跟着涨一点。"""
        if not self.settings.bool("wetness.enabled"):
            return {}
        now = util.now_ts()
        desire = self._fish_desire()
        # 顺手记一份鱼之心快照给"基础湿润度浮动"用（没装/没觉醒就 0）
        self.state["fish_snapshot"] = {
            "desire": round(max(0.0, min(100.0, util.safe_float(desire, 0.0))), 2),
            "at": now,
        }
        if desire is None:
            return {"ok": False, "reason": "鱼之心没启用"}
        seen = self.state.get("fish_desire_seen")
        try:
            seen_value = None if seen is None else float(seen)
        except (TypeError, ValueError):
            seen_value = None
        if seen_value is None:
            self.state["fish_desire_seen"] = desire
            return {"ok": True, "first": True, "desire": round(desire, 2)}
        delta = desire - seen_value
        if delta <= 0.01:
            self.state["fish_desire_seen"] = desire
            return {"ok": True, "delta": 0.0, "desire": round(desire, 2)}
        rate = self.settings.float("wetness.fish_desire_to_wet", 0.0, 100.0)
        # 补涨节流：每隔 N 分钟最多补一次；被节流时先不更新 seen，差值攒着下次一起补
        min_minutes = max(0, self.settings.int("wetness.fish_desire_min_minutes", 0, 1440))
        if min_minutes > 0:
            last = util.safe_float(self.state.get("fish_desire_sync_at"), 0.0)
            if last and now - last < min_minutes * 60:
                left = int(min_minutes * 60 - (now - last))
                return {"ok": True, "skipped": "throttle", "delta": round(delta, 2),
                        "pending": round(delta * rate, 2), "left_seconds": left,
                        "desire": round(desire, 2)}
        add = delta * rate
        before = wetness.value_of(self.state, self.settings)
        after = wetness.gain(self.state, self.settings, extra=add) if add > 0 else before
        self.state["fish_desire_seen"] = desire
        self.state["fish_desire_sync_at"] = now
        result = {"ok": True, "delta": round(delta, 2), "added": round(after - before, 2),
                  "before": round(before, 1), "after": round(after, 1),
                  "desire": round(desire, 2), "rate": rate}
        if result["added"] > 0:
            state_mod.append_log(
                self.state, "wetness",
                f"鱼之心「欲」+{delta:.1f} → 湿润度 +{result['added']:.1f}"
                f"（{result['before']:.0f} → {result['after']:.0f}）")
        return result

    def _gain_wetness(self, *, touch: float = 0.0, pleasure: float = 0.0,
                      extra: float = 0.0) -> dict:
        """涨湿润度：鱼之心「欲」越高涨得越快；涨完再同步加一点「欲」。"""
        self._sync_fish_wetness()
        desire_value, desire_source, _ = self._desire_pick("wetness")
        mult = 1.0
        scale = self.settings.float("wetness.fish_desire_scale", 0.0, 10.0)
        mult = 1.0 + max(0.0, scale) * desire_value / 100.0
        before = wetness.value_of(self.state, self.settings)
        after = wetness.gain(self.state, self.settings, touch=touch, pleasure=pleasure,
                             extra=extra, mult=mult)
        if after > before and clothing.worn_key(self.state, self.settings, "underwear"):
            cause = "lube" if (lube.active(self.state, self.settings) or
                               lube.hand_active(self.state, self.settings)) else "love"
            clothing.mark_panties_wet(self.state, cause)
        result = {"before": round(before, 1), "after": round(after, 1),
                  "gain": round(after - before, 2), "mult": round(mult, 2),
                  "fish_desire": round(desire_value, 1),
                  "desire_source": desire_source}
        if after > before and self._fish_write_on():
            amount = self.settings.float("wetness.fish_desire_gain", 0.0, 100.0)
            if amount > 0:
                try:
                    result["fish"] = boost.boost_fish_desire(
                        self.context, self.settings, amount, enabled=True)
                    if (result.get("fish") or {}).get("ok"):
                        self.state["fish_desire_seen"] = result["fish"].get("after")
                except Exception as error:
                    logger.warning("[受孕] 写鱼之心「欲」失败：%s", error)
        return result

    def _endurance_orgasm(self, trigger: str, *, was_full: bool,
                          open_scene: bool = True) -> dict | None:
        """忍耐条本来就满了，这次再刺激就到了 —— "满了再加就高潮"。"""
        if not endurance.enabled(self.settings) or not was_full:
            return None
        result = self._record_orgasm(f"忍耐到顶·{trigger}", open_scene=open_scene)
        if not result or result.get("refused"):
            return None
        return result

    def _record_orgasm(self, trigger: str, *, force: bool = False,
                       open_scene: bool = True) -> dict | None:
        ok, why = self._gate()
        if not ok:
            return {"refused": why}
        self._sleep_note()
        combo_on = self.settings.bool("combo.enabled")
        limit = self._combo_limit()

        # 1) 已经"过头"了：这段时间碰一下都难受
        rest = state_mod.rest_remaining(self.state) if combo_on else 0
        if rest and not force:
            return {"refused": f"她现在太敏感了（刚连续高潮过头），碰一下都难受，"
                               f"想让你慢一点、先缓 {rest} 分钟",
                    "overstimulated": True, "rest_minutes": rest,
                    "count": state_mod.combo_count(self.state, self.settings)}

        # 2) 连续次数已经到上限：再多就难受、会疼
        count = state_mod.combo_count(self.state, self.settings) if combo_on else 0
        if combo_on and count >= limit and not force:
            span = state_mod.set_rest(self.state, self.settings)
            state_mod.append_log(
                self.state, "combo",
                f"连续 {count} 次高潮后过头了，需要缓 {span} 分钟（{trigger}）")
            self._save()
            return {"refused": f"已经连续 {count} 次了，再多会难受、会疼；"
                               f"她会请求慢一点（先缓 {span} 分钟）",
                    "overstimulated": True, "rest_minutes": span, "count": count}

        pleasure = util.safe_float(self.state.get("pleasure"), 0.0)
        threshold = state_mod.effective_threshold(self.state, self.settings)
        endurance_on = endurance.enabled(self.settings)
        if not force and endurance_on and not endurance.is_full(self.state, self.settings):
            left = endurance.payload(self.state, self.settings)
            return {"refused": f"她还在忍（忍耐条 {left['value']:.0f}/{left['cap']:.0f}），"
                               f"满了再刺激一下才会到",
                    "endurance": left, "pleasure": pleasure, "threshold": threshold}
        if not force and not endurance_on and pleasure < threshold:
            return {"refused": f"快感还不够（{pleasure:.0f}/{threshold:.0f}），还没到那一步",
                    "pleasure": pleasure, "threshold": threshold}

        if unbirth.inside(self.state, self.settings):
            unbirth.settle(self.state, self.settings)
        if open_scene:
            self._surprise_note("orgasm")
            self._touch_scene("高潮")
        edge_stack = state_mod.edge_stack(self.state, self.settings)
        edge_bonus = state_mod.edge_orgasm_bonus(self.state, self.settings)
        info = state_mod.add_orgasm(self.state, self.settings, extra_gain=edge_bonus)
        combo = state_mod.add_combo_orgasm(self.state, self.settings) if combo_on else \
            {"count": 0, "peak": 0}
        info.update(threshold=threshold, combo=combo,
                    edge_stack=edge_stack, edge_bonus=edge_bonus)
        end_info = endurance.payload(self.state, self.settings) if endurance_on else {}
        sq = squirt.roll(self.state, self.settings, pleasure=pleasure,
                         endurance_percent=util.safe_float(end_info.get("percent"), 0.0),
                         combo=combo.get("count", 0))
        if sq:
            info["squirt"] = sq
        last_touch = self.state.get("last_touch") if isinstance(
            self.state.get("last_touch"), dict) else {}
        part = intimacy.ZONE_LABELS.get(str(last_touch.get("zone") or ""), "") or "最里面"
        cause = subzone.method_label(str(last_touch.get("method") or "")) or trigger
        if unbirth.inside(self.state, self.settings):
            info["unbirth"] = True
            if combo.get("count", 0) >= 2:
                line = prompts.text(self.state, "unbirth", "combo",
                                    count=combo["count"], part=part, cause=cause)
            else:
                line = prompts.text(self.state, "unbirth", "orgasm",
                                    part=part, cause=cause)
        elif combo.get("count", 0) >= 2:
            line = prompts.text(self.state, "orgasm", "combo", count=combo["count"],
                                part=part, cause=cause)
        else:
            line = prompts.text(self.state, "orgasm", "part", part=part, cause=cause)
        info["line"] = line
        if line:
            self.state["orgasm_note"] = {"at": util.now_ts(), "line": line}
        self._wake_after_orgasm()
        self._schedule_orgasm_message(line or "她刚刚到了一次高潮")
        self._note_text_event("orgasm")
        state_mod.append_log(
            self.state, "orgasm",
            f"高潮第 {info['session']} 次（今日 {info['today']}，累计 {info['total']}；"
            f"连续第 {combo['count']} 次；{trigger}）")
        if edge_stack:
            state_mod.append_log(
                self.state, "edge",
                f"被寸止 {edge_stack} 次后终于到了：额外快感 +{edge_bonus:.0f}（{trigger}）")
        if combo_on and combo["count"] >= limit:
            state_mod.append_log(self.state, "combo",
                                 f"已经连续 {combo['count']} 次，再继续就会过头")
        self._gain_wetness(extra=self.settings.float("wetness.orgasm_gain", 0.0, 100.0))
        state_mod.clear_edge(self.state)
        induced = self._maybe_induce_ovulation(trigger, orgasms=info["session"],
                                               pleasure=pleasure)
        if induced:
            info["induced_ovulation"] = induced
        if size.note(self.state, self.settings, "orgasm"):
            state_mod.append_log(self.state, "size", "高潮后阴道会略微变长一会儿")
        if endurance_on:
            grown = endurance.consume(self.state, self.settings)
            self.state.pop("endurance_full_since", None)
            self.state.pop("endurance_auto_edge_done", None)
            info["endurance"] = grown
            state_mod.append_log(
                self.state, "endurance",
                f"忍耐条清空，下一次要忍 {grown['cap']:.0f}"
                f"（连续第 {grown['combo']} 次，条变长 {grown['grow']:.0f}）")
        succubus = self._succubus_after_orgasm(trigger)
        if succubus:
            info["succubus"] = succubus
        if state_mod.scene_active(self.state, self.settings) or \
                state_mod.daily_active(self.state, self.settings):
            night.mark_orgasm(self.state)
        self._save()
        return info

    def _succubus_after_orgasm(self, trigger: str) -> dict | None:
        """魅魔：她高潮后的加成（PC 精力 + 鱼之心依恋/亲密/欲）。"""
        if not succubus.enabled(self.state, self.settings):
            return None
        gains = succubus.orgasm_gains(self.state, self.settings)
        pc = boost.boost_pc(self.settings, int(gains["energy"])) if gains["energy"] else {}
        fish = boost.boost_fish(
            self.context, self.settings,
            attachment=gains["attachment"], intimacy=gains["intimacy"],
            desire=gains["desire"],
        )
        text = self._succubus_text("高潮", gains, pc, fish)
        if not text:
            return None
        state_mod.append_log(self.state, "succubus", f"{text}（{trigger}）")
        logger.info("[受孕] %s", text)
        return {"text": text, "pc": pc, "fish": fish, "gains": gains}

    def _succubus_after_ejaculation(self, mode: str) -> dict | None:
        """魅魔：每次射出都加精力/依恋/亲密；欲每次活动只加一次。"""
        if not succubus.enabled(self.state, self.settings):
            return None
        if not succubus.can_boost(self.state, self.settings):
            state_mod.append_log(self.state, "succubus",
                                 "今日榨取已达上限，这次不再加成")
            return {"skipped": "今日榨取已达上限"}
        succubus.consume(self.state, self.settings)
        gains = succubus.ejaculation_gains(self.state, self.settings)
        desire = 0.0
        if succubus.desire_once(self.state):
            desire = self.settings.float("succubus.ejaculation_desire_gain", 0.0, 100.0)
            desire = round(desire * succubus.gain_scale(self.state, self.settings), 2)
        pc = boost.boost_pc(self.settings, int(gains["energy"])) if gains["energy"] else {}
        fish = boost.boost_fish(
            self.context, self.settings,
            attachment=gains["attachment"], intimacy=gains["intimacy"],
            desire=desire,
        )
        kind = f"射出·{intimacy.MODE_LABELS.get(mode, mode)}"
        text = self._succubus_text(kind, {**gains, "desire": desire}, pc, fish)
        if not text:
            text = f"魅魔榨取（{kind}）"
        exp = succubus.add_exp(self.state, self.settings,
                               self.settings.int("succubus.exp_gain", 0, 1000))
        text += f"｜淫纹经验 +{exp['gained']}（{exp['exp']}/{exp['need']}）"
        if exp.get("leveled"):
            text += f"｜升到 Lv.{exp['level']}！"
        state_mod.append_log(self.state, "succubus", text)
        logger.info("[受孕] %s", text)
        return {"text": text, "pc": pc, "fish": fish, "gains": gains,
                "desire": desire, "exp": exp}

    @staticmethod
    def _succubus_text(kind: str, gains: dict, pc: dict, fish: dict) -> str:
        parts = []
        if pc.get("ok"):
            parts.append(f"PC 精力 {pc['before']} → {pc['after']}")
        if fish.get("ok"):
            for key, label in (("attachment", "依恋"), ("intimacy", "亲密"),
                               ("desire", "欲")):
                row = (fish.get("applied") or {}).get(key)
                if row:
                    parts.append(f"{label} {row['before']} → {row['after']}")
        if not parts:
            return ""
        return f"魅魔榨取（{kind}）：" + "；".join(parts)

    def _succubus_conception_bonus(self) -> dict | None:
        """魅魔且她愿意怀时，受孕成功后的额外大加成。"""
        if not succubus.enabled(self.state, self.settings):
            return None
        if succubus.willing(self.state) is not True:
            return None
        energy = self.settings.int("succubus.willing_conception_energy", 0, 100)
        fish_gain = self.settings.float("succubus.willing_conception_fish_gain", 0.0, 50.0)
        pc = boost.boost_pc(self.settings, energy) if energy else {}
        fish = boost.boost_fish(self.context, self.settings,
                                attachment=fish_gain, intimacy=fish_gain)
        parts = []
        if pc.get("ok"):
            parts.append(f"PC 精力 {pc['before']} → {pc['after']}")
        if fish.get("ok"):
            for key, label in (("attachment", "依恋"), ("intimacy", "亲密")):
                row = (fish.get("applied") or {}).get(key)
                if row:
                    parts.append(f"{label} {row['before']} → {row['after']}")
        if not parts:
            return None
        text = "魅魔受孕加成：" + "；".join(parts)
        state_mod.append_log(self.state, "succubus", text)
        logger.info("[受孕] %s", text)
        return {"text": text, "pc": pc, "fish": fish}

    def _record_edge(self, trigger: str) -> dict:
        """寸止：快到门槛时停下来，不算高潮。"""
        ok, why = self._gate()
        if not ok:
            return {"refused": why}
        if not self.settings.bool("edge.enabled"):
            return {"refused": "寸止功能关着"}
        pleasure = util.safe_float(self.state.get("pleasure"), 0.0)
        threshold = state_mod.effective_threshold(self.state, self.settings)
        ratio = self.settings.float("edge.min_ratio", 0.0, 1.0)
        need = threshold * ratio
        if pleasure < need:
            return {"refused": f"还差得远（{pleasure:.0f}/{threshold:.0f}）："
                               f"至少到 {need:.0f} 再停下才算寸止"}
        self._touch_scene("寸止")
        info = state_mod.add_edge(self.state, self.settings)
        state_mod.append_log(
            self.state, "edge",
            f"寸止：快感吊在 {pleasure:.0f}/{threshold:.0f}，第 {info['stack']} 次，"
            f"门槛 +{info['bonus']:.0f}（渴求 {info['craving']:.0f}%；{trigger}）")
        self._save()
        info.update(pleasure=pleasure, threshold=threshold)
        return info

    def _maybe_induce_ovulation(self, trigger: str, *, orgasms: int,
                                pleasure: float) -> dict | None:
        """累积的高潮/快感到一定程度，把排卵"催"出来。"""
        if not self.settings.bool("ovulation.induced_enabled"):
            return None
        if pregnancy.is_pregnant(self.state):
            return None
        now = util.now_ts()
        if state_mod.ovulation_active(self.state, now):
            return None
        cooldown = max(0.0, self.settings.float("ovulation.cooldown_hours", 0.0, 720.0)) * 3600
        last = util.safe_float(self.state.get("induced_ovulation_at"), 0.0)
        if last and now - last < cooldown:
            return None
        need_orgasms = self.settings.int("ovulation.min_orgasms", 1, 50)
        need_pleasure = self.settings.float("ovulation.min_pleasure", 0.0, 100.0)
        if orgasms < need_orgasms and pleasure < need_pleasure:
            return None
        if self.settings.bool("ovulation.require_outside_fertile"):
            phase = str((self._cycle() or {}).get("phase") or "")
            if phase in ("pre_ovulation", "ovulation"):
                return None
        chance = self.settings.float("ovulation.chance", 0.0, 100.0)
        if chance <= 0 or random.random() * 100 >= chance:
            return None
        info = state_mod.induce_ovulation(self.state, self.settings, now)
        when = datetime.fromtimestamp(info["until"]).strftime("%m-%d %H:%M")
        state_mod.append_log(
            self.state, "ovulation",
            f"身体被诱发排卵：到 {when} 之前按排卵期算受孕率（{trigger}）")
        logger.info("[受孕] 诱发排卵，持续到 %s", when)
        return info

    def _record_touch(self, zone: str, times: int, trigger: str,
                      method: str = "", depth: float = 0.0,
                      hymen_break: bool = False) -> dict:
        """亲/摸某个敏感点：只涨快感，不判定受孕；同时给子敏感度条加进度。

        method 是"正在被怎么弄"（乳交/舔/吮吸…）：模型可以直接传，
        没传时由调用方从关键词里猜（猜不出就沿用这个部位上一次的方式）。
        """
        ok, why = self._gate()
        if not ok:
            return {"refused": why}
        key = intimacy.normalize_zone(zone)
        if not key:
            return {"refused": f"没有这个敏感点：{zone}",
                    "zones": [z["key"] for z in intimacy.zones_payload(self.settings, self.state)]}
        if not intimacy.zone_enabled_effective(self.state, self.settings, key):
            return {"refused": f"{intimacy.ZONE_LABELS.get(key, key)}还没启用"}
        reachable, why = size.can_reach(self.state, self.settings, key)
        if not reachable:
            return {"refused": why, "size": size.payload(self.state, self.settings)}
        used = subzone.normalize_method(key, method)
        if key == "ovary" and not self._ovary_available(
                subzone.normalize_method(key, method) if method else ""):
            return {"refused": "卵巢在很深的地方，普通碰不到：要揉捏小腹、用筋膜枪、"
                               "Unbirth，或者顶到最里面（整个阴茎头进来/插满）才行"}
        if key == "tube" and not self._tube_available():
            return {"refused": "输卵管太深了：要阴茎头几乎全进来/整个进来/插满，"
                               "或者 Unbirth 待在子宫里才碰得到"}
        blocked, item = clothing.blocked(self.state, self.settings, key)
        through = ""
        if blocked:
            if used not in ("lick", "suck", "rub", "knead", "tease"):
                return {"refused": f"她穿着{item}，直接来不了；得先脱掉，或者隔着衣物"}
            through = clothing.through_prompt(self.state, key)
        escalated = state_mod.daily_active(self.state, self.settings)
        self._surprise_note("touch")
        self._touch_scene("触碰")
        full_before = endurance.is_full(self.state, self.settings)
        info = intimacy.apply_touch(self.state, self.settings, key, times=times)
        if key == "hymen" and used in ("finger", "rub", "press") and body.hymen_intact(self.state):
            relief = wetness.hymen_relief(
                self.state, self.settings,
                pleasure=util.safe_float(self.state.get("pleasure"), 0.0))
            if hymen_break or depth > size.hymen_depth(self.state, self.settings):
                hymen = body.rupture_hymen(self.state, self.settings, "手指进入",
                                           relief=relief["relief"], blood_key="finger",
                                           force=True)
            else:
                hymen = body.add_hymen_damage(
                    self.state, self.settings,
                    self.settings.float("hymen.finger_damage", 0.0, 100.0),
                    blood_key="finger")
                if not hymen.get("ruptured"):
                    hymen = {"damage": hymen.get("damage"), "ruptured": False}
            if hymen:
                info["hymen"] = hymen
                if hymen.get("blood"):
                    menstrual.add_pad_fluid(self.state, self.settings, "处子血", 2.0)
                if hymen.get("pleasure"):
                    state_mod.add_pleasure(self.state, self.settings, hymen["pleasure"])
        if unbirth.inside(self.state, self.settings) and key in (
                "cervix", "tube", "hymen", "vulva", "gspot"):
            zone_line = prompts.text(self.state, "unbirth", f"zone_{key}")
            if zone_line:
                info["unbirth_zone"] = zone_line
                self.state["unbirth_zone_note"] = {
                    "at": util.now_ts(), "key": key, "line": zone_line}
        if through:
            info["through"] = through
        ask = self._maybe_condom_remove_ask()
        if ask:
            info["condom_remove_ask"] = ask
        extra = self._zone_extra(key, used)
        if extra:
            info["ear" if key == "ear" else "kiss"] = extra
        dry_info = insert_effects.dry_touch(self.state, self.settings, key, used)
        if dry_info:
            info["dry"] = dry_info
            info["value"] = util.safe_float(self.state.get("pleasure"), info["value"])
            state_mod.append_log(self.state, "dry", "太干了，进去会疼（快感/忍耐下降）")
        insert_effects.hold_note(self.state, key, used)
        self.state["last_touch"] = {"zone": key, "method": used, "at": util.now_ts()}
        # 特别敏感点：正好碰到她这会儿最敏感的地方 → 多涨点快感、多攒点忍耐
        special_hit = special.hit(self.state, self.settings, key)
        if special_hit:
            extra = special_hit.get("pleasure") or 0.0
            if extra > 0:
                state_mod.add_pleasure(self.state, self.settings, extra)
                info["value"] = util.safe_float(self.state.get("pleasure"), info["value"])
                info["gain"] = round(info["gain"] + extra, 2)
            extra_end = special_hit.get("endurance") or 0.0
            if extra_end > 0:
                endurance.add_extra(self.state, self.settings, extra_end)
            info["special"] = special_hit
            state_mod.append_log(
                self.state, "special",
                f"碰到特别敏感点（{special_hit['label']}）：快感 +{extra:.0f}、"
                f"忍耐 +{extra_end:.0f}（{trigger}）")
        # 子敏感度：只在她正在受孕活动里时涨；满了会溢出（给主敏感点加开发度/敏感度+快感）
        in_scene, _ = self._scene_active()
        if in_scene:
            end_now = endurance.payload(self.state, self.settings) if endurance.enabled(
                self.settings) else {}
            brk = condom.break_roll(
                self.state, self.settings,
                pleasure=util.safe_float(self.state.get("pleasure"), 0.0),
                endurance_percent=util.safe_float(end_now.get("percent"), 0.0))
            if brk:
                info["condom_break"] = brk
                state_mod.append_log(self.state, "condom",
                                     "避孕套破了" + ("（她感觉到了）" if brk["felt"]
                                                   else "（她没察觉）"))
        sub = subzone.apply_touch(
            self.state, self.settings, key, times=times, method=method,
            in_scene=in_scene, sensitivity=util.safe_float(info.get("sensitivity"), 1.0))
        info["sub"] = sub
        moved = behavior.mark(self.state, key, sub.get("method") or method)
        if moved:
            info["behavior"] = moved
        if escalated:
            info["escalated"] = True
        how = f"（{sub['method_label']}）" if sub.get("method_label") else ""
        state_mod.append_log(
            self.state, "touch",
            f"{info['label']}{how} ×{info['times']}：快感 +{info['gain']:.1f}"
            f"（开发 {info['dev']}%、敏感 ×{info['sensitivity']:.2f}）："
            f"{info['before']:.0f} → {info['value']:.0f}（{trigger}）")
        if sub.get("gain"):
            state_mod.append_log(
                self.state, "subzone",
                f"{sub['label']} 子敏感度 +{sub['gain']:.0f} → {sub['charge']:.0f}"
                f"（{sub['level_title']}）")
        burst = sub.get("burst")
        if burst:
            state_mod.append_log(
                self.state, "subzone",
                f"子敏感度溢出（{burst['label']} 第 {burst['count']} 次）："
                f"开发度 +{burst['dev_gain']:.1f} → {burst['dev']}%、"
                f"敏感度 +{burst['sensitivity_gain']:.2f} → ×{burst['sensitivity']:.2f}、"
                f"快感 +{burst['pleasure']:.1f} → {burst['value']:.0f}；"
                f"条 {burst['fall_seconds']:.1f} 秒内回落")
            logger.info("[受孕] 子敏感度溢出：%s", burst["label"])
        # 湿润度：碰几下 + 涨了多少快感都算（阴道/外阴这些地方涨得更明显）
        self._sleep_note()
        self._size_float_note()
        self._maybe_size_notice()
        wet = self._gain_wetness(touch=times,
                                  pleasure=util.safe_float(info.get("gain"), 0.0))
        info["wetness"] = wetness.payload(self.state, self.settings)
        if wet.get("gain"):
            info["wet"] = {"gain": wet["gain"], "after": wet["after"],
                           "fish_desire": wet.get("fish_desire")}
        orgasm = self._endurance_orgasm("触碰", was_full=full_before)
        if orgasm:
            info["orgasm"] = orgasm
        self._save()
        return info

    def _sub_text(self, info: dict) -> str:
        """把一次触碰里子敏感度的变化写成一句话（没有变化就返回空）。"""
        sub = (info or {}).get("sub") or {}
        prefix = "；日常小场景已升级成正式活动场景" if (info or {}).get("escalated") else ""
        how = f"{sub['method_label']} · " if sub.get("method_label") else ""
        burst = sub.get("burst")
        if burst:
            return (f"{prefix}；子敏感度满了（{how}{burst['label']}）：开发度 +{burst['dev_gain']:.1f}、"
                    f"敏感度 +{burst['sensitivity_gain']:.2f}、快感再 +{burst['pleasure']:.0f}")
        if sub.get("gain"):
            return f"{prefix}；子敏感度 {how}{sub['charge']:.0f}%（{sub['level_title']}）"
        if sub.get("blocked"):
            return f"{prefix}；子敏感度没涨（{sub['blocked']}）"
        return prefix

    def _comfort(self, kind: str, trigger: str) -> dict:
        """安慰 / 摸摸头 / 亲吻：降羞耻（也降一点欲望）。"""
        result = mood.comfort(self.state, self.settings, kind)
        state_mod.append_log(
            self.state, "mood",
            f"{result['kind']}：羞耻度 {result['shame']:.0f}（{result['shame_delta']:+.0f}）、"
            f"欲望度 {result['desire']:.0f}（{result['desire_delta']:+.0f}）（{trigger}）")
        self._save()
        return result

    COMFORT_WORDS = ("安慰", "摸摸头", "摸摸", "亲亲", "亲吻", "抱抱", "抱一下", "哄哄",
                     "哄她", "别害羞", "不羞", "没关系", "乖")

    def _detect_comfort(self, text: str) -> None:
        """日常里他说了安慰/摸摸头/亲吻这类话，羞耻度就降一点。"""
        if not self.settings.bool("mood.enabled") or \
                not self.settings.bool("mood.keyword_detect"):
            return
        if not text or not self._match_any(text, list(self.COMFORT_WORDS)):
            return
        now = util.now_ts()
        if now - util.safe_float(self.state.get("_comfort_at"), 0.0) < 60:
            return
        hit = next((word for word in self.COMFORT_WORDS if word.lower() in text.lower()), "安慰")
        self._comfort(hit, "主人的话")
        self.state["_comfort_at"] = now

    def _massage_gun_gains(self, info: dict) -> dict:
        """筋膜枪按部位分三档：手脚=亲密/依恋/欲望；小腹乳房=少量四维；外阴阴蒂=较多四维。"""
        place = str(info.get("place") or "belly")
        soft = place in ("foot", "hand", "leg", "tail", "ear", "mouth")
        hot = place in ("vulva", "clitoris", "vagina", "gspot", "cervix", "anus")
        if soft:
            group = "massage_soft"
            gains = {
                "attachment": tuning.get(self.state, "toys", "mg_soft_attachment",
                                         self.settings.float("toys.mg_soft_attachment", 0, 100)),
                "intimacy": tuning.get(self.state, "toys", "mg_soft_intimacy",
                                       self.settings.float("toys.mg_soft_intimacy", 0, 100)),
                "desire": tuning.get(self.state, "toys", "mg_soft_desire",
                                     self.settings.float("toys.mg_soft_desire", 0, 100)),
            }
            fish = boost.boost_fish(self.context, self.settings,
                                    attachment=gains["attachment"],
                                    intimacy=gains["intimacy"],
                                    desire=gains["desire"])
            info["massage"] = {"group": group, "gains": gains, "fish": fish}
        else:
            group = "massage_hot" if hot else "massage_body"
            prefix = "mg_hot" if hot else "mg_body"
            gains = {
                "pleasure": tuning.get(self.state, "toys", f"{prefix}_pleasure",
                                       self.settings.float(f"toys.{prefix}_pleasure", 0, 100)),
                "desire": tuning.get(self.state, "toys", f"{prefix}_desire",
                                     self.settings.float(f"toys.{prefix}_desire", 0, 100)),
                "wet": tuning.get(self.state, "toys", f"{prefix}_wet",
                                  self.settings.float(f"toys.{prefix}_wet", 0, 100)),
                "endurance": tuning.get(self.state, "toys", f"{prefix}_endurance",
                                        self.settings.float(f"toys.{prefix}_endurance", 0, 100)),
            }
            if gains["pleasure"]:
                state_mod.add_pleasure(self.state, self.settings, gains["pleasure"])
            if gains["desire"]:
                mood.adjust(self.state, self.settings, "desire", delta=gains["desire"])
            if gains["wet"]:
                wetness.gain(self.state, self.settings, extra=gains["wet"])
            if gains["endurance"]:
                endurance.add_extra(self.state, self.settings, gains["endurance"])
            info["massage"] = {"group": group, "gains": gains}
        info["massage_line"] = prompts.text(self.state, "toy", group)
        return info["massage"]

    def _toy_extra(self, info: dict) -> str:
        """玩具一次之后的附加说明：子敏感度 / 日常小场景 / 被玩具送上高潮 / 日常情绪。"""
        parts = [self._sub_text(info)]
        daily = (info or {}).get("daily") or {}
        if daily.get("active"):
            parts.append(f"；日常小场景（约剩 {daily['remaining']} 分钟）")
        orgasm = (info or {}).get("orgasm") or {}
        if orgasm and not orgasm.get("refused"):
            parts.append(f"；她被这一下弄到了（本次第 {orgasm['session']} 次，"
                         f"快感回落到 {orgasm['after']:.0f}）")
        gains = (info or {}).get("mood") or {}
        if gains:
            parts.append(f"；欲望度 {gains['desire']:.0f}（+{gains['desire_gain']:.0f}）、"
                         f"羞耻度 {gains['shame']:.0f}（+{gains['shame_gain']:.0f}）")
        full = (info or {}).get("shame_full") or {}
        if full:
            blame = full.get("blame") or {}
            parts.append(f"；羞耻满溢：进羞耻期 {full['minutes']} 分钟（这段时间她不肯再用玩具）"
                         + (f"，鱼之心的责怪 +{blame.get('added', 0):.1f}"
                            if blame.get("ok") else ""))
        if (info or {}).get("desire_full"):
            parts.append("；欲望满溢：她自己贴上来，这一段已经转成正式活动场景")
        return "".join(part for part in parts if part)

    def _record_toy(self, toy: str, intensity: int, trigger: str,
                    place: str = "", secret: bool = False,
                    depth: float = 0.0, hymen_break: bool = False,
                    user: str = "master") -> dict:
        """用一次小玩具：涨快感、推高对应部位的子敏感度；日常用会开一个"日常小场景"。

        只涨快感，不判定受孕；如果这一下把快感推过门槛，按配置自动记一次高潮。
        """
        ok, why = self._gate()
        if not ok:
            return {"refused": why}
        if menstrual.changing(self.state):
            return {"refused": "她正在换卫生巾，小玩具暂时不在手边"}
        key = toys.normalize_toy(toy)
        if not key:
            return {"refused": f"没有这个玩具：{toy}",
                    "toys": [t["key"] for t in toys.toys_payload(self.settings, self.state)]}
        if not toys.toy_enabled(self.settings, key):
            return {"refused": f"{toys.TOY_CATALOG[key]['label']}还没启用"}
        in_scene, _ = self._scene_active()
        if not in_scene and not toys.toy_outside(self.settings, key):
            allowed = "、".join(row["label"] for row in toys.toys_payload(
                self.settings, self.state) if row["enabled"] and row["outside"])
            return {"refused": f"{toys.TOY_CATALOG[key]['label']}要在亲密场景里用；"
                               f"不在场景时只能用：{allowed or '（没有允许的）'}"}
        # 羞耻期：她自己不肯再碰玩具
        if mood.shame_period_active(self.state):
            left = mood.shame_period_remaining(self.state)
            return {"refused": f"她刚羞耻过头，正在羞耻期（还要 {left} 分钟）："
                               f"这时候她自己不肯用玩具，先哄哄她",
                    "shame_period": left}
        if secret:
            self._surprise_note("toy_secret")
        elif not in_scene:
            self._surprise_note("toy_known", shock=False)
        if in_scene:
            self._touch_scene("玩具")
        full_before = endurance.is_full(self.state, self.settings)
        info = toys.apply_toy(self.state, self.settings, key, intensity, place=place)
        if key == "massage_gun":
            self.state["ovary_open_at"] = util.now_ts()
            self._massage_gun_gains(info)
        if info.get("place") == "vagina" and body.hymen_intact(self.state):
            relief = wetness.hymen_relief(
                self.state, self.settings,
                pleasure=util.safe_float(self.state.get("pleasure"), 0.0))
            who = "self" if str(user) == "self" else "master"
            blood_key = f"toy_{'scene' if in_scene else 'daily'}_{who}"
            if hymen_break or depth > size.hymen_depth(self.state, self.settings):
                hymen = body.rupture_hymen(
                    self.state, self.settings, "玩具进入", relief=relief["relief"],
                    blood_key=blood_key, force=True)
            else:
                hymen = body.add_hymen_damage(
                    self.state, self.settings,
                    self.settings.float("hymen.toy_damage", 0.0, 100.0),
                    blood_key=blood_key)
                if not hymen.get("ruptured"):
                    hymen = {"damage": hymen.get("damage"), "ruptured": False}
            if hymen:
                info["hymen"] = hymen
                if hymen.get("blood"):
                    menstrual.add_pad_fluid(self.state, self.settings, "处子血", 2.0)
                if hymen.get("pleasure"):
                    state_mod.add_pleasure(self.state, self.settings, hymen["pleasure"])

        # 日常用（不在亲密场景里）：先开/续"日常小场景"，这样对应部位的子敏感度才涨得起来
        state_mod_daily = None
        if not in_scene and self.settings.bool("toys.daily_scene"):
            window = max(1, self.settings.int("toys.daily_minutes", 1, 240)) * 60
            was_daily = state_mod.daily_active(self.state, self.settings)
            state_mod.touch_daily(self.state, str(info.get("place") or ""), key,
                                  window_seconds=window)
            if not was_daily:
                night.mark_activity(self.state, "daily")
                lewd.add(self.state, self.settings, self.settings.float(
                    "lewd.daily_add", 0.0, 100.0))
            state_mod_daily = state_mod.daily_payload(self.state, self.settings)

        # 子敏感度：日常和场景都推高"这次碰到的那个部位"
        zone = str(info.get("place") or "")
        sub = None
        activity = in_scene or state_mod.daily_active(self.state, self.settings)
        if zone and self.settings.bool("toys.sub_zone") and \
                intimacy.zone_enabled_effective(self.state, self.settings, zone):
            method = "toy" if "toy" in subzone.methods_of(zone) else ""
            sub = subzone.apply_touch(
                self.state, self.settings, zone, times=1, method=method,
                in_scene=activity,
                sensitivity=util.safe_float(
                    intimacy.zone_sensitivity_effective(self.state, self.settings, zone), 1.0))
            info["sub"] = sub

        daily = None
        if state_mod_daily is not None:
            daily = state_mod_daily
            state_mod.append_log(
                self.state, "daily",
                f"日常小场景：{info['label']}（{info['intensity_label']}"
                f"{'·' + info['place_label'] if info.get('place_label') else ''}），"
                f"{daily['remaining']} 分钟内算这一段（{trigger}）")
            info["daily"] = daily

        state_mod.append_log(
            self.state, "toy",
            f"{info['label']}（{info['intensity_label']}·{info['place_label']}）："
            f"快感 +{info['gain']:.1f}："
            f"{info['before']:.0f} → {info['value']:.0f}（{trigger}）")

        # 湿润度：玩具也算碰了几下
        self._sleep_note()
        self._gain_wetness(touch=1, pleasure=util.safe_float(info.get("gain"), 0.0))
        info["wetness"] = wetness.payload(self.state, self.settings)

        # 小玩具额外攒一点忍耐（可调）；日常用正好是"特别档位"那个玩具就多涨
        if endurance.enabled(self.settings):
            extra_end = self.settings.float("toys.endurance_gain", 0.0, 200.0)
            if extra_end > 0:
                endurance.add_extra(self.state, self.settings, extra_end)
                info["endurance_gain"] = extra_end
        if True:
            daily_hit = special.daily_roll(self.state, self.settings, key)
            if daily_hit:
                extra = daily_hit.get("pleasure") or 0.0
                if extra > 0:
                    value = state_mod.add_pleasure(self.state, self.settings, extra)
                    info["value"] = value
                    info["gain"] = round(util.safe_float(info.get("gain"), 0.0) + extra, 2)
                extra_end = daily_hit.get("endurance") or 0.0
                if extra_end > 0:
                    endurance.add_extra(self.state, self.settings, extra_end)
                info["special"] = daily_hit
                state_mod.append_log(
                    self.state, "special",
                    f"玩具撞上特别敏感档位：快感 +{extra:.0f}、忍耐 +{extra_end:.0f}"
                    f"（{trigger}）")

        # 忍耐条满了、这次又被刺激 → 到；没有忍耐条时退回旧的"快感过门槛"判断
        if endurance.enabled(self.settings):
            orgasm = self._endurance_orgasm(f"玩具·{info['label']}", was_full=full_before,
                                            open_scene=False)
            if orgasm:
                info["orgasm"] = orgasm
                if daily is not None:
                    state_mod.note_daily_orgasm(self.state)
                    info["daily"] = state_mod.daily_payload(self.state, self.settings)
        elif self.settings.bool("toys.auto_orgasm") and not in_scene:
            threshold = state_mod.effective_threshold(self.state, self.settings)
            combo_on = self.settings.bool("combo.enabled")
            limit = self._combo_limit()
            combo_now = state_mod.combo_count(self.state, self.settings) if combo_on else 0
            can_try = (not state_mod.overstimulated(self.state)
                       and not (combo_on and combo_now >= limit))
            if can_try and util.safe_float(info.get("value"), 0.0) >= threshold:
                orgasm = self._record_orgasm(f"玩具·{info['label']}", open_scene=False)
                if orgasm and not orgasm.get("refused"):
                    info["orgasm"] = orgasm
                    if daily is not None:
                        state_mod.note_daily_orgasm(self.state)
                        info["daily"] = state_mod.daily_payload(self.state, self.settings)
                    logger.info("[受孕] 玩具把她弄到了一次：%s", info["label"])

        # 日常情绪：每次激发小玩具，欲望度和羞耻度都涨
        if self.settings.bool("mood.enabled"):
            gains = mood.add_toy_gain(self.state, self.settings)
            info["mood"] = gains
            state_mod.append_log(
                self.state, "mood",
                f"小玩具之后：欲望度 {gains['desire']:.0f}（+{gains['desire_gain']:.0f}）、"
                f"羞耻度 {gains['shame']:.0f}（+{gains['shame_gain']:.0f}）（{trigger}）")
            # 羞耻满溢：加一点鱼之心的责怪 + 进羞耻期
            if mood.shame_full(self.state, self.settings):
                minutes = mood.start_shame_period(self.state, self.settings)
                info["shame_full"] = {"minutes": minutes}
                blame = None
                amount = tuning.get(self.state, "mood", "shame_blame",
                                    self.settings.float("mood.shame_blame", 0.0, 100.0))
                if amount > 0:
                    try:
                        blame = boost.boost_fish_blame(self.context, self.settings, amount)
                    except Exception as error:
                        logger.warning("[受孕] 写鱼之心责怪失败：%s", error)
                        blame = {"ok": False, "reason": str(error)}
                info["shame_full"]["blame"] = blame
                state_mod.append_log(
                    self.state, "mood",
                    f"羞耻满溢：进羞耻期 {minutes} 分钟（这段时间玩具不可用）"
                    + (f"；鱼之心责怪 +{blame.get('added', 0):.1f}"
                       if (blame or {}).get("ok") else ""))
                logger.info("[受孕] 羞耻满溢：羞耻期 %s 分钟", minutes)
            # 欲望满溢：直接诱发成正式的受孕活动场景
            daily_desire, _, _ = self._desire_pick("daily_scene")
            scene_cool = max(0, int(tuning.get(
                self.state, "mood", "self_approach_after_scene_minutes",
                self.settings.int("mood.self_approach_after_scene_minutes", 0, 1440)))) * 60
            last_scene_at = state_mod.scene_last_at(self.state)
            quiet_after_scene = bool(
                last_scene_at and util.now_ts() - last_scene_at < scene_cool)
            if self.settings.bool("mood.enabled") and not \
                    state_mod.scene_active(self.state, self.settings) and \
                    not quiet_after_scene and mood.desire_full(
                        self.state, self.settings, value=daily_desire):
                mood.note_desire_full(self.state, self.settings)
                state_mod.append_log(
                    self.state, "mood",
                    "欲望满溢：她自己贴上来，日常小场景转成正式受孕活动")
                self._touch_scene("欲望满溢")
                info["desire_full"] = True

        self._save()
        return info

    def _expel_uterus(self, trigger: str) -> dict:
        """把子宫里的东西排出来；怀孕时禁止（不能排胎儿）。"""
        ok, why = self._gate()
        if not ok:
            return {"refused": why}
        prog = pregnancy.progress(self.state)
        if prog:
            return {"refused": "她正在孕期：不能把胎儿当成精液排出去"}
        info = body.expel_uterus(self.state)
        if info["before"] <= 0:
            self._save()
            return {"empty": True, "before": 0.0}
        # 排干净了：撑开和溢出的记录也一起清掉
        fill.clear(self.state)
        info["after"] = 0.0
        state_mod.append_log(
            self.state, "expel",
            f"排出子宫里的东西：{info['before']:.1f} → 0 ml（{trigger}）")
        self._save()
        return info

    def _contraception_pill(self, action: str, trigger: str) -> dict:
        ok, why = self._gate()
        if not ok:
            return {"refused": why}
        if not self.settings.bool("contraception.pill_enabled"):
            return {"refused": "避孕药功能关着"}
        if action in ("take", "吃", "吃了"):
            info = body.take_pill(self.state, self.settings)
            state_mod.append_log(
                self.state, "contraception",
                f"吃了避孕药（{info['hours']:.0f} 小时内有效；{trigger}）")
            self._save()
            return info
        if action in ("stop", "停", "停了"):
            body.stop_pill(self.state)
            state_mod.append_log(self.state, "contraception", f"停了避孕药（{trigger}）")
            self._save()
            return {"stopped": True}
        return {"status": body.contraception_payload(self.state, self.settings)}

    def _contraception_condom(self, used: bool, trigger: str) -> dict:
        ok, why = self._gate()
        if not ok:
            return {"refused": why}
        if not self.settings.bool("contraception.condom_enabled"):
            return {"refused": "避孕套功能关着"}
        body.set_condom(self.state, used)
        state_mod.append_log(
            self.state, "contraception",
            f"{'戴上' if used else '摘下'}避孕套（{trigger}）")
        self._save()
        return {"condom": used, "status": body.contraception_payload(self.state, self.settings)}

    TUNE_SPEC = {
        "adult": {
            "scene_window_minutes": (1, 720, True),
        },
        "contraception": {
            "pill_effectiveness": (0, 100, False),
            "condom_effectiveness": (0, 100, False),
            "condom_break_chance": (0, 100, False),
            "pill_proactive_chance": (0, 100, False),
            "pill_proactive_window_minutes": (1, 120, True),
            "pill_proactive_cooldown_minutes": (0, 1440, True),
            "pill_proactive_delay_seconds": (0, 300, True),
            "pill_blame_chance": (0, 100, False),
            "pill_blame_amount": (0, 100, False),
            "pill_blame_window_minutes": (0, 1440, True),
        },
        "zones": {
            "sens_decay_after_minutes": (0, 10080, True),
            "sens_decay_per_hour": (0, 10, False),
        },
        "asmr": {            "default_minutes": (1, 240, True),
            "extend_minutes": (1, 120, True),
            "max_minutes": (1, 240, True),
            "sleep_relief": (0, 100, False),
            "sleep_relief_cap": (0, 200, False),
            "sleep_relief_daily_cap": (0, 200, False),
            "intimacy_gain": (0, 100, False),
            "intimacy_cap": (0, 100, False),
            "attachment_gain": (0, 100, False),
            "attachment_cap": (0, 100, False),
            "ear_sens_gain": (0, 1, False),
            "ear_sens_cap": (0, 2, False),
            "pleasure_gain": (0, 100, False),
            "pleasure_cap": (0, 100, False),
            "endurance_gain": (0, 100, False),
            "endurance_cap": (0, 100, False),
            "shame_gain": (0, 100, False),
            "shame_cap": (0, 100, False),
            "shame_decay_per_session": (0, 10, False),
            "shame_floor": (0, 100, False),
            "wet_gain": (0, 100, False),
            "wet_cap": (0, 100, False),
            "pregnancy_relief": (0, 100, False),
            "pregnancy_relief_cap": (0, 100, False),
            "sleep_chance": (0, 100, False),
            "request_start_hour": (0, 23, True),
            "request_end_hour": (0, 23, True),
            "request_chance": (0, 100, False),
            "request_wait_minutes": (1, 120, True),
        },
        "clothing": {
            "remove_shame": (0, 100, False),            "remove_shame_max": (0, 100, False),
            "remove_desire": (0, 100, False),
            "wear_shame_relief": (0, 100, False),
            "change_minutes": (0, 60, True),
            "undress_minutes": (0, 60, True),
        },
        "edge": {
            "auto_full_minutes": (0, 240, True),
        },
        "orgasm": {
            "minutes": (1, 240, True),
        },
        "ejaculation": {
            "volume_ml": (0.1, 100, False),
        },
        "uterus": {
            "leak_per_hour": (0, 100, False),
            "capacity_ml": (1, 500, False),
            "stretch_at": (0, 1, False),
            "stretch_ratio": (0, 2, False),
            "overflow_at": (0, 1, False),
            "overflow_minutes": (0, 1440, True),
            "after_leak_per_hour": (0, 100, False),
            "after_leak_until": (0, 100, False),
        },
        "endurance": {
            "cap": (1, 1000, False),
            "gain_at": (0, 1000, False),
            "gain_multiplier": (0, 10, False),
            "gain_low": (0, 200, False),
            "gain_high": (0, 200, False),
            "combo_grow": (0, 5, False),
            "combo_cap": (1, 20, False),
            "reset_minutes": (0, 1440, True),
            "idle_minutes": (0, 1440, True),
            "decay_per_hour": (0, 500, False),
            "level_at_1": (0, 100, False),
            "level_at_2": (0, 100, False),
            "level_at_3": (0, 100, False),
            "sens_boost": (0, 5, False),
        },
        "pleasure": {
            "decay_per_hour": (0, 500, False),
            "idle_minutes": (0, 1440, True),
            "post_orgasm_minutes": (0, 120, True),
        },
        "special": {
            "every_minutes": (1, 720, True),
            "jitter_percent": (0, 100, False),
            "pleasure_bonus": (0, 200, False),
            "endurance_bonus": (0, 200, False),
            "daily_chance": (0, 100, False),
            "daily_pleasure": (0, 200, False),
            "daily_endurance": (0, 200, False),
        },
        "toys": {
            "endurance_gain": (0, 200, False),
            "mg_soft_attachment": (0, 100, False),
            "mg_soft_intimacy": (0, 100, False),
            "mg_soft_desire": (0, 100, False),
            "mg_body_pleasure": (0, 100, False),
            "mg_body_desire": (0, 100, False),
            "mg_body_wet": (0, 100, False),
            "mg_body_endurance": (0, 100, False),
            "mg_hot_pleasure": (0, 100, False),
            "mg_hot_desire": (0, 100, False),
            "mg_hot_wet": (0, 100, False),
            "mg_hot_endurance": (0, 100, False),
            "self_use_chance": (0, 100, False),
            "self_use_check_minutes": (1, 1440, True),
            "self_use_cooldown_minutes": (0, 1440, True),
            "self_use_min_desire": (0, 100, False),
            "self_use_min_wet": (0, 100, False),
            "self_use_min_lewd": (0, 100, False),
            "self_use_controller_chance": (0, 100, False),
            "self_use_delay_seconds": (0, 300, True),
        },
        "birth": {
            "water_wet": (0, 100, False),
            "pain_due": (0, 100, False),
            "pain_pre": (0, 100, False),
            "pain_active": (0, 100, False),
            "pain_per_minute": (0, 100, False),
            "pain_max": (1, 100, False),
            "comfort_relief": (0, 100, False),
            "comfort_cooldown_seconds": (0, 3600, True),
            "gap_minutes": (1, 1440, True),
            "resume_delay_seconds": (0, 3600, True),
        },
        "insert": {
            "wet_at": (0, 100, False),
            "pleasure_at": (0, 100, False),
            "pain": (0, 100, False),
            "orgasm_pain": (0, 100, False),
            "force_pain": (0, 100, False),
            "force_pleasure_drop": (0, 100, False),
            "force_endurance_drop": (0, 100, False),
            "force_wet_gain": (0, 100, False),
            "capacity_ml": (0, 500, False),
            "fetus_pain": (0, 100, False),
        },
        "unbirth": {
            "grow_step": (0.01, 1, False),
            "birth_min_ratio": (0.01, 1, False),
            "birth_difficulty": (0, 100, False),
            "birth_depth_steps": (0, 10, True),
            "birth_step_minutes": (1, 240, True),
            "resist_chance": (0, 100, False),
            "resist_add_steps": (0, 5, True),
            "request_chance": (0, 100, False),
            "request_check_minutes": (1, 1440, True),
            "request_cooldown_minutes": (0, 1440, True),
            "request_wait_minutes": (1, 120, True),
            "birth_giveup_after": (1, 20, True),
            "tube_stage2": (0, 100, False),
            "tube_stage3": (0, 100, False),
            "tube_stage4": (0, 100, False),
            "tube_unbirth": (0, 100, False),
            "ovary_prob": (0, 100, False),
            "tube_flow_base_minutes": (1, 240, True),
            "tube_fill_percent": (1, 100, True),
            "tube_flow_ref_ml": (0.1, 100, False),
            "hymen_pass_pleasure": (0, 100, False),
            "hymen_pass_endurance": (0, 100, False),
            "hymen_pass_wet": (0, 100, False),
            "hymen_pass_desire": (0, 100, False),
            "inside_pleasure": (0, 100, False),
            "inside_wet": (0, 100, False),
            "inside_endurance": (0, 100, False),
            "inside_dev": (0, 100, False),
            "inside_sens": (0, 10, False),
            "inside_max_minutes": (1, 1440, True),
            "shrink_ratio": (0.01, 1, False),
            "limit_factor": (0.1, 5, False),
            "expand_small": (0, 1, False),
            "expand_mid": (0, 1, False),
            "enter_pleasure": (0, 100, False),
            "enter_endurance": (0, 100, False),
            "enter_wet": (0, 100, False),
            "birth_steps": (1, 20, True),
            "resist_desire": (0, 100, False),
        },
        "condom": {
            "break_per_action": (0, 100, False),
            "remove_ask_chance": (0, 100, False),
            "remove_help_chance": (0, 100, False),
            "remove_min_minutes": (1, 240, True),
            "remove_cooldown_minutes": (1, 1440, True),
            "ask_chance": (0, 100, False),
            "renew_ask_chance": (0, 100, False),
            "unfelt_pleasure": (0, 100, False),
            "unfelt_endurance": (0, 100, False),
            "unfelt_chance": (0, 100, False),
            "change_ask_chance": (0, 100, False),
            "help_desire": (0, 100, False),
            "help_shame": (0, 100, False),
            "help_wet": (0, 100, False),
        },
        "squirt": {
            "water_max": (1, 1000, False),
            "regen_per_minute": (0, 100, False),
            "min_water": (0, 1000, False),
            "volume": (0, 500, False),
            "volume_pleasure": (0, 10, False),
            "volume_endurance": (0, 10, False),
            "combo_volume": (0, 10, False),
            "chance": (0, 100, False),
            "pleasure_bonus": (0, 100, False),
            "endurance_bonus": (0, 100, False),
            "after_bonus": (0, 100, False),
            "combo_bonus": (0, 100, False),
            "cost_ratio": (0, 10, False),
            "pleasure_gain": (0, 100, False),
            "pleasure_cap": (0, 100, False),
            "wet_gain": (0, 100, False),
            "endurance_gain": (0, 100, False),
        },
        "swallow": {
            "collect_pleasure": (0, 100, False),
            "desire_gain": (0, 100, False),
            "wet_gain": (0, 100, False),
            "swallow_pleasure": (0, 100, False),
            "swallow_desire": (0, 100, False),
            "swallow_wet": (0, 100, False),
            "auto_chance": (0, 100, False),
            "auto_swallow_chance": (0, 100, False),
        },
        "combo": {
            "overstim_after": (1, 20, True),
        },
        "menstrual": {
            "pad_shame_cap": (0, 100, False),
        },
        "children": {
            "intimacy_interrupt_chance": (0, 100, False),
            "intimacy_child_max_age_years": (1, 18, True),
        },
        "mood": {
            "shame_decay_per_hour": (0, 100, False),
            "desire_decay_per_hour": (0, 100, False),
            "self_approach_after_scene_minutes": (0, 1440, True),
        },
        "size": {
            "vagina_width": (0.2, 50, False),
            "hymen_hole": (0.1, 100, False),
            "hymen_depth": (0.5, 30, False),
            "penis_length": (1, 100, False),
            "penis_girth": (0.5, 50, False),
            "penis_head_length": (0.5, 50, False),
            "uterus_length": (1, 100, False),
            "tube_width": (0.1, 20, False),
            "ovary_width": (0.1, 20, False),
            "fetus_uterus_max_ratio": (1, 5, False),
            "vagina_length": (1, 100, False),
            "notice_chance": (0, 100, False),
            "dev_sens_boost": (0, 5, False),
            "pre_orgasm_shorten": (0, 20, False),
            "pre_orgasm_ratio": (0, 1, False),
            "cervix_stretch_max": (0, 20, False),
            "cervix_stretch_ratio": (0, 1, False),
            "cervix_stretch_minutes": (1, 240, True),
        },
        "sleep": {
            "wake_grace_minutes": (1, 240, True),
            "afterglow_minutes": (0, 240, True),
        },
        "self_test": {
            "chance": (0, 100, False),
            "min_delay_hours": (1, 720, True),
        },
        "surprise": {
            "proactive_chance": (0, 100, False),
            "proactive_delay_seconds": (0, 300, True),
            "shock_minutes": (1, 240, True),
            "remember_minutes": (1, 1440, True),
        },
        "wetness": {
            "base": (0, 100, False),
            "prompt_min_level": (1, 4, True),
            "gain_per_touch": (0, 100, False),
            "scene_step_gain": (0, 100, False),
            "daily_step_gain": (0, 100, False),
            "gain_per_pleasure": (0, 10, False),
            "idle_minutes": (0, 1440, True),
            "decay_per_hour": (0, 500, False),
            "level_at_1": (0, 100, False),
            "level_at_2": (0, 100, False),
            "level_at_3": (0, 100, False),
            "pain_wetness_at": (0, 100, False),
            "pain_pleasure_at": (0, 100, False),
            "pain_relief": (0, 100, False),
            "fish_desire_gain": (0, 100, False),
            "fish_desire_scale": (0, 10, False),
            "fish_desire_to_wet": (0, 100, False),
            "fish_desire_min_minutes": (0, 1440, True),
            "base_float_desire": (0, 100, False),
            "base_float_pleasure": (0, 100, False),
            "base_float_endurance": (0, 100, False),
            "base_float_cap": (0, 100, False),
        },
        "succubus": {
            "pc_energy_gain": (0, 100, True),
            "fish_attachment_gain": (0, 100, False),
            "fish_intimacy_gain": (0, 100, False),
            "ejaculation_energy_gain": (0, 100, True),
            "ejaculation_attachment_gain": (0, 100, False),
            "ejaculation_intimacy_gain": (0, 100, False),
            "desire_base_gain": (0, 100, False),
            "desire_gain_per_level": (0, 100, False),
            "absorption_multiplier": (1, 100, False),
            "tail_sensitivity_scale": (1, 5, False),
            "daily_limit": (0, 100, True),
            "exp_gain": (0, 1000, True),
            "exp_per_level": (1, 10000, True),
        },
        "lewd": {
            "max": (1, 1000, False),
            "scene_add": (0, 100, False),
            "daily_add": (0, 100, False),
            "tick_minutes": (1, 1440, True),
            "tick_min": (0, 100, False),
            "cost_per_tick": (0, 100, False),
            "desire_per_tick": (0, 100, False),
            "wet_per_tick": (0, 100, False),
            "decay_after_minutes": (0, 10080, True),
            "decay_per_hour": (0, 100, False),
            "prompt_min": (0, 100, False),
            "level_at_2": (0, 100, False),
            "level_at_3": (0, 100, False),
            "level_at_4": (0, 100, False),
        },
        "night_raid": {
            "start_hour": (0, 23, True),
            "end_hour": (0, 23, True),
            "desire_min": (0, 100, False),
            "very_high_desire": (0, 100, False),
            "very_high_wet_min": (0, 100, False),
            "very_high_bonus": (0, 100, False),
            "wet_min": (0, 100, False),
            "chance": (0, 100, False),
            "pregnancy_chance": (0, 100, False),
            "activity_window_minutes": (1, 1440, True),
            "after_ejac_minutes": (0, 1440, True),
            "after_ejac_factor": (0, 1, False),
            "unfinished_minutes": (0, 1440, True),
            "unfinished_bonus": (0, 100, False),
            "lead_minutes": (0, 180, True),
            "wait_minutes": (1, 120, True),
            "afterglow_minutes": (0, 120, True),
            "after_scene_minutes": (0, 1440, True),
            "cooldown_hours": (0, 168, True),
            "lewd_late_per_point": (0, 100, False),
            "lewd_late_max": (0, 100, False),
            "fish_stay_up_bonus": (0, 100, False),
            "energy_gain": (0, 100, True),
        },
    }

    def _set_tuning(self, section: str, key: str, value) -> dict:
        spec = (self.TUNE_SPEC.get(section) or {}).get(key)
        if not spec:
            return {"refused": f"不认识的可调项：{section}.{key}"}
        low, high, as_int = spec
        try:
            number = float(value)
        except (TypeError, ValueError):
            return {"refused": "数值不对"}
        number = max(low, min(high, number))
        number = int(round(number)) if as_int else round(number, 2)
        tuning.set_value(self.state, section, key, number)
        self._persist_config_value((section, key), number)
        self._save()
        return {"section": section, "key": key, "value": number}

    def _config_path(self, section: str, key: str) -> str:
        aliases = {
            ("uterus", "leak_per_hour"): "ejaculation.uterus_leak_per_hour",
            ("uterus", "capacity_ml"): "ejaculation.uterus_capacity_ml",
            ("uterus", "stretch_at"): "ejaculation.uterus_stretch_at",
            ("uterus", "stretch_ratio"): "ejaculation.uterus_stretch_ratio",
            ("uterus", "overflow_at"): "ejaculation.uterus_overflow_at",
            ("uterus", "overflow_minutes"): "ejaculation.uterus_overflow_minutes",
            ("uterus", "after_leak_per_hour"): "ejaculation.uterus_after_leak_per_hour",
            ("uterus", "after_leak_until"): "ejaculation.uterus_after_leak_until",
        }
        return aliases.get((section, key), f"{section}.{key}")

    def _persist_config_value(self, path, value) -> bool:
        """把面板上的值写回 AstrBot 配置文件（配置页同步）。"""
        if isinstance(path, str):
            parts = path.split(".")
        else:
            parts = list(path)
        if not parts:
            return False
        if type(self.context).__name__ == "StubContext":
            return False
        import copy
        file = CONFIG_DIR / f"{PLUGIN_NAME}_config.json"
        try:
            disk = json.loads(file.read_text(encoding="utf-8-sig"))
            data = disk if isinstance(disk, dict) else copy.deepcopy(self.settings.config)
        except Exception:
            data = copy.deepcopy(self.settings.config)
        if not isinstance(data, dict):
            return False
        node = data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = value
        try:
            file.write_text(json.dumps(data, ensure_ascii=False, indent=2)
                            + "\n", encoding="utf-8-sig")
            # 只把这一项同步进当前内存配置，别用整份旧配置覆盖磁盘上的其它项
            mem = self.settings.config
            for part in parts[:-1]:
                child = mem.get(part)
                if not isinstance(child, dict):
                    child = {}
                    mem[part] = child
                mem = child
            mem[parts[-1]] = value
            return True
        except Exception as error:
            logger.warning("[受孕] 同步写配置失败：%s", error)
            return False

    def _succubus_set_level(self, value=None, delta=None) -> dict:
        current = succubus.level(self.state, self.settings)
        target = current + int(delta or 0) if delta is not None else int(value if value is not None else current)
        target = succubus.set_level(self.state, self.settings, target)
        state_mod.append_log(self.state, "succubus", f"淫纹等级调到 Lv.{target}")
        self._save()
        return {"level": target}

    def _succubus_set_willing(self, value) -> dict:
        if value in (None, "", "unknown", "未表态"):
            succubus.set_willing(self.state, None)
            label = "未表态"
        else:
            willing = bool(value)
            succubus.set_willing(self.state, willing)
            label = "愿意怀" if willing else "不愿意怀"
        state_mod.append_log(self.state, "succubus", f"怀孕意愿：{label}")
        self._save()
        return {"willing": succubus.willing(self.state), "label": label}

    def _restore_hymen(self, trigger: str) -> dict:
        body.restore_hymen(self.state)
        state_mod.append_log(self.state, "hymen", f"处女膜恢复完整（{trigger}）")
        self._save()
        return {"intact": True}

    def _record_ejaculation(self, mode: str | bool = "vagina", trigger: str = "",
                            depth: float = 0.0, hymen_break: bool = False) -> dict:
        ok, why = self._gate()
        if not ok:
            return {"refused": why}
        key = intimacy.normalize_mode(mode)
        if not key:
            return {"refused": f"不认识的射精方式：{mode}"}
        ub_inside = unbirth.inside(self.state, self.settings)
        if ub_inside:
            unbirth.settle(self.state, self.settings)
        insert_stage = 0
        if uterus_insert.data(self.state).get("active"):
            insert_stage = uterus_insert.stage_of(self.state, self.settings)
        if key == "tube" and not (ub_inside or insert_stage >= 2):
            return {"refused": "还没顶到那么深：要先让阴茎头几乎全进来/整个进来/插满，"
                               "或者用 Unbirth 待在子宫里，才射得到输卵管/卵巢"}
        self._surprise_note(f"ejaculation_{key}" if key in
                            ("vagina", "anal", "throat", "outside") else "ejaculation")
        self._touch_scene("射精")
        self._sleep_note()
        was_pregnant = pregnancy.is_pregnant(self.state)
        last_orgasm = util.safe_float(self.state.get("last_orgasm_at"), 0.0)
        was_orgasm = bool(last_orgasm and util.now_ts() - last_orgasm <= 60)
        info = state_mod.add_ejaculation(self.state, self.settings, mode=key)
        self.state["last_ejaculation_volume"] = round(intimacy.mode_volume(self.settings), 2)
        menstrual.add_pad_fluid(self.state, self.settings, "精液", 3.0)
        self._note_text_event("ejaculation")

        notes = []
        condom_protected = False
        if key == "vagina" and not ub_inside and body.condom_on(self.state):
            end_now = endurance.payload(self.state, self.settings) if endurance.enabled(
                self.settings) else {}
            brk = condom.break_roll(
                self.state, self.settings,
                pleasure=util.safe_float(self.state.get("pleasure"), 0.0),
                endurance_percent=util.safe_float(end_now.get("percent"), 0.0),
                at_ejaculation=True)
            if not brk and body.condom_breaks(self.settings, self.state):
                body.set_condom(self.state, False)
                notes.append("避孕套破了")
            elif brk:
                notes.append(brk.get("line") or "避孕套破了")
            else:
                condom_protected = True
                notes.append("戴着避孕套")

        hymen = None
        if key == "vagina" and not ub_inside and (
                hymen_break or depth > size.hymen_depth(self.state, self.settings)):
            relief = wetness.hymen_relief(
                self.state, self.settings,
                pleasure=util.safe_float(self.state.get("pleasure"), 0.0))
            hymen = body.rupture_hymen(self.state, self.settings, "第一次进入",
                                       relief=relief["relief"], blood_key="penis",
                                       force=True)
            if hymen:
                notes.append(self._hymen_note(hymen))
                if hymen.get("blood"):
                    notes.append(hymen["blood"])
                if hymen.get("pleasure"):
                    state_mod.add_pleasure(self.state, self.settings, hymen["pleasure"])

        gain = intimacy.mode_pleasure(self.settings, key) * body.pleasure_scale(self.settings, self.state)
        if gain:
            state_mod.add_pleasure(self.state, self.settings, gain)
        lewd_gain = self.settings.float("conception.ejaculation_lewd", 0.0, 100.0)
        if lewd_gain:
            lewd.add(self.state, self.settings, lewd_gain)
        endurance_gain = self.settings.float("conception.ejaculation_endurance", 0.0, 100.0)
        if endurance_gain:
            endurance.add_extra(self.state, self.settings, endurance_gain)
        if was_orgasm:
            extra_pleasure = self.settings.float("conception.simultaneous_pleasure", 0.0, 100.0)
            extra_endurance = self.settings.float("conception.simultaneous_endurance", 0.0, 100.0)
            if extra_pleasure:
                state_mod.add_pleasure(self.state, self.settings, extra_pleasure)
            if extra_endurance:
                endurance.add_extra(self.state, self.settings, extra_endurance)
        self._maybe_write_memory(
            memory_link.activity_value(self.settings,
                                       mode_label=intimacy.MODE_LABELS.get(key, key)),
            reason="受孕·活动")

        uterus = None
        cloth_line = clothing.ejac_prompt(self.state, self.settings, key,
                                          in_shoe=("鞋里" in str(trigger or "")))
        if cloth_line:
            notes.append(cloth_line)
        inner = insert_effects.inner(self.state, self.settings, key)
        if key == "tube":
            situation = "unbirth" if ub_inside else f"stage{insert_stage}"
            chance = tuning.get(
                self.state, "unbirth", f"tube_{situation}",
                self.settings.float(f"unbirth.tube_{situation}", 0.0, 100.0))
            prog = pregnancy.progress(self.state)
            hit = False
            rolled = False
            if not prog:
                rolled = True
                hit = random.random() * 100.0 < chance
                if hit:
                    self._start_pregnancy(chance, trigger)
            result = {"rolled": rolled, "hit": hit, "mode": key,
                      "probability": round(chance, 1), "situation": situation,
                      "reason": (f"已在孕期" if prog else
                                 f"射进输卵管（{situation}，{chance:.0f}%）")}
            self.state["last_roll"] = {
                "at": util.now_ts(), "probability": round(chance, 1),
                "hit": bool(hit), "phase": (self._cycle() or {}).get("phase"),
                "inside": True, "mode": key, "situation": situation,
            }
            if key == "tube" and rolled and not hit:
                volume = intimacy.mode_volume(self.settings)
                pregnancy.schedule_tube_flow(self.state, self.settings,
                                             trigger=trigger, volume_ml=volume)
            tube_line = prompts.text(self.state, "unbirth", f"{key}_{situation}")
            if tube_line:
                result["tube_prompt"] = tube_line
                self.state["ejac_site"] = {"at": util.now_ts(), "line": tube_line,
                                           "zone": "uterus"}
            state_mod.append_log(
                self.state, "roll",
                f"射进输卵管（{situation}，概率 {chance:.0f}%）："
                f"{'受孕' if hit else '未受孕，精液会慢慢流进卵巢'}")
        elif ub_inside:
            internal = key != "outside"
            if internal:
                uterus = fill.add(self.state, self.settings)
                result = self._roll_conception(inside=True, trigger=trigger)
            else:
                result = {"rolled": False, "hit": False, "mode": key,
                          "reason": "从阴道口向外射，算体外",
                          "inside": False, "unbirth_internal": False}
                self.state["last_roll"] = {
                    "at": util.now_ts(), "probability": 0.0, "hit": False,
                    "phase": (self._cycle() or {}).get("phase"), "inside": False,
                    "mode": key,
                }
            result["unbirth_internal"] = internal
            ub_line = prompts.text(
                self.state, "unbirth",
                "ejac_internal" if internal else "ejac_outside",
                label=intimacy.MODE_LABELS.get(key, key))
            if ub_line:
                result["unbirth_ejac"] = ub_line
                self.state["ejac_site"] = {
                    "at": util.now_ts(), "line": ub_line,
                    "zone": "uterus" if internal else "vulva"}
        elif key == "vagina":
            if not condom_protected:
                uterus = fill.add(self.state, self.settings)
            result = self._roll_conception(inside=True, trigger=trigger)
            if condom_protected:
                result["condom"] = True
        elif key in ("anal", "throat"):
            scale = self.settings.float(f"conception.{key}_scale", 0.0, 1.0)
            result = self._roll_conception(inside=True, trigger=trigger, scale=scale)
            result["low_route"] = key
            result["route_scale"] = scale
        else:
            result = {"rolled": False, "hit": False, "mode": key,
                      "reason": f"{intimacy.MODE_LABELS[key]}，不判定受孕"}
            self.state["last_roll"] = {
                "at": util.now_ts(), "probability": 0.0, "hit": False,
                "phase": (self._cycle() or {}).get("phase"), "inside": False,
                "mode": key,
            }
        result["inner_wet"] = inner
        if key != "tube" and uterus and not result.get("hit"):
            fill_percent = tuning.get(self.state, "unbirth", "tube_fill_percent",
                                      self.settings.int("unbirth.tube_fill_percent", 1, 100))
            if util.safe_float(uterus.get("percent"), 0.0) >= float(fill_percent):
                pregnancy.schedule_tube_flow(
                    self.state, self.settings, trigger=trigger,
                    volume_ml=intimacy.mode_volume(self.settings))
        last_touch = self.state.get("last_touch") if isinstance(
            self.state.get("last_touch"), dict) else {}
        site = str(last_touch.get("zone") or "")
        site_map = {"vulva": "vulva", "vagina": "vagina", "gspot": "gspot",
                    "cervix": "cervix", "uterus": "uterus", "anus": "anus",
                    "mouth": "mouth", "breast": "breast", "nipple": "breast",
                    "foot": "foot", "tail": "tail", "ear": "ear",
                    "hand": "hand", "kiss": "face", "hair": "hair",
                    "back": "back", "leg": "leg", "belly": "belly"}
        site_key = site_map.get(site, "")
        if site_key and not ub_inside:
            site_line = prompts.text(self.state, "ejac", site_key)
            if site_line:
                result["site_prompt"] = site_line
                self.state["ejac_site"] = {"at": util.now_ts(), "line": site_line,
                                           "zone": site_key}

        if key == "vagina" and not ub_inside:
            body.set_condom(self.state, False)

        if key == "outside" and clothing.worn_key(self.state, self.settings, "underwear"):
            clothing.mark_panties_wet(self.state, "semen")
        if key == "vagina" or (ub_inside and key != "outside"):
            blame = self._maybe_pill_blame()
            if blame:
                result["pill_blame"] = blame

        label = intimacy.MODE_LABELS.get(key, key)
        extra = ""
        if uterus:
            extra = (f"；子宫 {uterus['ml']:.1f}/{uterus['capacity_effective']:.0f} ml"
                     f"（{uterus['level_title']}）")
            if uterus.get("stretch"):
                extra += f"，撑开 +{uterus['stretch_percent']:.0f}%"
            if uterus.get("overflow"):
                extra += f"，溢出来 {uterus['overflow']:.1f} ml"
        if notes:
            extra += "；" + "；".join(notes)
        state_mod.append_log(
            self.state, "ejaculation",
            f"{label}（本次第 {info['session']} 次；快感 +{gain:.0f}{extra}；{trigger}）")
        if ub_inside and result.get("unbirth_internal") and not was_pregnant:
            self._maybe_schedule_self_test(trigger)
        elif key == "vagina" and not was_pregnant:
            self._maybe_schedule_self_test(trigger)
        succubus_info = self._succubus_after_ejaculation(key)
        if succubus_info:
            result["succubus"] = succubus_info
        if state_mod.scene_active(self.state, self.settings) or \
                state_mod.daily_active(self.state, self.settings):
            night.mark_ejaculation(self.state)
        self._save()
        result["count"] = info
        result["mode"] = key
        result["pleasure_gain"] = gain
        if uterus:
            result["uterus"] = uterus
        if hymen:
            result["hymen"] = hymen
        auto = swallow.auto_after_ejaculation(self.state, self.settings, mode=key)
        if auto:
            result["swallow_auto"] = auto
            if auto.get("line"):
                notes.append(auto["line"])
            if auto.get("swallowed"):
                state_mod.append_log(self.state, "swallow", "她自主收集并吞了下去")
            else:
                state_mod.append_log(self.state, "swallow", "她自主收集了")
        if notes:
            result["notes"] = notes
        if key == "throat" or auto:
            line = ""
            if auto:
                line = auto.get("swallow_line") or auto.get("line") or ""
            if not line and key == "throat":
                line = prompts.text(self.state, "swallow", "mouth")
            if line:
                self.state["swallow_event_note"] = {"at": util.now_ts(), "line": line}
                self._save()
        return result

    def _maybe_schedule_self_test(self, trigger: str) -> None:
        """受孕活动之后，有概率让她过一阵子自己起念去验孕。"""
        if not self.settings.bool("self_test.enabled"):
            return
        chance = self.settings.float("self_test.chance", 0.0, 100.0)
        if chance <= 0 or random.random() * 100 >= chance:
            return
        if pregnancy.schedule_self_test(self.state, self.settings):
            window = pregnancy.self_test_window(self.state)
            when = datetime.fromtimestamp(window["due_at"]).strftime("%m-%d %H:%M") if window else "—"
            state_mod.append_log(self.state, "self_test",
                                 f"她自己起了验孕的念头（约 {when} 之后；{trigger}）")
            logger.info("[受孕] 已安排一次自查（约 %s 之后）", when)

    # ================================================================ 关键词识别

    def _match_any(self, text: str, words: list[str]) -> bool:
        body = text or ""
        return any(word and word in body for word in words)

    def _mode_from_text(self, text: str) -> str:
        body = text or ""
        if self._match_any(body, ("肛内", "后庭里", "射在肛", "肛门里", "射进后庭", "菊里")):
            return "anal"
        if self._match_any(body, ("深喉", "射在喉咙", "射进喉咙", "喉咙里", "射在嘴里")):
            return "throat"
        if self._match_any(body, ("输卵管", "卵管", "射进管子", "射进输卵管")):
            return "tube"
        if self._match_any(body, ("体外", "外面", "射在外", "射到外面", "脸上", "肚子上")):
            return "outside"
        return "vagina"

    def _detect_touches(self, text: str, data: dict | None, trigger: str) -> None:
        """从对话里认出亲/摸哪个部位（同一部位 45 秒内不重复记）。"""
        if not self.settings.bool("zones.enabled") or \
                not self.settings.bool("zones.keyword_detect"):
            return
        if self.settings.bool("adult.detect_requires_scene"):
            in_scene, _ = self._scene_active(data)
            if not in_scene:
                return
        now = util.now_ts()
        last = self.state.get("_zone_text_at")
        if not isinstance(last, dict):
            last = {}
        for zone in intimacy.detect_zones(text, self.settings, self.state):
            if now - util.safe_float(last.get(zone), 0.0) < 45:
                continue
            method = subzone.detect_method(text, zone, self.state)
            if self._record_touch(zone, 1, trigger, method=method).get("refused"):
                continue
            last[zone] = now
        self.state["_zone_text_at"] = last

    def _text_event_ok(self, kind: str) -> bool:
        """同一件事在去重窗口里只记一次（工具记过就不再从文字里重复记）。"""
        dedupe = max(0, self.settings.int("adult.reply_dedupe_seconds", 0, 600))
        last = self.state.get("_last_text_event") or {}
        if last.get("kind") != kind:
            return True
        return util.now_ts() - util.safe_float(last.get("at"), 0.0) >= dedupe

    def _note_text_event(self, kind: str) -> None:
        self.state["_last_text_event"] = {"kind": kind, "at": util.now_ts()}

    def _desire_pick(self, feature: str) -> tuple[float, str, dict]:
        """按功能自己的来源策略读欲望，返回 (值, 来源, 各来源)。"""
        fish = self._fish_desire()
        dark = None
        try:
            snap = self._read_sources().get("dark")
            if snap is not None and getattr(snap, "available", False):
                dark = float(getattr(snap, "lust", 0.0))
        except Exception:
            pass
        value, source, parts = desire.pick(
            self.state, self.settings, feature, fish=fish, dark=dark)
        return value, source, parts

    def _night_desire(self) -> tuple[float, str, dict]:
        return self._desire_pick("night_raid")

    def _night_window(self) -> tuple[datetime, datetime]:
        """当前/下一段夜袭窗口（处理跨午夜）。"""
        now = datetime.now()
        start_hour = int(tuning.get(self.state, "night_raid", "start_hour",
                                    self.settings.int("night_raid.start_hour", 0, 23)))
        end_hour = int(tuning.get(self.state, "night_raid", "end_hour",
                                  self.settings.int("night_raid.end_hour", 0, 23)))
        duration = (end_hour - start_hour) % 24 or 24
        start = datetime(now.year, now.month, now.day, start_hour)
        end = start + timedelta(hours=duration)
        if now >= end:
            start += timedelta(days=1)
            end += timedelta(days=1)
        elif now < start:
            prev_start = start - timedelta(days=1)
            prev_end = end - timedelta(days=1)
            if prev_start <= now < prev_end:
                start, end = prev_start, prev_end
        return start, end

    def _night_forecast_payload(self) -> dict:
        """面板用：现在看今晚会不会夜袭、大概多少概率。"""
        now = util.now_ts()
        pending = isinstance(self.state.get("night_raid"), dict) and bool(
            self.state.get("night_raid"))
        start, end = self._night_window()
        base = {"at": start.strftime("%H:%M"), "end": end.strftime("%H:%M"),
                "minutes_to": max(0, int((start.timestamp() - now) / 60)),
                "lead_minutes": max(0, int(tuning.get(
                    self.state, "night_raid", "lead_minutes",
                    self.settings.int("night_raid.lead_minutes", 0, 180))))}
        if pending:
            return {**base, "phase": "pending", "label": "已发消息，等回应",
                    "chance": 100, "reason": "等你回应", "can": True}
        lead_start = start.timestamp() - base["lead_minutes"] * 60
        if now < lead_start:
            return {**base, "phase": "waiting", "label": "等待判断",
                    "chance": 0, "reason": f"窗口前 {base['lead_minutes']} 分钟显示预估",
                    "can": False}
        if not self.settings.bool("night_raid.enabled"):
            return {**base, "phase": "off", "label": "没开", "chance": 0, "reason": ""}
        if unbirth.inside(self.state, self.settings):
            return {**base, "phase": "blocked", "label": "不会", "chance": 0,
                    "reason": "正在 Unbirth"}
        if state_mod.scene_active(self.state, self.settings) or \
                state_mod.daily_active(self.state, self.settings):
            return {**base, "phase": "blocked", "label": "不会", "chance": 0,
                    "reason": "正在活动/小场景"}
        quiet_after_scene = max(0, int(tuning.get(
            self.state, "night_raid", "after_scene_minutes",
            self.settings.int("night_raid.after_scene_minutes", 0, 1440)))) * 60
        last_scene_at = state_mod.scene_last_at(self.state)
        if last_scene_at and now - last_scene_at < quiet_after_scene:
            left = max(1, int((quiet_after_scene - (now - last_scene_at)) // 60))
            return {**base, "phase": "blocked", "label": "不会", "chance": 0,
                    "reason": f"刚结束活动，还要缓 {left} 分钟"}
        cool = util.safe_float(self.state.get("night_raid_cool_at"), 0.0)
        cooldown = max(0, int(tuning.get(
            self.state, "night_raid", "cooldown_hours",
            self.settings.int("night_raid.cooldown_hours", 0, 168)))) * 3600
        if cool and now - cool < cooldown:
            left = max(1, int((cooldown - (now - cool)) / 60))
            return {**base, "phase": "cooldown", "label": "冷却中", "chance": 0,
                    "reason": f"还要 {left} 分钟"}
        desire, desire_source, desire_parts = self._night_desire()
        wet = lube.natural_wetness(self.state, self.settings)
        desire_min = float(tuning.get(self.state, "night_raid", "desire_min",
                                      self.settings.float("night_raid.desire_min", 0, 100)))
        wet_min = float(tuning.get(self.state, "night_raid", "wet_min",
                                   self.settings.float("night_raid.wet_min", 0, 100)))
        if desire < desire_min or wet < wet_min:
            return {**base, "phase": "blocked", "label": "不会", "chance": 0,
                    "desire_source": desire_source, "desire_parts": desire_parts,
                    "reason": f"欲望 {desire:.0f}/{desire_min:.0f}（{desire_source}）、"
                              f"自然湿润 {wet:.0f}/{wet_min:.0f}（不含润滑）还不够"}
        very_high_at = float(tuning.get(
            self.state, "night_raid", "very_high_desire",
            self.settings.float("night_raid.very_high_desire", 0, 100)))
        very_high_wet = float(tuning.get(
            self.state, "night_raid", "very_high_wet_min",
            self.settings.float("night_raid.very_high_wet_min", 0, 100)))
        very_high = desire >= very_high_at and wet >= very_high_wet
        chance_key = "pregnancy_chance" if pregnancy.is_pregnant(self.state) else "chance"
        chance = float(tuning.get(self.state, "night_raid", chance_key,
                                  self.settings.float(f"night_raid.{chance_key}", 0, 100)))
        if very_high:
            chance = min(100.0, chance + float(tuning.get(
                self.state, "night_raid", "very_high_bonus",
                self.settings.float("night_raid.very_high_bonus", 0, 100))))
        chance, note = night.adjust_chance(self.state, self.settings, chance)
        if note:
            base["reason"] = note
        late_chance = 100.0
        chance = max(0.0, min(100.0, chance))
        label = "会" if chance >= 50 else ("可能" if chance > 0 else "不会")
        return {**base, "phase": "forecast", "label": label,
                "chance": round(chance, 0), "very_high": bool(very_high),
                "late_chance": 100,
                "desire_source": desire_source, "desire_parts": desire_parts,
                "reason": base.get("reason") or ""}

    def _pill_proactive_enabled(self) -> bool:
        override = self.state.get("pill_proactive_enabled")
        if isinstance(override, bool):
            return override
        return self.settings.bool("contraception.pill_proactive_enabled")

    def _maybe_pill_offer(self, context: str = "") -> dict:
        """活动/夜袭前，她可能主动说自己要吃避孕药。"""
        if not self._pill_proactive_enabled():
            return {}
        if not self.settings.bool("contraception.pill_enabled"):
            return {}
        if body.pill_active(self.state):
            return {}
        if isinstance(self.state.get("pill_offer"), dict) and self.state["pill_offer"]:
            return {}
        now = util.now_ts()
        cool = util.safe_float(self.state.get("pill_offer_cool_at"), 0.0)
        cooldown = max(0, int(tuning.get(
            self.state, "contraception", "pill_proactive_cooldown_minutes",
            self.settings.int("contraception.pill_proactive_cooldown_minutes", 0, 1440)))) * 60
        if cool and now - cool < cooldown:
            return {}
        chance = float(tuning.get(
            self.state, "contraception", "pill_proactive_chance",
            self.settings.float("contraception.pill_proactive_chance", 0, 100)))
        if random.random() * 100 >= chance:
            return {}
        window = max(1, int(tuning.get(
            self.state, "contraception", "pill_proactive_window_minutes",
            self.settings.int("contraception.pill_proactive_window_minutes", 1, 120))))
        line = prompts.text(self.state, "pill", "offer")
        self.state["pill_offer"] = {"at": now, "until": now + window * 60,
                                    "context": str(context or ""), "took": False}
        self.state["pill_offer_note"] = {"at": now, "line": line}
        delay = max(0, int(tuning.get(
            self.state, "contraception", "pill_proactive_delay_seconds",
            self.settings.int("contraception.pill_proactive_delay_seconds", 0, 300))))
        self._schedule_notice(line, "受孕·避孕药", "pill_proactive", delay=delay)
        state_mod.append_log(self.state, "contraception",
                             f"她主动说想吃避孕药（{context or '活动前'}）")
        self._save()
        return {"sent": True, "line": line}

    def _finalize_pill_offer(self, took: bool, notify: bool = True,
                             refusal_text: str = "") -> dict:
        pending = self.state.get("pill_offer")
        if not isinstance(pending, dict) or not pending:
            return {}
        self.state["pill_offer"] = {}
        self.state["pill_offer_cool_at"] = util.now_ts()
        if not took:
            text = str(refusal_text or "")
            promise = self._match_any(
                text, self.settings.list("contraception.pill_inside_promise_keywords"))
            self.state["pill_refusal"] = {
                "at": util.now_ts(), "context": pending.get("context") or "",
                "promise": bool(promise), "text": text[:80], "used": False}
        else:
            self.state.pop("pill_refusal", None)
        if took:
            body.take_pill(self.state, self.settings)
            line = prompts.text(self.state, "pill", "taken")
            state_mod.append_log(self.state, "contraception", "她最后吃了避孕药")
        else:
            line = prompts.text(self.state, "pill", "skipped")
            state_mod.append_log(self.state, "contraception", "她最后没吃避孕药")
        if line:
            self.state["pill_offer_note"] = {"at": util.now_ts(), "line": line}
            if notify:
                self._schedule_notice(line, "受孕·避孕药", "pill_result")
        self._save()
        return {"ok": True, "took": bool(took), "line": line}

    def _pill_blame_enabled(self) -> bool:
        override = self.state.get("pill_blame_enabled")
        if isinstance(override, bool):
            return override
        return self.settings.bool("contraception.pill_blame_enabled")

    def _maybe_pill_blame(self) -> dict:
        """她拒绝吃药+答应不内射，结果还是内射：按概率加鱼之心责备。"""
        if not self._pill_blame_enabled():
            return {}
        refusal = self.state.get("pill_refusal")
        once = self.settings.bool("contraception.pill_blame_once")
        if not isinstance(refusal, dict) or not refusal:
            return {}
        if once and refusal.get("used"):
            return {}
        scene_at = util.safe_float((self.state.get("scene") or {}).get("started_at"), 0.0)
        if once and scene_at and util.safe_float(self.state.get("pill_blame_scene"), 0.0) == scene_at:
            return {}
        if str(refusal.get("context") or "") != "夜袭前":
            return {}
        now = util.now_ts()
        window = max(0, int(tuning.get(
            self.state, "contraception", "pill_blame_window_minutes",
            self.settings.int("contraception.pill_blame_window_minutes", 0, 1440)))) * 60
        if window and now - util.safe_float(refusal.get("at"), 0.0) > window:
            return {}
        if self.settings.bool("contraception.pill_blame_require_promise") and \
                not refusal.get("promise"):
            return {}
        if once:
            refusal["used"] = True
            if scene_at:
                self.state["pill_blame_scene"] = scene_at
        complain = prompts.text(self.state, "pill", "complain")
        if complain:
            # 只作为提示词交给她，由她自己在下一轮说，不由插件代发
            self.state["pill_complain_note"] = {"at": now, "line": complain}
        chance = float(tuning.get(
            self.state, "contraception", "pill_blame_chance",
            self.settings.float("contraception.pill_blame_chance", 0, 100)))
        if random.random() * 100 >= chance:
            self._save()
            return {"rolled": False, "line": complain}
        amount = float(tuning.get(
            self.state, "contraception", "pill_blame_amount",
            self.settings.float("contraception.pill_blame_amount", 0, 100)))
        result = {}
        if amount > 0:
            try:
                result = boost.boost_fish_blame(self.context, self.settings, amount)
            except Exception as error:
                logger.warning("[受孕] 写鱼之心责备失败：%s", error)
                result = {"ok": False, "reason": str(error)}
        line = prompts.text(self.state, "pill", "blame")
        if line:
            self.state["pill_blame_note"] = {"at": now, "line": line}
        state_mod.append_log(
            self.state, "contraception",
            f"拒绝吃药后被内射：鱼之心责备 +{amount:.1f}"
            + ("（已写入）" if (result or {}).get("ok") else ""))
        self._save()
        return {"rolled": True, "amount": amount, "fish": result,
                "line": line, "complain": complain}

    def _pill_offer_tick(self) -> dict:
        pending = self.state.get("pill_offer")
        if not isinstance(pending, dict) or not pending:
            return {}
        now = util.now_ts()
        until = util.safe_float(pending.get("until"), 0.0)
        if until and now > until:
            return self._finalize_pill_offer(True)
        return {}

    def _pill_offer_response(self, text: str) -> bool:
        pending = self.state.get("pill_offer")
        if not isinstance(pending, dict) or not pending:
            return False
        now = util.now_ts()
        until = util.safe_float(pending.get("until"), 0.0)
        if until and now > until:
            self._finalize_pill_offer(True)
            return True
        body_text = str(text or "")
        if self._match_any(body_text, self.settings.list("contraception.pill_cancel_keywords")):
            self._finalize_pill_offer(False, notify=False, refusal_text=body_text)
            line = prompts.text(self.state, "pill", "cancel")
            if line:
                self.state["pill_offer_note"] = {"at": now, "line": line}
            self._save()
            return True
        if self._match_any(body_text, self.settings.list("contraception.pill_take_keywords")):
            self._finalize_pill_offer(True, notify=False)
            line = prompts.text(self.state, "pill", "confirm")
            if line:
                self.state["pill_offer_note"] = {"at": now, "line": line}
            self._save()
            return True
        return False

    def _unbirth_overnight_invite_tick(self) -> None:
        """还没进来时，她可能主动邀请 Unbirth 进来过夜。"""
        if self._proactive_deferred("unbirth_overnight_invite"):
            return
        if not self.settings.bool("unbirth.enabled"):
            return
        if unbirth.data(self.state).get("inside"):
            return
        if sleep_inside.active(self.state):
            return
        now = util.now_ts()
        hour = datetime.now().hour
        if not (hour >= 21 or hour < 4):
            return
        sleep = sleepy.sleeping(self.settings)
        if sleep.get("sleeping", sleep.get("asleep")):
            return
        lewd_value = lewd.payload(self.state, self.settings).get("value") or 0.0
        if lewd_value < self.settings.float("unbirth.overnight_invite_min_lewd", 0.0, 100.0):
            return
        last = util.safe_float(self.state.get("unbirth_overnight_invite_at"), 0.0)
        if last and now - last < 1800:
            return
        chance = self.settings.float("unbirth.overnight_invite_chance", 0.0, 100.0)
        if chance <= 0 or random.random() * 100 >= chance:
            return
        line = prompts.text(self.state, "unbirth", "overnight_invite")
        if not line:
            return
        self.state["unbirth_overnight_invite_at"] = now
        self.state["unbirth_overnight_invite"] = {"at": now, "line": line}
        self._schedule_notice(
            line, "受孕·Unbirth", "unbirth_overnight_invite", judge=True,
            rollback=lambda: (self.state.pop("unbirth_overnight_invite", None),
                              self.state.__setitem__("unbirth_overnight_invite_at", 0.0)))
        state_mod.append_log(self.state, "unbirth", "她主动邀请 Unbirth 进来过夜")

    def _unbirth_overnight_request_tick(self) -> None:
        """她在子宫里睡下后，可能主动提出就这样过夜。"""
        if self._proactive_deferred("unbirth_overnight"):
            return
        if not self.settings.bool("unbirth.enabled"):
            return
        if not unbirth.data(self.state).get("inside"):
            return
        if sleep_inside.active(self.state):
            return
        sleep = sleepy.sleeping(self.settings)
        if not sleep.get("sleeping", sleep.get("asleep")):
            return
        now = util.now_ts()
        check = max(1, self.settings.int("unbirth.overnight_check_minutes", 1, 1440)) * 60
        last = util.safe_float(self.state.get("unbirth_overnight_check_at"), 0.0)
        if last and now - last < check:
            return
        self.state["unbirth_overnight_check_at"] = now
        chance = self.settings.float("unbirth.overnight_request_chance", 0.0, 100.0)
        if chance <= 0 or random.random() * 100 >= chance:
            return
        line = prompts.text(self.state, "unbirth", "overnight_request")
        if not line:
            return
        self.state["unbirth_overnight_request"] = {
            "at": now, "until": now + 600, "line": line}
        ask = sleep_inside.data(self.state)
        ask.update({"pending": "unbirth", "asked_at": now,
                    "mode": "", "until": 0.0})
        self._schedule_notice(
            line, "受孕·Unbirth", "unbirth_overnight", judge=True,
            rollback=lambda: (
                self.state.pop("unbirth_overnight_request", None),
                sleep_inside.data(self.state).pop("pending", None)))
        state_mod.append_log(self.state, "unbirth", "她提出就这样在里面过夜")

    def _sleep_inside_overnight_request_tick(self) -> None:
        """没在 Unbirth 里时，也可能主动提出让他在里面过夜。"""
        if self._proactive_deferred("sleep_inside_overnight"):
            return
        if not self.settings.bool("sleep_inside.enabled") or \
                not self.settings.bool("sleep_inside.overnight_request_enabled"):
            return
        if sleep_inside.active(self.state):
            return
        if unbirth.data(self.state).get("inside"):
            return  # 已在子宫里，交给 Unbirth 过夜请求
        row = sleep_inside.data(self.state)
        if row.get("pending"):
            return
        sleep = sleepy.sleeping(self.settings)
        if not sleep.get("sleeping", sleep.get("asleep")):
            return
        lewd_value = lewd.payload(self.state, self.settings).get("value") or 0.0
        need = self.settings.float("sleep_inside.overnight_min_lewd", 0.0, 100.0)
        if lewd_value < need:
            return
        now = util.now_ts()
        last = util.safe_float(self.state.get("sleep_inside_offer_at"), 0.0)
        if last and now - last < 1800:
            return
        chance = self.settings.float("sleep_inside.overnight_request_chance", 0.0, 100.0)
        if chance <= 0 or random.random() * 100 >= chance:
            return
        self.state["sleep_inside_offer_at"] = now
        line = prompts.text(self.state, "sleep_inside", "overnight_offer")
        if not line:
            return
        row.update({"pending": "vagina", "asked_at": now, "mode": "", "until": 0.0})
        self.state["sleep_inside_offer"] = {"at": now, "line": line}
        self._schedule_notice(
            line, "受孕·过夜", "sleep_inside_overnight", judge=True,
            rollback=lambda: (
                self.state.pop("sleep_inside_offer", None),
                self.state.__setitem__("sleep_inside_offer_at", 0.0),
                row.pop("pending", None)))
        state_mod.append_log(self.state, "sleep_inside", "她主动提出让他在里面过夜")

    def _unbirth_request_tick(self) -> dict:
        """她在场景里主动请求让主人进入 Unbirth。"""
        if self._proactive_deferred("unbirth_request"):
            return {}
        now = util.now_ts()
        pending = self.state.get("unbirth_request") if isinstance(
            self.state.get("unbirth_request"), dict) else {}
        if pending:
            until = util.safe_float(pending.get("until"), 0.0)
            if until and now > until:
                self.state["unbirth_request"] = {}
                state_mod.append_log(self.state, "unbirth", "请求进入没等到回应，作罢")
                self._save()
            return {}
        if not unbirth.enabled(self.settings, self.state):
            return {}
        if not unbirth.request_enabled(self.state, self.settings):
            return {}
        if unbirth.inside(self.state, self.settings):
            return {}
        if not state_mod.scene_active(self.state, self.settings):
            return {}
        check_minutes = max(1, int(tuning.get(
            self.state, "unbirth", "request_check_minutes",
            self.settings.int("unbirth.request_check_minutes", 1, 1440))))
        last = util.safe_float(self.state.get("unbirth_request_check_at"), 0.0)
        if last and now - last < check_minutes * 60:
            return {}
        self.state["unbirth_request_check_at"] = now
        cool = util.safe_float(self.state.get("unbirth_request_cool_at"), 0.0)
        cooldown = max(0, int(tuning.get(
            self.state, "unbirth", "request_cooldown_minutes",
            self.settings.int("unbirth.request_cooldown_minutes", 0, 1440)))) * 60
        if cool and now - cool < cooldown:
            return {}
        chance = float(tuning.get(
            self.state, "unbirth", "request_chance",
            self.settings.float("unbirth.request_chance", 0, 100)))
        if random.random() * 100 >= chance:
            return {}
        line = prompts.text(self.state, "unbirth",
                            "request_period" if self.state.get("menstrual_active")
                            else "request")
        if not line:
            return {}
        wait = max(1, int(tuning.get(
            self.state, "unbirth", "request_wait_minutes",
            self.settings.int("unbirth.request_wait_minutes", 1, 120))))
        self.state["unbirth_request"] = {"at": now, "until": now + wait * 60}
        self.state["unbirth_request_note"] = {"at": now, "line": line}
        self._schedule_notice(
            line, "受孕·Unbirth", "unbirth_request", judge=True,
            rollback=lambda: (
                self.state.pop("unbirth_request", None),
                self.state.pop("unbirth_request_note", None)))
        state_mod.append_log(self.state, "unbirth", "她主动请求让主人进入 Unbirth")
        self._save()
        return {"sent": True, "line": line}

    def _unbirth_request_response(self, text: str) -> bool:
        pending = self.state.get("unbirth_request")
        if not isinstance(pending, dict) or not pending:
            return False
        now = util.now_ts()
        if util.safe_float(pending.get("until"), 0.0) and \
                now > util.safe_float(pending.get("until"), 0.0):
            self.state["unbirth_request"] = {}
            self._save()
            return False
        if not str(text or "").strip():
            return False
        self.state["unbirth_request"] = {}
        self.state["unbirth_request_cool_at"] = now
        result = unbirth.enter(self.state, self.settings)
        if result.get("ok"):
            line = prompts.text(self.state, "unbirth", "request_enter")
            self.state["unbirth_request_note"] = {"at": now, "line": line}
            state_mod.append_log(self.state, "unbirth", "回应了她的请求，进入 Unbirth")
        else:
            line = prompts.text(self.state, "unbirth", "request_fail",
                                reason=result.get("reason") or "")
            self.state["unbirth_request_note"] = {"at": now, "line": line}
            state_mod.append_log(self.state, "unbirth",
                                 f"她请求进入但没成功：{result.get('reason') or ''}")
        self._save()
        return True

    def _toy_self_enabled(self) -> bool:
        override = self.state.get("toy_self_use_enabled")
        if isinstance(override, bool):
            return override
        return self.settings.bool("toys.self_use_enabled")

    def _maybe_self_toy(self) -> dict:
        """她主动拿玩具：日常里欲望/湿润/淫乱度够高时按概率触发。"""
        if not self.settings.bool("toys.enabled") or not self._toy_self_enabled():
            return {}
        now = util.now_ts()
        check_minutes = max(1, int(tuning.get(
            self.state, "toys", "self_use_check_minutes",
            self.settings.int("toys.self_use_check_minutes", 1, 1440))))
        last_check = util.safe_float(self.state.get("toy_self_check_at"), 0.0)
        if last_check and now - last_check < check_minutes * 60:
            return {}
        self.state["toy_self_check_at"] = now
        if state_mod.scene_active(self.state, self.settings) or \
                state_mod.daily_active(self.state, self.settings):
            return {}
        if isinstance(self.state.get("night_raid"), dict) and self.state["night_raid"]:
            return {}
        cool = util.safe_float(self.state.get("toy_self_cool_at"), 0.0)
        cooldown = max(0, int(tuning.get(
            self.state, "toys", "self_use_cooldown_minutes",
            self.settings.int("toys.self_use_cooldown_minutes", 0, 1440)))) * 60
        if cool and now - cool < cooldown:
            return {}
        desire, _, _ = self._desire_pick("night_raid")
        wet = wetness.value_of(self.state, self.settings)
        lewd_value = lewd.payload(self.state, self.settings).get("value") or 0.0
        mins = (
            float(tuning.get(self.state, "toys", "self_use_min_desire",
                             self.settings.float("toys.self_use_min_desire", 0, 100))),
            float(tuning.get(self.state, "toys", "self_use_min_wet",
                             self.settings.float("toys.self_use_min_wet", 0, 100))),
            float(tuning.get(self.state, "toys", "self_use_min_lewd",
                             self.settings.float("toys.self_use_min_lewd", 0, 100))),
        )
        if desire < mins[0] or wet < mins[1] or lewd_value < mins[2]:
            return {}
        chance = float(tuning.get(self.state, "toys", "self_use_chance",
                                  self.settings.float("toys.self_use_chance", 0, 100)))
        if random.random() * 100 >= chance:
            return {}
        choices = [row for row in toys.toys_payload(self.settings, self.state)
                   if row.get("enabled") and (row.get("outside") or
                                              toys.toy_outside(self.settings, row["key"]))]
        if not choices:
            return {}
        picked = random.choice(choices)
        key = str(picked["key"])
        result = self._record_toy(key, 2, "她主动", user="self")
        if result.get("refused"):
            return {}
        label = str(picked.get("label") or key)
        line = prompts.text(self.state, "toy_self", "start", toy=label)
        notes = [line] if line else []
        controller = float(tuning.get(
            self.state, "toys", "self_use_controller_chance",
            self.settings.float("toys.self_use_controller_chance", 0, 100)))
        if random.random() * 100 < controller:
            extra = prompts.text(self.state, "toy_self", "controller", toy=label)
            if extra:
                notes.append(extra)
                self.state["toy_self_controller_note"] = {"at": now, "line": extra}
        text_line = "\n".join(notes)
        if text_line:
            self.state["toy_self_note"] = {"at": now, "line": text_line}
            delay = max(0, int(tuning.get(
                self.state, "toys", "self_use_delay_seconds",
                self.settings.int("toys.self_use_delay_seconds", 0, 300))))
            self._schedule_notice(text_line, "受孕·玩具", "toy_self", delay=delay)
        self.state["toy_self_cool_at"] = now
        state_mod.append_log(self.state, "toys", f"她自己主动用了{label}")
        self._save()
        return {"ok": True, "toy": key, "label": label, "line": text_line}

    def _night_raid_tick(self) -> dict:
        """半夜：PC 熬夜 + 欲望/湿润够高时，她可能自己摸过来。"""
        now = util.now_ts()
        pending = self.state.get("night_raid") if isinstance(
            self.state.get("night_raid"), dict) else {}
        if pending:
            until = util.safe_float(pending.get("until"), 0.0)
            if until and now > until:
                self.state["night_raid"] = {}
                pc_state.clear_night_raid_bypass()
                state_mod.append_log(self.state, "night_raid", "夜袭没等到回应，放弃")
                self._save()
            return {}
        if not self.settings.bool("night_raid.enabled"):
            return {}
        if state_mod.scene_active(self.state, self.settings) or \
                state_mod.daily_active(self.state, self.settings):
            return {}
        if unbirth.inside(self.state, self.settings):
            return {}
        quiet_after_scene = max(0, int(tuning.get(
            self.state, "night_raid", "after_scene_minutes",
            self.settings.int("night_raid.after_scene_minutes", 0, 1440)))) * 60
        last_scene_at = state_mod.scene_last_at(self.state)
        if last_scene_at and now - last_scene_at < quiet_after_scene:
            return {}
        hour = datetime.now().hour
        start = tuning.get(self.state, "night_raid", "start_hour",
                           self.settings.int("night_raid.start_hour", 0, 23))
        end = tuning.get(self.state, "night_raid", "end_hour",
                         self.settings.int("night_raid.end_hour", 0, 23))
        start, end = int(start), int(end)
        in_night = (start <= hour < end) if start <= end else (hour >= start or hour < end)
        if not in_night:
            return {}
        cool = util.safe_float(self.state.get("night_raid_cool_at"), 0.0)
        cooldown = max(0, int(tuning.get(
            self.state, "night_raid", "cooldown_hours",
            self.settings.int("night_raid.cooldown_hours", 0, 168)))) * 3600
        if cool and now - cool < cooldown:
            return {}
        desire, _, _ = self._night_desire()
        wet = lube.natural_wetness(self.state, self.settings)
        desire_min = tuning.get(self.state, "night_raid", "desire_min",
                                self.settings.float("night_raid.desire_min", 0, 100))
        wet_min = tuning.get(self.state, "night_raid", "wet_min",
                             self.settings.float("night_raid.wet_min", 0, 100))
        if desire < desire_min or wet < wet_min:
            return {}
        very_high_at = float(tuning.get(
            self.state, "night_raid", "very_high_desire",
            self.settings.float("night_raid.very_high_desire", 0, 100)))
        very_high_wet = float(tuning.get(
            self.state, "night_raid", "very_high_wet_min",
            self.settings.float("night_raid.very_high_wet_min", 0, 100)))
        very_high = desire >= very_high_at and wet >= very_high_wet
        chance_key = "pregnancy_chance" if pregnancy.is_pregnant(self.state) else "chance"
        chance = tuning.get(self.state, "night_raid", chance_key,
                            self.settings.float(f"night_raid.{chance_key}", 0, 100))
        if very_high:
            chance = min(100.0, chance + float(tuning.get(
                self.state, "night_raid", "very_high_bonus",
                self.settings.float("night_raid.very_high_bonus", 0, 100))))
        chance, chance_note = night.adjust_chance(self.state, self.settings, chance)
        if chance_note:
            state_mod.append_log(self.state, "night_raid", chance_note)
        if chance <= 0 or random.random() * 100 >= chance:
            self.state["night_raid_cool_at"] = now + 1800
            return {}
        umo = str(getattr(self, "_last_umo", "") or "")
        if not umo:
            return {}
        wait = max(1, int(tuning.get(
            self.state, "night_raid", "wait_minutes",
            self.settings.int("night_raid.wait_minutes", 1, 120))))
        line = prompts.text(self.state, "night_raid",
                            "very_high" if very_high else "ask",
                            desire=round(desire, 0), wet=round(wet, 0))
        bar_value = lewd.payload(self.state, self.settings).get("value") or 0.0
        pre = prompts.text(self.state, "night_raid", "pre",
                           desire=round(desire, 0), wet=round(wet, 0),
                           lewd=round(float(bar_value), 0))
        if pre:
            self.state["night_raid_pre_note"] = {"at": now, "line": pre}
        self._maybe_pill_offer("夜袭前")
        self.state["night_raid"] = {"at": now, "until": now + wait * 60, "umo": umo}
        afterglow = max(0, int(tuning.get(
            self.state, "night_raid", "afterglow_minutes",
            self.settings.int("night_raid.afterglow_minutes", 0, 120))))
        pc_state.set_night_raid_bypass(self.settings,
                                       now + (wait + afterglow) * 60)
        self._schedule_notice(line, "受孕·夜袭", "night_raid")
        gain = int(tuning.get(self.state, "night_raid", "energy_gain",
                              self.settings.int("night_raid.energy_gain", 0, 100)))
        if gain:
            pc_state.adjust_energy(self.settings, gain)
        state_mod.append_log(self.state, "night_raid", "她半夜自己摸过来了，等回应")
        self._save()
        return {"sent": True, "line": line}

    def _night_raid_response(self, text: str) -> bool:
        """主人在夜袭后回了话：取消等待，直接进正常受孕场景。"""
        pending = self.state.get("night_raid")
        if not isinstance(pending, dict) or not pending:
            return False
        now = util.now_ts()
        if util.safe_float(pending.get("until"), 0.0) and                 now > util.safe_float(pending.get("until"), 0.0):
            self.state["night_raid"] = {}
            self._save()
            return False
        if not str(text or "").strip():
            return False
        self.state["night_raid"] = {}
        self.state["night_raid_cool_at"] = now
        afterglow = max(0, int(tuning.get(
            self.state, "night_raid", "afterglow_minutes",
            self.settings.int("night_raid.afterglow_minutes", 0, 120))))
        activity = max(afterglow, int(tuning.get(
            self.state, "night_raid", "activity_window_minutes",
            self.settings.int("night_raid.activity_window_minutes", 1, 720))))
        pc_state.set_night_raid_bypass(self.settings, now + activity * 60)
        self._touch_scene("夜袭回应")
        line = prompts.text(self.state, "night_raid", "start")
        if line:
            self.state["night_raid_start_note"] = {"at": now, "line": line}
        state_mod.append_log(self.state, "night_raid", "主人回应了夜袭，进入亲密场景")
        self._save()
        return True

    def _touch_scene(self, trigger: str) -> None:
        """明确的亲密动作（工具/命令）开场，或把场景续上。

        如果她正处在"日常小场景"（自己用玩具那段），真正的亲密动作会把它**升级**成
        正常场景：子敏感度攒的进度原样保留，后面就按活动场景算。
        """
        was_daily = state_mod.daily_active(self.state, self.settings)
        if was_daily:
            state_mod.clear_daily(self.state, escalated=True)
            state_mod.append_log(
                self.state, "scene",
                f"日常小场景升级成亲密场景：{trigger}")
            logger.info("[受孕] 日常小场景 → 亲密场景（%s）", trigger)
        was_scene = state_mod.scene_active(self.state, self.settings)
        if menstrual.changing(self.state):
            menstrual.data(self.state)["change_intruded"] = True
            self.state["menstrual_note"] = {
                "at": util.now_ts(),
                "line": prompts.text(self.state, "clothing", "pad_change_intruded")}
        if not was_scene:
            hit = children.maybe_interrupt(self.state, self.settings)
            if hit:
                self._schedule_notice(hit.get("line") or "", "受孕·孩子", "children_interrupt")
                self._save()
                return
        window = max(1, self.settings.int("adult.scene_window_minutes", 1, 720)) * 60
        state_mod.touch_scene(self.state, window_seconds=window)
        if not was_scene:
            night.mark_activity(self.state, "scene")
            lewd.add(self.state, self.settings, self.settings.float(
                "lewd.scene_add", 0.0, 100.0))
            self._maybe_pill_offer("活动前")
        step_key = "daily_step_gain" if was_daily else "scene_step_gain"
        step_gain = self.settings.float(f"wetness.{step_key}", 0.0, 100.0)
        if step_gain:
            wetness.gain(self.state, self.settings, extra=step_gain)
        logger.debug("[受孕] 场景已刷新（%s）", trigger)

    def _scene_active(self, data: dict | None = None) -> tuple[bool, str]:
        """现在是不是"正在进行的亲密场景"。

        三种算场景内：
          1. 本插件自己的场景窗口（工具/命令刷新的，默认 30 分钟）；
          2. 鱼之心正处于成人场景里（它自己的 scene 同意或 intimate 标记）；
          3. 手动 /受孕场景 开的窗口（也写在本插件场景里）。
        平常聊天里突然冒出一个关键词，不会命中这里。
        """
        if state_mod.scene_active(self.state, self.settings):
            return True, "本插件场景中"
        data = data or self._read_sources()
        fish = data.get("fish")
        if isinstance(fish, sources.FishSnapshot) and fish.usable:
            if fish.adult_scene or fish.scene_intimate:
                return True, "鱼之心场景中"
        return False, "不在亲密场景里"

    def _detect_toys(self, text: str, data: dict | None, trigger: str) -> None:
        """从对话里认出在用哪个玩具（60 秒内不重复记）。"""
        if not self.settings.bool("toys.enabled") or \
                not self.settings.bool("toys.keyword_detect"):
            return
        if self.settings.bool("adult.detect_requires_scene"):
            in_scene, _ = self._scene_active(data)
            if not in_scene:
                return
        key = toys.detect_toy(text, self.settings)
        if not key:
            return
        now = util.now_ts()
        if now - util.safe_float(self.state.get("_toy_text_at"), 0.0) < 60:
            return
        if self._record_toy(key, 2, trigger).get("refused"):
            return
        self.state["_toy_text_at"] = now

    def _detect_user_message(self, text: str, data: dict | None = None) -> None:
        if not self.settings.bool("adult.detect_user_message"):
            return
        if not text:
            return
        ok, _ = self._gate(data)
        if not ok:
            return
        if self.settings.bool("adult.detect_requires_scene"):
            in_scene, why = self._scene_active(data)
            if not in_scene:
                logger.debug("[受孕] 关键词命中但%s，忽略：%s", why, text[:40])
                return
        words = self.settings.list("adult.ejaculation_keywords")
        if self._match_any(text, words) and self._text_event_ok("ejaculation"):
            mode = self._mode_from_text(text)
            self._record_ejaculation(mode, "主人这句话")
            logger.info("[受孕] 从主人消息里识别到射精：%s", intimacy.MODE_LABELS.get(mode, mode))
        else:
            self._detect_touches(text, data, "主人这句话")
            self._detect_toys(text, data, "主人这句话")
            self._detect_clothing(text)
            self._detect_unbirth_resist(text, data)

    def _detect_unbirth_resist(self, text: str, data: dict | None = None) -> None:
        if not unbirth.enabled(self.settings, self.state):
            return
        if not unbirth.inside(self.state, self.settings):
            return
        words = unbirth.resist_keywords(self.state, self.settings)
        if not self._match_any(text, words):
            return
        info = unbirth.birth_out(self.state, self.settings, resist=True)
        if info.get("ok"):
            self._save()
            logger.info("[受孕] 从主人消息里识别到 Unbirth 逆着来")

    def _detect_clothing(self, text: str) -> None:
        if not clothing.enabled(self.settings):
            return
        now = util.now_ts()
        last = util.safe_float(self.state.get("_clothing_text_at"), 0.0)
        if last and now - last < 15:
            return
        action = clothing.detect_action(self.state, text)
        if not action:
            return
        if action == "remove_underwear":
            info = clothing.remove(self.state, self.settings, "underwear", now=now)
        else:
            info = clothing.wear(self.state, self.settings, "underwear", "panties", now=now)
        if not info.get("ok"):
            return
        self.state["_clothing_text_at"] = now
        state_mod.append_log(self.state, "clothing",
                             f"从关键词识别：{action}（{info.get('line') or ''}）")
        self._save()

    def _detect_reply(self, text: str, data: dict | None = None) -> None:
        if not self.settings.bool("adult.detect_reply") or not text:
            return
        ok, _ = self._gate(data)
        if not ok:
            return
        if self.settings.bool("adult.detect_requires_scene"):
            in_scene, why = self._scene_active(data)
            if not in_scene:
                logger.debug("[受孕] 回话关键词命中但%s，忽略", why)
                return

        orgasm_words = self.settings.list("adult.orgasm_keywords")
        if self._match_any(text, orgasm_words) and self._text_event_ok("orgasm"):
            self._record_orgasm("她的回话")
            logger.info("[受孕] 从她的回话里识别到高潮")

        ejaculation_words = self.settings.list("adult.ejaculation_keywords")
        if self._match_any(text, ejaculation_words) and self._text_event_ok("ejaculation"):
            mode = self._mode_from_text(text)
            self._record_ejaculation(mode, "她的回话")
            logger.info("[受孕] 从她的回话里识别到射精：%s", intimacy.MODE_LABELS.get(mode, mode))
        else:
            self._detect_touches(text, data, "她的回话")
            self._detect_toys(text, data, "她的回话")

    # ================================================================ 提示词注入

    def _attach_temp(self, req, text: str) -> bool:
        """挂到本轮用户消息末尾（mark_as_temp，不回存历史），保住前缀缓存。"""
        body = (text or "").strip()
        if not body:
            return False
        parts = getattr(req, "extra_user_content_parts", None)
        if TextPart is not None and isinstance(parts, list):
            try:
                part = TextPart(text=body)
                marked = part.mark_as_temp()
                parts.append(marked if isinstance(marked, TextPart) else part)
                return True
            except Exception as error:
                logger.debug("[受孕] 挂到用户消息失败，退回 system_prompt：%s", error)
        try:
            req.system_prompt = (getattr(req, "system_prompt", "") or "").rstrip() + "\n\n" + body
            return True
        except Exception:
            return False

    @filter.on_llm_request(priority=INJECT_PRIORITY)
    async def on_llm_request(self, event, req):
        if not self._active(event):
            return
        try:
            if not self._owner_private(event):
                return
            text = str(getattr(event, "message_str", "") or "")
            data = self._read_sources()
            self._pill_offer_response(text)
            self._children_request(text)
            self._cycle_request(text)
            self._sleep_inside_detect(text)
            self._asmr_learn(text)
            self._asmr_wake(text)
            self._asmr_response(text)
            self._night_raid_response(text)
            self._unbirth_request_response(text)
            # 先认场景，再认关键词：平常聊天里的词不参与判定
            self._detect_user_message(text, data)
            comfort = birth.comfort(self.state, self.settings, text)
            if comfort:
                state_mod.append_log(self.state, "birth",
                                     f"安抚（{comfort['hit']}）：产痛 -{comfort['relief']:.0f}"
                                     f" → {comfort['pain']:.0f}")
            self._tick()
            in_scene_now, _ = self._scene_active(data)
            if self.settings.bool("mood.enabled") and not in_scene_now:
                # 日常里的两句：正常聊天慢慢降羞耻；他说了安慰/摸摸头/亲吻就降得多一点
                mood.daily_relief(self.state, self.settings)
                self._detect_comfort(text)

            gate_ok, gate_why = self._gate(data)
            cycle = self._cycle()
            prog = pregnancy.progress(self.state)

            if self.settings.bool("inject.enabled") and self.settings.bool("inject.stable_system"):
                stable = pregnancy.stable_block(self.settings, self.state)
                if stable:
                    current = getattr(req, "system_prompt", "") or ""
                    marker = "【身体状态·"
                    if marker not in current:
                        req.system_prompt = current.rstrip() + "\n\n" + stable
                guide = pregnancy.tool_guide(self.settings)
                current = getattr(req, "system_prompt", "") or ""
                if guide and "【可主动调用的身体与生活动作】" not in current:
                    req.system_prompt = current.rstrip() + "\n\n" + guide

            if self.settings.bool("inject.enabled") and self.settings.bool("inject.dynamic_tail"):
                if gate_ok or prog:
                    p = None
                    if not prog and gate_ok:
                        p = self._probability(data, cycle, inside=True)
                    line = pregnancy.dynamic_line(
                        self.settings, self.state, cycle,
                        pleasure=util.safe_float(self.state.get("pleasure"), 0.0),
                        orgasms=state_mod.session_orgasms(self.state, self.settings),
                        probability=p,
                        self_test=pregnancy.self_test_window(self.state),
                        in_scene=self._scene_active(data)[0],
                        daily=self._daily_payload())
                    if line:
                        self._attach_temp(req, line)
            window = pregnancy.self_test_window(self.state)
            if window and window.get("ready") and not window.get("hinted_at"):
                # 让"想验一下"这件事只提醒一次，不刷屏
                self.state["self_test"]["hinted_at"] = util.now_ts()
            self._save()
        except Exception as error:
            logger.warning("[受孕] on_llm_request 异常：%s", error)

    @filter.on_llm_response()
    async def on_llm_response(self, event, response):
        if not self._active(event):
            return
        try:
            if not self._owner_private(event):
                return
            text = str(getattr(response, "completion_text", "") or
                       getattr(response, "_completion_text", "") or "")
            if not text:
                return
            self._detect_told(text)
            self._detect_reply(text, self._read_sources())
            self._save()
        except Exception as error:
            logger.warning("[受孕] on_llm_response 异常：%s", error)

    # 她说出这些词，就当作已经把怀孕这件事告诉他了
    TOLD_WORDS = ("怀孕", "怀上了", "怀了", "两条杠", "验孕", "有喜", "肚子里有")

    def _detect_told(self, text: str) -> None:
        """她已经知道、但还没说，而这次回话里说破了 → 记为"已经告诉他"。"""
        if not self.settings.bool("self_test.tell_detect"):
            return
        if not pregnancy.knows(self.state) or pregnancy.told(self.state):
            return
        if not self._match_any(text, list(self.TOLD_WORDS)):
            return
        if pregnancy.note_told(self.state):
            state_mod.append_log(self.state, "told", "她自己把怀孕的事说出来了")
            logger.info("[受孕] 她已把怀孕的事告诉主人")

    # ================================================================ Web 面板

    def _purge_web_apis(self) -> int:
        """先清掉本插件以前注册过的路由（含旧实例留下的通配路由）。

        AstrBot 卸载插件时不会从 Context.registered_web_apis 里删路由，
        重载后旧实例的 handler 还留在列表里；而 `/<plugin>/state` 这种通配
        会抢在别的插件前面匹配到它们的路径（鱼的心就这样被抢过），
        所以每次加载先把属于本插件的一律摘掉，再按插件名注册固定路由。
        """
        apis = getattr(self.context, "registered_web_apis", None)
        if not isinstance(apis, list):
            return 0
        module = type(self).__module__
        keep, removed = [], 0
        for entry in apis:
            try:
                handler = entry[1]
            except (TypeError, IndexError):
                keep.append(entry)
                continue
            owner = getattr(getattr(handler, "__self__", None), "__class__", None)
            owner_module = str(getattr(owner, "__module__", "") or "")
            if owner_module == module or owner_module.startswith(
                    "data.plugins.astrbot_plugin_conception"):
                removed += 1
                continue
            keep.append(entry)
        if removed:
            apis[:] = keep
        return removed

    def _register_web_apis(self) -> None:
        """给自带的「受孕」页面注册数据接口。

        路径故意用**三段**（/astrbot_plugin_conception/web/state）：
        鱼之心用的是 `/<plugin>/state` 这种两段通配路由，
        面板又是拿完整路径逐条正则匹配、先匹配到谁就用谁；
        两段路径会被它抢走（重载顺序一变就翻车），三段它匹配不到。
        """
        removed = self._purge_web_apis()
        if removed:
            logger.info("[受孕] 已清理 %d 条旧 Web 路由（避免抢别的插件）", removed)
        routes = [
            ("/astrbot_plugin_conception/web/state", self._web_state, ["GET"],
             "受孕：状态快照"),
            ("/astrbot_plugin_conception/web/action", self._web_action, ["POST"],
             "受孕：面板操作"),
            ("/astrbot_plugin_conception/web/_routes", self._web_routes, ["GET"],
             "受孕：查看已注册的 Web 路由（排障用）"),
            ("/conception/web/state", self._web_state, ["GET"], "受孕：状态快照（别名）"),
            ("/conception/web/action", self._web_action, ["POST"], "受孕：面板操作（别名）"),
        ]
        for route, handler, methods, desc in routes:
            try:
                self.context.register_web_api(route, handler, methods, desc)
            except Exception as error:  # 老版本没有 register_web_api 也不能让插件起不来
                logger.warning("[受孕] 注册 Web API 失败（页面将不可用）：%s", error)
                return
        self.state["web_api_ready"] = True
        self.state["web_api_at"] = util.now_ts()
        self._save()
        logger.info("[受孕] Web 面板接口已注册：state / action（%d 条）", len(routes))

    def _toy_payload(self) -> dict | None:
        toy = toys.active_toy(self.state, self.settings)
        if not toy:
            return None
        span = max(1, self.settings.int("toys.active_minutes", 1, 240)) * 60
        elapsed = util.now_ts() - util.safe_float(toy.get("at"), 0.0)
        remaining = max(0, int((span - elapsed) / 60))
        return {
            "key": toy.get("key"),
            "label": toys.TOY_CATALOG.get(toy.get("key"), {}).get("label", ""),
            "intensity": util.safe_int(toy.get("intensity"), 2),
            "intensity_label": toys.INTENSITY_LABELS.get(
                util.safe_int(toy.get("intensity"), 2), ""),
            "place": toy.get("place") or "",
            "place_label": toys.PLACE_LABELS.get(toy.get("place") or "", ""),
            "remaining": remaining,
        }

    def _daily_payload(self) -> dict:
        """日常小场景的摘要（自己用玩具那一小段），给面板和提示词用。"""
        info = state_mod.daily_payload(self.state, self.settings)
        zone = info.get("zone") or ""
        info["zone_label"] = intimacy.ZONE_LABELS.get(zone, "")
        info["toy_label"] = toys.TOY_CATALOG.get(info.get("toy") or "", {}).get("label", "")
        info["zones"] = [zone] if (info["active"] and zone) else []
        return info

    def _status_flags(self) -> dict:
        """给面板顶部状态栏用：一个主状态 + 若干副标签。"""
        now = util.now_ts()
        pleasure = util.safe_float(self.state.get("pleasure"), 0.0)
        threshold = state_mod.effective_threshold(self.state, self.settings)
        tier = pregnancy.arousal_tier(pleasure)
        post = pregnancy.post_orgasm_active(self.state, self.settings)
        last_orgasm = util.safe_float(self.state.get("last_orgasm_at"), 0.0)
        orgasm_now = bool(last_orgasm) and (now - last_orgasm) <= 90
        edge_stack = state_mod.edge_stack(self.state, self.settings)
        craving = state_mod.edge_craving(self.state, self.settings)
        bonus = state_mod.edge_threshold_bonus(self.state, self.settings)
        ovul = state_mod.ovulation_active(self.state, now)
        ovul_left = max(0.0, (state_mod.ovulation_until(self.state) - now) / 3600.0)

        if orgasm_now:
            main = {"key": "orgasm", "label": "高潮中", "tone": "peak",
                    "note": "刚过去，身体还在抖、腿发软，先让她缓一缓。"}
        elif post:
            main = {"key": "afterglow", "label": "余韵", "tone": "afterglow",
                    "note": "还在回味，声音发软、动作慢，暂时不太想再被碰。"}
        elif pleasure >= threshold:
            main = {"key": "near", "label": "即将高潮", "tone": "near",
                    "note": f"已经到门槛 {threshold:.0f}，再推一点就会到。"}
        elif edge_stack:
            main = {"key": "edge", "label": "被寸止", "tone": "edge",
                    "note": f"已经被吊了 {edge_stack} 次，正渴着；门槛被抬到 {threshold:.0f}，"
                            f"渴求 {craving:.0f}%。"}
        elif pleasure >= 60:
            main = {"key": "hot", "label": "发情", "tone": "hot",
                    "note": tier.get("hint", "")}
        else:
            main = {"key": "calm", "label": "平静", "tone": "calm",
                    "note": tier.get("hint", "")}

        chips = []
        if ovul:
            chips.append({"key": "ovulation", "label": "排卵中", "tone": "ovulation",
                          "note": f"身体被诱发排卵，接下来约 {ovul_left:.0f} 小时按排卵期算。"})
        toy = self._toy_payload()
        if toy:
            where = f"·{toy['place_label']}" if toy.get("place_label") else ""
            chips.append({"key": "toy", "label": f"玩具·{toy['label']}{where}",
                          "tone": "toy",
                          "note": f"{toy['intensity_label']}，还剩约 {toy['remaining']} 分钟"})
        daily = self._daily_payload()
        if daily.get("active"):
            chips.append({"key": "daily",
                          "label": f"日常·{daily.get('toy_label') or '玩具'} {daily.get('remaining')}′",
                          "tone": "daily",
                          "note": "日常小场景：只是自己/他帮忙用玩具那一小段；"
                                  "真正的亲密动作会把它升级成正式场景"})
        if edge_stack:
            chips.append({"key": "edge", "label": f"寸止 {edge_stack} 次", "tone": "edge",
                          "note": f"门槛 +{bonus:.0f}"})
        if self.settings.bool("sub_zones.enabled"):
            in_scene, _ = self._scene_active()
            hot = [row for row in subzone.rows_payload(
                self.settings, self.state, in_scene=in_scene, now=now) if row["charge"] > 0]
            if hot:
                top = max(hot, key=lambda item: (item["level"], item["charge"]))
                chips.append({"key": "subzone",
                              "label": f"子敏感度·{top['label']} {top['level_name']}",
                              "tone": "subzone",
                              "note": f"{top['level_title']}，{top['percent']:.0f}%；"
                                      f"满了会给主敏感点加开发度/敏感度"})
        contra = body.contraception_payload(self.state, self.settings)
        if contra["pill_active"]:
            chips.append({"key": "pill", "label": "避孕药", "tone": "contra",
                          "note": f"还剩 {contra['pill_hours_left']:.1f} 小时"})
        if contra["condom"]:
            chips.append({"key": "condom", "label": "避孕套", "tone": "contra",
                          "note": "戴着；除非破了，否则不会进子宫"})
        if succubus.enabled(self.state, self.settings):
            chips.append({"key": "succubus", "label": "魅魔", "tone": "succubus",
                          "note": "欲望更强、吸收更快"})
        if post and main["key"] != "afterglow":
            chips.append({"key": "afterglow", "label": "余韵", "tone": "afterglow"})
        if pleasure >= 60 and main["key"] != "hot":
            chips.append({"key": "hot", "label": "发情", "tone": "hot"})
        mood_info = mood.payload(self.state, self.settings)
        if mood_info["desire"]["value"] >= 1:
            chips.append({"key": "desire",
                          "label": f"欲望 {mood_info['desire']['value']:.0f}",
                          "tone": "desire",
                          "note": f"{mood_info['desire']['title']}："
                                  f"满了她会自己贴上来、转成正式场景"})
        if mood_info["shame"]["value"] >= 1:
            chips.append({"key": "shame",
                          "label": f"羞耻 {mood_info['shame']['value']:.0f}",
                          "tone": "shame",
                          "note": f"{mood_info['shame']['title']}："
                                  f"满了会进羞耻期（玩具暂时不可用）"})
        if mood_info["shame_period"]["active"]:
            chips.append({"key": "shame_period",
                          "label": f"羞耻期 {mood_info['shame_period']['remaining']}′",
                          "tone": "warn",
                          "note": "这段时间她自己不肯用玩具，先哄哄她"})
        return {"main": main, "chips": chips, "pleasure": round(pleasure, 1),
                "threshold": round(threshold, 1), "edge_bonus": round(bonus, 1),
                "craving": round(craving, 0)}

    def _web_payload(self) -> dict:
        try:
            pregnancy.tick_tube_flow(self.state, self.settings)
        except Exception:
            pass
        """页面要的一整份快照。所有数值都换算成前端好画的东西。"""
        data = self._read_sources(force=True)
        cycle = self._cycle()
        gender = self._refresh_gender()
        gate_ok, gate_why = self._gate(data)
        prog = pregnancy.progress(self.state)
        pleasure = util.safe_float(self.state.get("pleasure"), 0.0)
        cap = self.settings.float("pleasure.max", 1.0, 1000.0)
        session_orgasms = state_mod.session_orgasms(self.state, self.settings)
        day = self.state.get("day") or {}
        combo_count = state_mod.combo_count(self.state, self.settings)
        combo_limit = self._combo_limit()
        rest = state_mod.rest_remaining(self.state)
        threshold = state_mod.effective_threshold(self.state, self.settings)
        tier = pregnancy.arousal_tier(pleasure)

        postpartum = pregnancy.postpartum_active(self.state)
        postpartum_stage = (pregnancy.postpartum_stage(self.state, self.settings)
                            if postpartum else None)
        postpartum_hard = bool(
            postpartum_stage and postpartum_stage.get("key") == "hard"
            and self.settings.bool("pregnancy.postpartum_no_conception"))
        prob = None
        if not prog and not postpartum_hard:
            p = self._probability(data, cycle, inside=True)
            outside = self._probability(data, cycle, inside=False, orgasm_recent=False)
            factors = [
                {"key": "phase", "label": "生理期基准", "kind": "percent",
                 "value": p.factors.get("phase", 0)},
                {"key": "fish", "label": "鱼之心欲", "kind": "mult",
                 "value": p.factors.get("fish", 1)},
                {"key": "dark", "label": "暗涌 lust", "kind": "mult",
                 "value": p.factors.get("dark", 1)},
                {"key": "pleasure", "label": "快感", "kind": "mult",
                 "value": p.factors.get("pleasure", 1)},
                {"key": "orgasm", "label": "高潮次数", "kind": "mult",
                 "value": p.factors.get("orgasm", 1)},
                {"key": "inside", "label": "体内/体外", "kind": "mult",
                 "value": p.factors.get("inside", 1)},
                {"key": "orgasm_now", "label": "高潮时被射", "kind": "mult",
                 "value": p.factors.get("orgasm_now", 1)},
            ]
            for key, label in (("ejaculation_count", "本次射精次数"),
                               ("ejaculation_volume", "本次精液量"),
                               ("simultaneous", "高潮同时被射"),
                               ("sleep_semen", "插着入睡·精液")):
                if p.factors.get(key) is not None:
                    factors.append({"key": key, "label": label, "kind": "mult",
                                    "value": p.factors[key]})
            if p.factors.get("postpartum") is not None:
                factors.append({"key": "postpartum", "label": "产后恢复期",
                                "kind": "mult", "value": p.factors["postpartum"]})
            prob = {
                "value": round(p.probability, 1),
                "tier": p.tier,
                "outside": round(outside.probability, 2),
                "max": round(self.settings.float(
                    "conception.max_probability", 0.0, 100.0), 1),
                "factors": factors,
            }

        fish = data.get("fish")
        dark = data.get("dark")
        return {
            "plugin": {"version": PLUGIN_VERSION,
                       "enabled": self.settings.bool("enabled")},
            "gender": {"gender": gender.get("gender"), "suitable": gender.get("suitable"),
                       "source": gender.get("source"), "evidence": gender.get("evidence")},
            "gate": {"ok": gate_ok, "reason": gate_why,
                     "consent_until": util.safe_float(self.state.get("adult_consent_until"), 0.0),
                     "adult_required": self.settings.bool("adult_required")},
            "scene": {"active": state_mod.scene_active(self.state, self.settings),
                      "remaining": state_mod.scene_remaining(self.state, self.settings)},
            "sources": {
                "owner": data.get("owner"),
                "fish": {
                    "available": bool(getattr(fish, "available", False)),
                    "activated": bool(getattr(fish, "activated", False)),
                    "enabled": bool(getattr(fish, "enabled", False)),
                    "usable": bool(getattr(fish, "usable", False)),
                    "desire": round(util.safe_float(getattr(fish, "desire", 0.0), 0.0), 1),
                    "awakened": bool(getattr(fish, "desire_awakened", False)),
                    "adult_enabled": bool(getattr(fish, "adult_enabled", False)),
                    "adult_allowed": bool(getattr(fish, "adult_allowed", False)),
                    "adult_open": bool(getattr(fish, "adult_open", False)),
                },
                "dark": {
                    "available": bool(getattr(dark, "available", False)),
                    "enabled": bool(getattr(dark, "enabled", False)),
                    "usable": bool(getattr(dark, "usable", False)),
                    "lust": round(util.safe_float(getattr(dark, "lust", 0.0), 0.0), 1),
                    "fresh": bool(getattr(dark, "fresh", False)),
                    "reason": str(getattr(dark, "reason", "") or ""),
                },
            },
            "cycle": {
                "prompts_enabled": self.settings.bool("cycle.prompts_enabled"),
                "menstrual": menstrual.payload(
                    self.state, self.settings, phase=cycle.get("phase")),
                "phase": cycle.get("phase"),
                "label": cycle.get("label") or cyclemodel.phase_label(cycle.get("phase")),
                "day": cycle.get("day"),
                "total": cycle.get("total"),
                "source": cycle.get("source"),
                "next_phase": cycle.get("next_phase"),
                "next_label": cyclemodel.phase_label(cycle.get("next_phase") or ""),
                "phase_index": cycle.get("phase_index"),
                "phases": [{"phase": item.get("phase"),
                            "label": cyclemodel.phase_label(item.get("phase")),
                            "days": item.get("days")}
                           for item in (cycle.get("phases") or [])],
            },
            "pleasure": {
                "value": round(pleasure, 1),
                "max": cap,
                "tier": tier.get("key"),
                "tier_hint": tier.get("hint"),
                "threshold": round(threshold, 1),
                "post_orgasm": pregnancy.post_orgasm_active(self.state, self.settings),
            },
            "combo": {"count": combo_count, "peak": state_mod.combo_peak(self.state),
                      "limit": combo_limit, "rest": rest,
                      "overstimulated": rest > 0},
            "orgasms": {"session": session_orgasms,
                        "today": util.safe_int(day.get("orgasms"), 0),
                        "total": util.safe_int(self.state.get("orgasms_total"), 0)},
            "ejaculations": {"today": util.safe_int(day.get("ejaculations"), 0),
                             "total": util.safe_int(self.state.get("ejaculations_total"), 0),
                             "inside": util.safe_int(
                                 self.state.get("ejaculations_inside_total"), 0),
                             "modes": {key: util.safe_int(
                                 (self.state.get("ejaculations_modes") or {}).get(key), 0)
                                 for key in intimacy.MODE_ORDER}},
            "zones": intimacy.zones_payload(self.settings, self.state),
            "sub_zones": subzone.payload(
                self.settings, self.state,
                in_scene=(self._scene_active(data)[0] or self._daily_payload()["active"])),
            "sub_prompts": subzone.prompts_payload(self.state),
            "mood": {**mood.payload(self.state, self.settings),
                     "shame_decay_per_hour": tuning.get(
                         self.state, "mood", "shame_decay_per_hour",
                         self.settings.float("mood.shame_decay_per_hour", 0, 100)),
                     "desire_decay_per_hour": tuning.get(
                         self.state, "mood", "desire_decay_per_hour",
                         self.settings.float("mood.desire_decay_per_hour", 0, 100)),
                     "manual": {key: tuning.raw(self.state, "mood", key, None) is not None
                                for key in ("shame_decay_per_hour", "desire_decay_per_hour")},
                     "fish_blame": round(util.safe_float(
                         getattr(fish, "blame", 0.0), 0.0), 1),
                     "fish_available": bool(getattr(fish, "available", False))},
            "mood_prompts": mood.prompts_payload(self.state),
            "lewd": lewd.payload(self.state, self.settings),
            "desire_strategy": desire.payload(self.state, self.settings),
            "pill_proactive": {"enabled": self._pill_proactive_enabled()},
            "pill_blame": {"enabled": self._pill_blame_enabled(),
                           "once": self.settings.bool("contraception.pill_blame_once")},
            "asmr": {**asmr.payload(self.state, self.settings),
                     "known_keywords": self._asmr_known_words()},
            "clothing_keywords": clothing.keyword_payload(self.state),
            "contraception_keywords": {
                key: self.settings.list(f"contraception.{key}")
                for key in ("pill_cancel_keywords", "pill_take_keywords",
                            "pill_inside_promise_keywords")},
            "toy_self": {
                "enabled": self._toy_self_enabled(),
                "last_check": util.safe_float(self.state.get("toy_self_check_at"), 0.0),
                "cool_at": util.safe_float(self.state.get("toy_self_cool_at"), 0.0),
            },
            "night_raid": {
                "pending": bool(self.state.get("night_raid")),
                "pc_late": pc_state.is_staying_up(
                    self.settings, self.settings.list("night_raid.pc_keywords")),
                "pc_stay_up_enabled": self.settings.bool(
                    "night_raid.pc_stay_up_enabled"),
                "fish_stay_up_enabled": self.settings.bool(
                    "night_raid.fish_stay_up_enabled"),
                "fish_late": bool(sources.fish_stay_up(self.settings).get("stay_up")),
                "forecast": self._night_forecast_payload(),
            },
            "daily": self._daily_payload(),
            "uterus": fill.volume(self.state, self.settings),
            "fill_prompts": fill.prompts_payload(self.state),
            "endurance": endurance.payload(self.state, self.settings),
            "special": special.payload(self.state, self.settings),
            "prompt_groups": prompts.payload(self.state),
            "behavior": behavior.payload(self.state, self.settings),
            "size": size.payload(self.state, self.settings),
            "uterus_insert": uterus_insert.payload(self.state, self.settings),
            "lube": lube.payload(self.state, self.settings),
            "squirt": squirt.payload(self.state, self.settings),
            "condom": condom.payload(self.state, self.settings),
            "birth": birth.payload(self.state, self.settings),
            "clothing": clothing.payload(self.state, self.settings),
            "unbirth": unbirth.payload(self.state, self.settings),
            "sleep_inside": sleep_inside.payload(self.state, self.settings),
            "children": {"list": children.roster(self.state, self.settings),
                         "summary": children.summary(self.state, self.settings),
                         "care_mode": self.settings.str("children.care_mode"),
                         "interrupt_enabled": self.settings.bool(
                             "children.intimacy_interrupt_enabled"),
                         "interrupt_chance": self.settings.float(
                             "children.intimacy_interrupt_chance", 0, 100),
                         "interrupt_age": self.settings.int(
                             "children.intimacy_child_max_age_years", 1, 18)},
        "zone_keywords": intimacy.zone_keywords_payload(self.settings, self.state),
            "swallow": swallow.payload(self.state, self.settings),
            "wetness": self._wetness_payload(),
            "sleep": {**sleepy.awake_payload(self.state, self.settings),
                      "note": sleepy.sleeping(self.settings)},
            "surprise": surprise.payload(self.state, self.settings),
            "memory": {**memory_link.available(self.context),
                       "write": memory_link.write_enabled(self.settings),
                       "bridge": bool(memory_link.bridge_tag(
                           getattr(self.store, "path", ""))),
                       "written": bool(util.safe_float(
                           self.state.get("memory_written_at"), 0.0))},
            "toys": toys.toys_payload(self.settings, self.state),
            "toy": self._toy_payload(),
            "hymen": {**body.hymen_payload(self.state, self.settings),
                      "blood_enabled": body.hymen_blood_enabled(
                          self.state, self.settings)},
            "contraception": body.contraception_payload(self.state, self.settings),
            "succubus": succubus.payload(self.state, self.settings),
            "tuning": {
                "adult": {
                    "scene_window_minutes": tuning.get(
                        self.state, "adult", "scene_window_minutes",
                        self.settings.int("adult.scene_window_minutes", 1, 720)),
                },
                "contraception": {
                    "pill_effectiveness": tuning.get(
                        self.state, "contraception", "pill_effectiveness",
                        self.settings.float("contraception.pill_effectiveness", 0, 100)),
                    "condom_effectiveness": tuning.get(
                        self.state, "contraception", "condom_effectiveness",
                        self.settings.float("contraception.condom_effectiveness", 0, 100)),
                    "condom_break_chance": tuning.get(
                        self.state, "contraception", "condom_break_chance",
                        self.settings.float("contraception.condom_break_chance", 0, 100)),
                    "pill_proactive_chance": tuning.get(
                        self.state, "contraception", "pill_proactive_chance",
                        self.settings.float("contraception.pill_proactive_chance", 0, 100)),
                    "pill_proactive_window_minutes": tuning.get(
                        self.state, "contraception", "pill_proactive_window_minutes",
                        self.settings.int("contraception.pill_proactive_window_minutes", 1, 120)),
                    "pill_proactive_cooldown_minutes": tuning.get(
                        self.state, "contraception", "pill_proactive_cooldown_minutes",
                        self.settings.int("contraception.pill_proactive_cooldown_minutes", 0, 1440)),
                    "pill_proactive_delay_seconds": tuning.get(
                        self.state, "contraception", "pill_proactive_delay_seconds",
                        self.settings.int("contraception.pill_proactive_delay_seconds", 0, 300)),
                    "pill_blame_chance": tuning.get(
                        self.state, "contraception", "pill_blame_chance",
                        self.settings.float("contraception.pill_blame_chance", 0, 100)),
                    "pill_blame_amount": tuning.get(
                        self.state, "contraception", "pill_blame_amount",
                        self.settings.float("contraception.pill_blame_amount", 0, 100)),
                    "pill_blame_window_minutes": tuning.get(
                        self.state, "contraception", "pill_blame_window_minutes",
                        self.settings.int("contraception.pill_blame_window_minutes", 0, 1440)),
                },
                "zones": {
                    "sens_decay_after_minutes": tuning.get(
                        self.state, "zones", "sens_decay_after_minutes",
                        self.settings.int("zones.sens_decay_after_minutes", 0, 10080)),
                    "sens_decay_per_hour": tuning.get(
                        self.state, "zones", "sens_decay_per_hour",
                        self.settings.float("zones.sens_decay_per_hour", 0, 10)),
                },
                "asmr": {
                    "default_minutes": tuning.get(self.state, "asmr", "default_minutes",
                        self.settings.int("asmr.default_minutes", 1, 240)),
                    "extend_minutes": tuning.get(self.state, "asmr", "extend_minutes",
                        self.settings.int("asmr.extend_minutes", 1, 120)),
                    "max_minutes": tuning.get(self.state, "asmr", "max_minutes",
                        self.settings.int("asmr.max_minutes", 1, 240)),
                    "sleep_relief": tuning.get(self.state, "asmr", "sleep_relief",
                        self.settings.float("asmr.sleep_relief", 0, 100)),
                    "sleep_relief_cap": tuning.get(self.state, "asmr", "sleep_relief_cap",
                        self.settings.float("asmr.sleep_relief_cap", 0, 200)),
                    "sleep_relief_daily_cap": tuning.get(
                        self.state, "asmr", "sleep_relief_daily_cap",
                        self.settings.float("asmr.sleep_relief_daily_cap", 0, 200)),
                    "intimacy_gain": tuning.get(self.state, "asmr", "intimacy_gain",
                        self.settings.float("asmr.intimacy_gain", 0, 100)),
                    "intimacy_cap": tuning.get(self.state, "asmr", "intimacy_cap",
                        self.settings.float("asmr.intimacy_cap", 0, 100)),
                    "attachment_gain": tuning.get(self.state, "asmr", "attachment_gain",
                        self.settings.float("asmr.attachment_gain", 0, 100)),
                    "attachment_cap": tuning.get(self.state, "asmr", "attachment_cap",
                        self.settings.float("asmr.attachment_cap", 0, 100)),
                    "ear_sens_gain": tuning.get(self.state, "asmr", "ear_sens_gain",
                        self.settings.float("asmr.ear_sens_gain", 0, 1)),
                    "ear_sens_cap": tuning.get(self.state, "asmr", "ear_sens_cap",
                        self.settings.float("asmr.ear_sens_cap", 0, 2)),
                    "pleasure_gain": tuning.get(self.state, "asmr", "pleasure_gain",
                        self.settings.float("asmr.pleasure_gain", 0, 100)),
                    "pleasure_cap": tuning.get(self.state, "asmr", "pleasure_cap",
                        self.settings.float("asmr.pleasure_cap", 0, 100)),
                    "endurance_gain": tuning.get(self.state, "asmr", "endurance_gain",
                        self.settings.float("asmr.endurance_gain", 0, 100)),
                    "endurance_cap": tuning.get(self.state, "asmr", "endurance_cap",
                        self.settings.float("asmr.endurance_cap", 0, 100)),
                    "shame_gain": tuning.get(self.state, "asmr", "shame_gain",
                        self.settings.float("asmr.shame_gain", 0, 100)),
                    "shame_cap": tuning.get(self.state, "asmr", "shame_cap",
                        self.settings.float("asmr.shame_cap", 0, 100)),
                    "shame_decay_per_session": tuning.get(self.state, "asmr", "shame_decay_per_session",
                        self.settings.float("asmr.shame_decay_per_session", 0, 10)),
                    "shame_floor": tuning.get(self.state, "asmr", "shame_floor",
                        self.settings.float("asmr.shame_floor", 0, 100)),
                    "wet_gain": tuning.get(self.state, "asmr", "wet_gain",
                        self.settings.float("asmr.wet_gain", 0, 100)),
                    "wet_cap": tuning.get(self.state, "asmr", "wet_cap",
                        self.settings.float("asmr.wet_cap", 0, 100)),
                    "pregnancy_relief": tuning.get(self.state, "asmr", "pregnancy_relief",
                        self.settings.float("asmr.pregnancy_relief", 0, 100)),
                    "pregnancy_relief_cap": tuning.get(self.state, "asmr", "pregnancy_relief_cap",
                        self.settings.float("asmr.pregnancy_relief_cap", 0, 100)),
                    "sleep_chance": tuning.get(self.state, "asmr", "sleep_chance",
                        self.settings.float("asmr.sleep_chance", 0, 100)),
                    "request_start_hour": tuning.get(self.state, "asmr", "request_start_hour",
                        self.settings.int("asmr.request_start_hour", 0, 23)),
                    "request_end_hour": tuning.get(self.state, "asmr", "request_end_hour",
                        self.settings.int("asmr.request_end_hour", 0, 23)),
                    "request_chance": tuning.get(self.state, "asmr", "request_chance",
                        self.settings.float("asmr.request_chance", 0, 100)),
                    "request_wait_minutes": tuning.get(self.state, "asmr", "request_wait_minutes",
                        self.settings.int("asmr.request_wait_minutes", 1, 120)),
                },
                "edge": {
                    "auto_full_minutes": tuning.get(
                        self.state, "edge", "auto_full_minutes",
                        self.settings.int("edge.auto_full_minutes", 0, 240)),
                },
                "orgasm": {
                    "minutes": tuning.get(
                        self.state, "orgasm", "minutes",
                        self.settings.int("orgasm.minutes", 1, 240)),
                },
                "clothing": {
                    "remove_shame": tuning.get(
                        self.state, "clothing", "remove_shame",
                        self.settings.float("clothing.remove_shame", 0, 100)),
                    "remove_shame_max": tuning.get(
                        self.state, "clothing", "remove_shame_max",
                        self.settings.float("clothing.remove_shame_max", 0, 100)),
                    "remove_desire": tuning.get(
                        self.state, "clothing", "remove_desire",
                        self.settings.float("clothing.remove_desire", 0, 100)),
                    "wear_shame_relief": tuning.get(
                        self.state, "clothing", "wear_shame_relief",
                        self.settings.float("clothing.wear_shame_relief", 0, 100)),
                    "change_minutes": tuning.get(
                        self.state, "clothing", "change_minutes",
                        self.settings.int("clothing.change_minutes", 0, 60)),
                    "undress_minutes": tuning.get(
                        self.state, "clothing", "undress_minutes",
                        self.settings.int("clothing.undress_minutes", 0, 60)),
                },
                "ejaculation": {
                    "volume_ml": tuning.get(
                        self.state, "ejaculation", "volume_ml",
                        self.settings.float("ejaculation.volume_ml", 0.1, 100)),
                },
                "uterus": {
                    "leak_per_hour": tuning.get(
                        self.state, "uterus", "leak_per_hour",
                        self.settings.float("ejaculation.uterus_leak_per_hour", 0, 100)),
                    "capacity_ml": fill.capacity_base(self.state, self.settings),
                    "stretch_at": fill.stretch_at(self.state, self.settings),
                    "stretch_ratio": fill.stretch_ratio_max(self.state, self.settings),
                    "overflow_at": fill.overflow_at(self.state, self.settings),
                    "overflow_minutes": fill.overflow_minutes(self.state, self.settings),
                    "after_leak_per_hour": fill.after_leak_per_hour(self.state, self.settings),
                    "after_leak_until": fill.after_leak_until(self.state, self.settings),
                    "manual": {
                        key: tuning.raw(self.state, "uterus", key, None) is not None
                        for key in ("leak_per_hour", "capacity_ml", "stretch_at",
                                    "stretch_ratio", "overflow_at", "overflow_minutes",
                                    "after_leak_per_hour", "after_leak_until")
                    },
                },
                "succubus": {
                    "pc_energy_gain": tuning.get(
                        self.state, "succubus", "pc_energy_gain",
                        self.settings.int("succubus.pc_energy_gain", 0, 100)),
                    "fish_attachment_gain": tuning.get(
                        self.state, "succubus", "fish_attachment_gain",
                        self.settings.float("succubus.fish_attachment_gain", 0, 100)),
                    "fish_intimacy_gain": tuning.get(
                        self.state, "succubus", "fish_intimacy_gain",
                        self.settings.float("succubus.fish_intimacy_gain", 0, 100)),
                    "ejaculation_energy_gain": tuning.get(
                        self.state, "succubus", "ejaculation_energy_gain",
                        self.settings.int("succubus.ejaculation_energy_gain", 0, 100)),
                    "ejaculation_attachment_gain": tuning.get(
                        self.state, "succubus", "ejaculation_attachment_gain",
                        self.settings.float("succubus.ejaculation_attachment_gain", 0, 100)),
                    "ejaculation_intimacy_gain": tuning.get(
                        self.state, "succubus", "ejaculation_intimacy_gain",
                        self.settings.float("succubus.ejaculation_intimacy_gain", 0, 100)),
                    "desire_base_gain": tuning.get(
                        self.state, "succubus", "desire_base_gain",
                        self.settings.float("succubus.desire_base_gain", 0, 100)),
                    "desire_gain_per_level": tuning.get(
                        self.state, "succubus", "desire_gain_per_level",
                        self.settings.float("succubus.desire_gain_per_level", 0, 100)),
                    "absorption_multiplier": tuning.get(
                        self.state, "succubus", "absorption_multiplier",
                        self.settings.float("succubus.absorption_multiplier", 1, 100)),
                    "tail_sensitivity_scale": tuning.get(
                        self.state, "succubus", "tail_sensitivity_scale",
                        self.settings.float("succubus.tail_sensitivity_scale", 1, 5)),
                    "daily_limit": tuning.get(
                        self.state, "succubus", "daily_limit",
                        self.settings.int("succubus.daily_limit", 0, 100)),
                    "exp_gain": tuning.get(
                        self.state, "succubus", "exp_gain",
                        self.settings.int("succubus.exp_gain", 0, 1000)),
                    "exp_per_level": tuning.get(
                        self.state, "succubus", "exp_per_level",
                        self.settings.int("succubus.exp_per_level", 1, 10000)),
                },
                "endurance": {
                    "cap": tuning.get(self.state, "endurance", "cap",
                                      self.settings.float("endurance.cap", 1, 1000)),
                    "gain_at": tuning.get(self.state, "endurance", "gain_at",
                                          self.settings.float("endurance.gain_at", 0, 1000)),
                    "gain_multiplier": tuning.get(
                        self.state, "endurance", "gain_multiplier",
                        self.settings.float("endurance.gain_multiplier", 0, 10)),
                    "gain_low": tuning.get(self.state, "endurance", "gain_low",
                                           self.settings.float("endurance.gain_low", 0, 200)),
                    "gain_high": tuning.get(self.state, "endurance", "gain_high",
                                            self.settings.float("endurance.gain_high", 0, 200)),
                    "combo_grow": tuning.get(self.state, "endurance", "combo_grow",
                                             self.settings.float("endurance.combo_grow", 0, 5)),
                    "combo_cap": tuning.get(self.state, "endurance", "combo_cap",
                                            self.settings.float("endurance.combo_cap", 1, 20)),
                    "reset_minutes": tuning.get(self.state, "endurance", "reset_minutes",
                                                self.settings.int("endurance.reset_minutes", 0, 1440)),
                    "idle_minutes": tuning.get(self.state, "endurance", "idle_minutes",
                                               self.settings.int("endurance.idle_minutes", 0, 1440)),
                    "decay_per_hour": tuning.get(self.state, "endurance", "decay_per_hour",
                                                 self.settings.float("endurance.decay_per_hour", 0, 500)),
                    "level_at_1": tuning.get(self.state, "endurance", "level_at_1",
                                             self.settings.float("endurance.level_at_1", 0, 100)),
                    "level_at_2": tuning.get(self.state, "endurance", "level_at_2",
                                             self.settings.float("endurance.level_at_2", 0, 100)),
                    "level_at_3": tuning.get(self.state, "endurance", "level_at_3",
                                             self.settings.float("endurance.level_at_3", 0, 100)),
                    "sens_boost": tuning.get(
                        self.state, "endurance", "sens_boost",
                        self.settings.float("endurance.sens_boost", 0, 5)),
                    "manual": {key: tuning.raw(self.state, "endurance", key, None) is not None
                               for key in ("cap", "gain_at", "gain_multiplier",
                                           "gain_low", "gain_high",
                                           "combo_grow", "combo_cap", "reset_minutes",
                                           "idle_minutes", "decay_per_hour",
                                           "level_at_1", "level_at_2", "level_at_3")},
                },
                "pleasure": {
                    "decay_per_hour": tuning.get(self.state, "pleasure", "decay_per_hour",
                                                 self.settings.float("pleasure.decay_per_hour", 0, 500)),
                    "idle_minutes": tuning.get(self.state, "pleasure", "idle_minutes",
                                               self.settings.int("pleasure.idle_minutes", 0, 1440)),
                    "post_orgasm_minutes": tuning.get(
                        self.state, "pleasure", "post_orgasm_minutes",
                        self.settings.int("pleasure.post_orgasm_minutes", 0, 120)),
                    "manual": {key: tuning.raw(self.state, "pleasure", key, None) is not None
                               for key in ("decay_per_hour", "idle_minutes",
                                           "post_orgasm_minutes")},
                },
                "special": {
                    "every_minutes": tuning.get(self.state, "special", "every_minutes",
                                                self.settings.int("special.every_minutes", 1, 720)),
                    "jitter_percent": tuning.get(self.state, "special", "jitter_percent",
                                                 self.settings.float("special.jitter_percent", 0, 100)),
                    "pleasure_bonus": tuning.get(self.state, "special", "pleasure_bonus",
                                                 self.settings.float("special.pleasure_bonus", 0, 200)),
                    "endurance_bonus": tuning.get(self.state, "special", "endurance_bonus",
                                                  self.settings.float("special.endurance_bonus", 0, 200)),
                    "daily_chance": tuning.get(self.state, "special", "daily_chance",
                                               self.settings.float("special.daily_chance", 0, 100)),
                    "daily_pleasure": tuning.get(self.state, "special", "daily_pleasure",
                                                 self.settings.float("special.daily_pleasure", 0, 200)),
                    "daily_endurance": tuning.get(self.state, "special", "daily_endurance",
                                                  self.settings.float("special.daily_endurance", 0, 200)),
                    "manual": {key: tuning.raw(self.state, "special", key, None) is not None
                               for key in ("every_minutes", "jitter_percent", "pleasure_bonus",
                                           "endurance_bonus", "daily_chance", "daily_pleasure",
                                           "daily_endurance")},
                },
                "toys": {
                    "endurance_gain": tuning.get(self.state, "toys", "endurance_gain",
                                                 self.settings.float("toys.endurance_gain", 0, 200)),
                    "mg_soft_attachment": tuning.get(
                        self.state, "toys", "mg_soft_attachment",
                        self.settings.float("toys.mg_soft_attachment", 0, 100)),
                    "mg_soft_intimacy": tuning.get(
                        self.state, "toys", "mg_soft_intimacy",
                        self.settings.float("toys.mg_soft_intimacy", 0, 100)),
                    "mg_soft_desire": tuning.get(
                        self.state, "toys", "mg_soft_desire",
                        self.settings.float("toys.mg_soft_desire", 0, 100)),
                    "mg_body_pleasure": tuning.get(
                        self.state, "toys", "mg_body_pleasure",
                        self.settings.float("toys.mg_body_pleasure", 0, 100)),
                    "mg_body_desire": tuning.get(
                        self.state, "toys", "mg_body_desire",
                        self.settings.float("toys.mg_body_desire", 0, 100)),
                    "mg_body_wet": tuning.get(
                        self.state, "toys", "mg_body_wet",
                        self.settings.float("toys.mg_body_wet", 0, 100)),
                    "mg_body_endurance": tuning.get(
                        self.state, "toys", "mg_body_endurance",
                        self.settings.float("toys.mg_body_endurance", 0, 100)),
                    "mg_hot_pleasure": tuning.get(
                        self.state, "toys", "mg_hot_pleasure",
                        self.settings.float("toys.mg_hot_pleasure", 0, 100)),
                    "mg_hot_desire": tuning.get(
                        self.state, "toys", "mg_hot_desire",
                        self.settings.float("toys.mg_hot_desire", 0, 100)),
                    "mg_hot_wet": tuning.get(
                        self.state, "toys", "mg_hot_wet",
                        self.settings.float("toys.mg_hot_wet", 0, 100)),
                    "mg_hot_endurance": tuning.get(
                        self.state, "toys", "mg_hot_endurance",
                        self.settings.float("toys.mg_hot_endurance", 0, 100)),
                    "self_use_chance": tuning.get(
                        self.state, "toys", "self_use_chance",
                        self.settings.float("toys.self_use_chance", 0, 100)),
                    "self_use_check_minutes": tuning.get(
                        self.state, "toys", "self_use_check_minutes",
                        self.settings.int("toys.self_use_check_minutes", 1, 1440)),
                    "self_use_cooldown_minutes": tuning.get(
                        self.state, "toys", "self_use_cooldown_minutes",
                        self.settings.int("toys.self_use_cooldown_minutes", 0, 1440)),
                    "self_use_min_desire": tuning.get(
                        self.state, "toys", "self_use_min_desire",
                        self.settings.float("toys.self_use_min_desire", 0, 100)),
                    "self_use_min_wet": tuning.get(
                        self.state, "toys", "self_use_min_wet",
                        self.settings.float("toys.self_use_min_wet", 0, 100)),
                    "self_use_min_lewd": tuning.get(
                        self.state, "toys", "self_use_min_lewd",
                        self.settings.float("toys.self_use_min_lewd", 0, 100)),
                    "self_use_controller_chance": tuning.get(
                        self.state, "toys", "self_use_controller_chance",
                        self.settings.float("toys.self_use_controller_chance", 0, 100)),
                    "self_use_delay_seconds": tuning.get(
                        self.state, "toys", "self_use_delay_seconds",
                        self.settings.int("toys.self_use_delay_seconds", 0, 300)),
                    "manual": {key: tuning.raw(self.state, "toys", key, None) is not None
                               for key in ("endurance_gain", "self_use_chance",
                                           "self_use_check_minutes", "self_use_cooldown_minutes",
                                           "self_use_min_desire", "self_use_min_wet",
                                           "self_use_min_lewd", "self_use_controller_chance",
                                           "self_use_delay_seconds", "mg_soft_attachment",
                                           "mg_soft_intimacy", "mg_soft_desire",
                                           "mg_body_pleasure", "mg_body_desire",
                                           "mg_body_wet", "mg_body_endurance",
                                           "mg_hot_pleasure", "mg_hot_desire",
                                           "mg_hot_wet", "mg_hot_endurance")},
                },
                "self_test": {
                    "chance": tuning.get(
                        self.state, "self_test", "chance",
                        self.settings.float("self_test.chance", 0, 100)),
                    "min_delay_hours": tuning.get(
                        self.state, "self_test", "min_delay_hours",
                        self.settings.float("self_test.min_delay_hours", 1, 720)),
                },
                "surprise": {
                    "proactive_chance": tuning.get(
                        self.state, "surprise", "proactive_chance",
                        self.settings.float("surprise.proactive_chance", 0, 100)),
                    "proactive_delay_seconds": tuning.get(
                        self.state, "surprise", "proactive_delay_seconds",
                        self.settings.int("surprise.proactive_delay_seconds", 0, 300)),
                    "shock_minutes": tuning.get(
                        self.state, "surprise", "shock_minutes",
                        self.settings.int("surprise.shock_minutes", 1, 240)),
                    "remember_minutes": tuning.get(
                        self.state, "surprise", "remember_minutes",
                        self.settings.int("surprise.remember_minutes", 1, 1440)),
                    "manual": {key: tuning.raw(self.state, "surprise", key, None) is not None
                               for key in ("proactive_chance", "proactive_delay_seconds",
                                           "shock_minutes", "remember_minutes")},
                },
                "birth": {
                    "water_wet": tuning.get(self.state, "birth", "water_wet",
                                            self.settings.float("birth.water_wet", 0, 100)),
                    "pain_due": tuning.get(self.state, "birth", "pain_due",
                                           self.settings.float("birth.pain_due", 0, 100)),
                    "pain_pre": tuning.get(self.state, "birth", "pain_pre",
                                           self.settings.float("birth.pain_pre", 0, 100)),
                    "pain_active": tuning.get(self.state, "birth", "pain_active",
                                              self.settings.float("birth.pain_active", 0, 100)),
                    "pain_per_minute": tuning.get(
                        self.state, "birth", "pain_per_minute",
                        self.settings.float("birth.pain_per_minute", 0, 100)),
                    "pain_max": tuning.get(self.state, "birth", "pain_max",
                                           self.settings.float("birth.pain_max", 1, 100)),
                    "comfort_relief": tuning.get(
                        self.state, "birth", "comfort_relief",
                        self.settings.float("birth.comfort_relief", 0, 100)),
                    "comfort_cooldown_seconds": tuning.get(
                        self.state, "birth", "comfort_cooldown_seconds",
                        self.settings.int("birth.comfort_cooldown_seconds", 0, 3600)),
                    "gap_minutes": tuning.get(self.state, "birth", "gap_minutes",
                                              self.settings.int("birth.gap_minutes", 1, 1440)),
                    "resume_delay_seconds": tuning.get(
                        self.state, "birth", "resume_delay_seconds",
                        self.settings.int("birth.resume_delay_seconds", 0, 3600)),
                    "manual": {key: tuning.raw(self.state, "birth", key, None) is not None
                               for key in ("water_wet", "pain_due", "pain_pre", "pain_active",
                                           "pain_per_minute", "pain_max", "comfort_relief",
                                           "comfort_cooldown_seconds", "gap_minutes",
                                           "resume_delay_seconds")},
                },
                "insert": {
                    "wet_at": tuning.get(self.state, "insert", "wet_at",
                                         self.settings.float("insert.wet_at", 0, 100)),
                    "pleasure_at": tuning.get(self.state, "insert", "pleasure_at",
                                              self.settings.float("insert.pleasure_at", 0, 100)),
                    "pain": tuning.get(self.state, "insert", "pain",
                                       self.settings.float("insert.pain", 0, 100)),
                    "orgasm_pain": tuning.get(self.state, "insert", "orgasm_pain",
                                              self.settings.float("insert.orgasm_pain", 0, 100)),
                    "force_pain": tuning.get(self.state, "insert", "force_pain",
                                             self.settings.float("insert.force_pain", 0, 100)),
                    "force_pleasure_drop": tuning.get(
                        self.state, "insert", "force_pleasure_drop",
                        self.settings.float("insert.force_pleasure_drop", 0, 100)),
                    "force_endurance_drop": tuning.get(
                        self.state, "insert", "force_endurance_drop",
                        self.settings.float("insert.force_endurance_drop", 0, 100)),
                    "force_wet_gain": tuning.get(
                        self.state, "insert", "force_wet_gain",
                        self.settings.float("insert.force_wet_gain", 0, 100)),
                    "capacity_ml": tuning.get(self.state, "insert", "capacity_ml",
                                              self.settings.float("insert.capacity_ml", 0, 500)),
                    "fetus_pain": tuning.get(self.state, "insert", "fetus_pain",
                                             self.settings.float("insert.fetus_pain", 0, 100)),
                    "manual": {key: tuning.raw(self.state, "insert", key, None) is not None
                               for key in ("wet_at", "pleasure_at", "pain", "orgasm_pain",
                                           "force_pain", "force_pleasure_drop",
                                           "force_endurance_drop", "force_wet_gain",
                                           "capacity_ml", "fetus_pain")},
                },
                "unbirth": {
                    "grow_step": tuning.get(
                        self.state, "unbirth", "grow_step",
                        self.settings.float("unbirth.grow_step", 0.01, 1)),
                    "birth_min_ratio": tuning.get(
                        self.state, "unbirth", "birth_min_ratio",
                        self.settings.float("unbirth.birth_min_ratio", 0.01, 1)),
                    "birth_difficulty": tuning.get(
                        self.state, "unbirth", "birth_difficulty",
                        self.settings.float("unbirth.birth_difficulty", 0, 100)),
                    "birth_depth_steps": tuning.get(
                        self.state, "unbirth", "birth_depth_steps",
                        self.settings.int("unbirth.birth_depth_steps", 0, 10)),
                    "birth_step_minutes": tuning.get(
                        self.state, "unbirth", "birth_step_minutes",
                        self.settings.int("unbirth.birth_step_minutes", 1, 240)),
                    "resist_chance": tuning.get(
                        self.state, "unbirth", "resist_chance",
                        self.settings.float("unbirth.resist_chance", 0, 100)),
                    "resist_add_steps": tuning.get(
                        self.state, "unbirth", "resist_add_steps",
                        self.settings.int("unbirth.resist_add_steps", 0, 5)),
                    "request_chance": tuning.get(
                        self.state, "unbirth", "request_chance",
                        self.settings.float("unbirth.request_chance", 0, 100)),
                    "request_check_minutes": tuning.get(
                        self.state, "unbirth", "request_check_minutes",
                        self.settings.int("unbirth.request_check_minutes", 1, 1440)),
                    "request_cooldown_minutes": tuning.get(
                        self.state, "unbirth", "request_cooldown_minutes",
                        self.settings.int("unbirth.request_cooldown_minutes", 0, 1440)),
                    "request_wait_minutes": tuning.get(
                        self.state, "unbirth", "request_wait_minutes",
                        self.settings.int("unbirth.request_wait_minutes", 1, 120)),
                    "birth_giveup_after": tuning.get(
                        self.state, "unbirth", "birth_giveup_after",
                        self.settings.int("unbirth.birth_giveup_after", 1, 20)),
                    "tube_stage2": tuning.get(
                        self.state, "unbirth", "tube_stage2",
                        self.settings.float("unbirth.tube_stage2", 0, 100)),
                    "tube_stage3": tuning.get(
                        self.state, "unbirth", "tube_stage3",
                        self.settings.float("unbirth.tube_stage3", 0, 100)),
                    "tube_stage4": tuning.get(
                        self.state, "unbirth", "tube_stage4",
                        self.settings.float("unbirth.tube_stage4", 0, 100)),
                    "tube_unbirth": tuning.get(
                        self.state, "unbirth", "tube_unbirth",
                        self.settings.float("unbirth.tube_unbirth", 0, 100)),
                    "ovary_prob": tuning.get(
                        self.state, "unbirth", "ovary_prob",
                        self.settings.float("unbirth.ovary_prob", 0, 100)),
                    "tube_flow_base_minutes": tuning.get(
                        self.state, "unbirth", "tube_flow_base_minutes",
                        self.settings.int("unbirth.tube_flow_base_minutes", 1, 240)),
                    "tube_fill_percent": tuning.get(
                        self.state, "unbirth", "tube_fill_percent",
                        self.settings.int("unbirth.tube_fill_percent", 1, 100)),
                    "tube_flow_ref_ml": tuning.get(
                        self.state, "unbirth", "tube_flow_ref_ml",
                        self.settings.float("unbirth.tube_flow_ref_ml", 0.1, 100)),
                    "hymen_pass_pleasure": tuning.get(
                        self.state, "unbirth", "hymen_pass_pleasure",
                        self.settings.float("unbirth.hymen_pass_pleasure", 0, 100)),
                    "hymen_pass_endurance": tuning.get(
                        self.state, "unbirth", "hymen_pass_endurance",
                        self.settings.float("unbirth.hymen_pass_endurance", 0, 100)),
                    "hymen_pass_wet": tuning.get(
                        self.state, "unbirth", "hymen_pass_wet",
                        self.settings.float("unbirth.hymen_pass_wet", 0, 100)),
                    "hymen_pass_desire": tuning.get(
                        self.state, "unbirth", "hymen_pass_desire",
                        self.settings.float("unbirth.hymen_pass_desire", 0, 100)),
                    "inside_pleasure": tuning.get(
                        self.state, "unbirth", "inside_pleasure",
                        self.settings.float("unbirth.inside_pleasure", 0, 100)),
                    "inside_wet": tuning.get(
                        self.state, "unbirth", "inside_wet",
                        self.settings.float("unbirth.inside_wet", 0, 100)),
                    "inside_endurance": tuning.get(
                        self.state, "unbirth", "inside_endurance",
                        self.settings.float("unbirth.inside_endurance", 0, 100)),
                    "inside_dev": tuning.get(
                        self.state, "unbirth", "inside_dev",
                        self.settings.float("unbirth.inside_dev", 0, 100)),
                    "inside_sens": tuning.get(
                        self.state, "unbirth", "inside_sens",
                        self.settings.float("unbirth.inside_sens", 0, 10)),
                    "inside_max_minutes": tuning.get(
                        self.state, "unbirth", "inside_max_minutes",
                        self.settings.int("unbirth.inside_max_minutes", 1, 1440)),
                    "shrink_ratio": tuning.get(
                        self.state, "unbirth", "shrink_ratio",
                        self.settings.float("unbirth.shrink_ratio", 0, 1)),
                    "limit_factor": tuning.get(
                        self.state, "unbirth", "limit_factor",
                        self.settings.float("unbirth.limit_factor", 0, 5)),
                    "expand_small": tuning.get(
                        self.state, "unbirth", "expand_small",
                        self.settings.float("unbirth.expand_small", 0, 1)),
                    "expand_mid": tuning.get(
                        self.state, "unbirth", "expand_mid",
                        self.settings.float("unbirth.expand_mid", 0, 1)),
                    "enter_pleasure": tuning.get(
                        self.state, "unbirth", "enter_pleasure",
                        self.settings.float("unbirth.enter_pleasure", 0, 100)),
                    "enter_endurance": tuning.get(
                        self.state, "unbirth", "enter_endurance",
                        self.settings.float("unbirth.enter_endurance", 0, 100)),
                    "enter_wet": tuning.get(
                        self.state, "unbirth", "enter_wet",
                        self.settings.float("unbirth.enter_wet", 0, 100)),
                    "birth_steps": tuning.get(
                        self.state, "unbirth", "birth_steps",
                        self.settings.int("unbirth.birth_steps", 1, 20)),
                    "resist_desire": tuning.get(
                        self.state, "unbirth", "resist_desire",
                        self.settings.float("unbirth.resist_desire", 0, 100)),
                    "manual": {key: tuning.raw(self.state, "unbirth", key, None) is not None
                               for key in ("grow_step", "birth_min_ratio",
                                           "birth_difficulty", "birth_depth_steps",
                                           "birth_step_minutes", "resist_chance",
                                           "resist_add_steps", "request_chance",
                                           "request_check_minutes", "request_cooldown_minutes",
                                           "request_wait_minutes",
                                           "birth_giveup_after", "tube_stage2",
                                           "tube_stage3", "tube_stage4",
                                           "tube_unbirth", "ovary_prob",
                                           "tube_flow_base_minutes", "tube_flow_ref_ml",
                                           "tube_fill_percent",
                                           "hymen_pass_pleasure",
                                           "hymen_pass_endurance",
                                           "hymen_pass_wet", "hymen_pass_desire",
                                           "inside_pleasure", "inside_wet",
                                           "inside_endurance", "inside_dev",
                                           "inside_sens", "inside_max_minutes",
                                           "shrink_ratio", "limit_factor", "expand_small",
                                           "expand_mid", "enter_pleasure", "enter_endurance",
                                           "enter_wet", "birth_steps", "resist_desire")},
                },
                "condom": {
                    "remove_ask_chance": tuning.get(
                        self.state, "condom", "remove_ask_chance",
                        self.settings.float("condom.remove_ask_chance", 0, 100)),
                    "remove_help_chance": tuning.get(
                        self.state, "condom", "remove_help_chance",
                        self.settings.float("condom.remove_help_chance", 0, 100)),
                    "remove_min_minutes": tuning.get(
                        self.state, "condom", "remove_min_minutes",
                        self.settings.int("condom.remove_min_minutes", 1, 240)),
                    "remove_cooldown_minutes": tuning.get(
                        self.state, "condom", "remove_cooldown_minutes",
                        self.settings.int("condom.remove_cooldown_minutes", 1, 1440)),
                    "break_per_action": tuning.get(
                        self.state, "condom", "break_per_action",
                        self.settings.float("condom.break_per_action", 0, 100)),
                    "ask_chance": tuning.get(
                        self.state, "condom", "ask_chance",
                        self.settings.float("condom.ask_chance", 0, 100)),
                    "renew_ask_chance": tuning.get(
                        self.state, "condom", "renew_ask_chance",
                        self.settings.float("condom.renew_ask_chance", 0, 100)),
                    "unfelt_pleasure": tuning.get(
                        self.state, "condom", "unfelt_pleasure",
                        self.settings.float("condom.unfelt_pleasure", 0, 100)),
                    "unfelt_endurance": tuning.get(
                        self.state, "condom", "unfelt_endurance",
                        self.settings.float("condom.unfelt_endurance", 0, 100)),
                    "unfelt_chance": tuning.get(
                        self.state, "condom", "unfelt_chance",
                        self.settings.float("condom.unfelt_chance", 0, 100)),
                    "change_ask_chance": tuning.get(
                        self.state, "condom", "change_ask_chance",
                        self.settings.float("condom.change_ask_chance", 0, 100)),
                    "help_desire": tuning.get(
                        self.state, "condom", "help_desire",
                        self.settings.float("condom.help_desire", 0, 100)),
                    "help_shame": tuning.get(
                        self.state, "condom", "help_shame",
                        self.settings.float("condom.help_shame", 0, 100)),
                    "help_wet": tuning.get(
                        self.state, "condom", "help_wet",
                        self.settings.float("condom.help_wet", 0, 100)),
                    "manual": {key: tuning.raw(self.state, "condom", key, None) is not None
                               for key in ("break_per_action", "remove_ask_chance",
                                           "remove_help_chance", "remove_min_minutes",
                                           "remove_cooldown_minutes", "ask_chance",
                                           "renew_ask_chance", "unfelt_pleasure",
                                           "unfelt_endurance", "unfelt_chance",
                                           "change_ask_chance", "help_desire", "help_shame",
                                           "help_wet")},
                },
                "lewd": {
                    "max": tuning.get(self.state, "lewd", "max",
                                      self.settings.float("lewd.max", 1, 1000)),
                    "scene_add": tuning.get(self.state, "lewd", "scene_add",
                                            self.settings.float("lewd.scene_add", 0, 100)),
                    "daily_add": tuning.get(self.state, "lewd", "daily_add",
                                            self.settings.float("lewd.daily_add", 0, 100)),
                    "tick_minutes": tuning.get(self.state, "lewd", "tick_minutes",
                                               self.settings.int("lewd.tick_minutes", 1, 1440)),
                    "tick_min": tuning.get(self.state, "lewd", "tick_min",
                                           self.settings.float("lewd.tick_min", 0, 100)),
                    "cost_per_tick": tuning.get(self.state, "lewd", "cost_per_tick",
                                                self.settings.float("lewd.cost_per_tick", 0, 100)),
                    "desire_per_tick": tuning.get(self.state, "lewd", "desire_per_tick",
                                                  self.settings.float("lewd.desire_per_tick", 0, 100)),
                    "wet_per_tick": tuning.get(self.state, "lewd", "wet_per_tick",
                                               self.settings.float("lewd.wet_per_tick", 0, 100)),
                    "decay_after_minutes": tuning.get(self.state, "lewd", "decay_after_minutes",
                                                      self.settings.int("lewd.decay_after_minutes", 0, 10080)),
                    "decay_per_hour": tuning.get(self.state, "lewd", "decay_per_hour",
                                                 self.settings.float("lewd.decay_per_hour", 0, 100)),
                    "prompt_min": tuning.get(self.state, "lewd", "prompt_min",
                                             self.settings.float("lewd.prompt_min", 0, 100)),
                    "level_at_2": tuning.get(self.state, "lewd", "level_at_2",
                                             self.settings.float("lewd.level_at_2", 0, 100)),
                    "level_at_3": tuning.get(self.state, "lewd", "level_at_3",
                                             self.settings.float("lewd.level_at_3", 0, 100)),
                    "level_at_4": tuning.get(self.state, "lewd", "level_at_4",
                                             self.settings.float("lewd.level_at_4", 0, 100)),
                    "manual": {key: tuning.raw(self.state, "lewd", key, None) is not None
                               for key in ("max", "scene_add", "daily_add", "tick_minutes",
                                           "tick_min", "cost_per_tick", "desire_per_tick",
                                           "wet_per_tick", "decay_after_minutes",
                                           "decay_per_hour")},
                },
                "night_raid": {
                    "start_hour": tuning.get(self.state, "night_raid", "start_hour",
                                             self.settings.int("night_raid.start_hour", 0, 23)),
                    "end_hour": tuning.get(self.state, "night_raid", "end_hour",
                                           self.settings.int("night_raid.end_hour", 0, 23)),
                    "desire_min": tuning.get(self.state, "night_raid", "desire_min",
                                             self.settings.float("night_raid.desire_min", 0, 100)),
                    "very_high_desire": tuning.get(
                        self.state, "night_raid", "very_high_desire",
                        self.settings.float("night_raid.very_high_desire", 0, 100)),
                    "very_high_wet_min": tuning.get(
                        self.state, "night_raid", "very_high_wet_min",
                        self.settings.float("night_raid.very_high_wet_min", 0, 100)),
                    "very_high_bonus": tuning.get(
                        self.state, "night_raid", "very_high_bonus",
                        self.settings.float("night_raid.very_high_bonus", 0, 100)),
                    "wet_min": tuning.get(self.state, "night_raid", "wet_min",
                                          self.settings.float("night_raid.wet_min", 0, 100)),
                    "chance": tuning.get(self.state, "night_raid", "chance",
                                         self.settings.float("night_raid.chance", 0, 100)),
                    "pregnancy_chance": tuning.get(
                        self.state, "night_raid", "pregnancy_chance",
                        self.settings.float("night_raid.pregnancy_chance", 0, 100)),
                    "activity_window_minutes": tuning.get(
                        self.state, "night_raid", "activity_window_minutes",
                        self.settings.int("night_raid.activity_window_minutes", 1, 1440)),
                    "after_ejac_minutes": tuning.get(
                        self.state, "night_raid", "after_ejac_minutes",
                        self.settings.int("night_raid.after_ejac_minutes", 0, 1440)),
                    "after_ejac_factor": tuning.get(
                        self.state, "night_raid", "after_ejac_factor",
                        self.settings.float("night_raid.after_ejac_factor", 0, 1)),
                    "unfinished_minutes": tuning.get(
                        self.state, "night_raid", "unfinished_minutes",
                        self.settings.int("night_raid.unfinished_minutes", 0, 1440)),
                    "unfinished_bonus": tuning.get(
                        self.state, "night_raid", "unfinished_bonus",
                        self.settings.float("night_raid.unfinished_bonus", 0, 100)),
                    "lead_minutes": tuning.get(self.state, "night_raid", "lead_minutes",
                                               self.settings.int("night_raid.lead_minutes", 0, 180)),
                    "wait_minutes": tuning.get(self.state, "night_raid", "wait_minutes",
                                               self.settings.int("night_raid.wait_minutes", 1, 120)),
                    "afterglow_minutes": tuning.get(
                        self.state, "night_raid", "afterglow_minutes",
                        self.settings.int("night_raid.afterglow_minutes", 0, 120)),
                    "after_scene_minutes": tuning.get(
                        self.state, "night_raid", "after_scene_minutes",
                        self.settings.int("night_raid.after_scene_minutes", 0, 1440)),
                    "cooldown_hours": tuning.get(self.state, "night_raid", "cooldown_hours",
                                                 self.settings.int("night_raid.cooldown_hours", 0, 168)),
                    "lewd_late_per_point": tuning.get(
                        self.state, "night_raid", "lewd_late_per_point",
                        self.settings.float("night_raid.lewd_late_per_point", 0, 100)),
                    "lewd_late_max": tuning.get(self.state, "night_raid", "lewd_late_max",
                                                self.settings.float("night_raid.lewd_late_max", 0, 100)),
                    "fish_stay_up_bonus": tuning.get(
                        self.state, "night_raid", "fish_stay_up_bonus",
                        self.settings.float("night_raid.fish_stay_up_bonus", 0, 100)),
                    "energy_gain": tuning.get(self.state, "night_raid", "energy_gain",
                                              self.settings.int("night_raid.energy_gain", 0, 100)),
                    "manual": {key: tuning.raw(self.state, "night_raid", key, None) is not None
                               for key in ("start_hour", "end_hour", "desire_min", "wet_min",
                                           "chance", "pregnancy_chance", "activity_window_minutes",
                                           "after_ejac_minutes", "after_ejac_factor",
                                           "unfinished_minutes", "unfinished_bonus",
                                           "lead_minutes", "wait_minutes", "afterglow_minutes",
                                           "cooldown_hours",
                                           "lewd_late_per_point", "lewd_late_max", "energy_gain")},
                },
                "squirt": {
                    "water_max": tuning.get(self.state, "squirt", "water_max",
                                            self.settings.float("squirt.water_max", 1, 1000)),
                    "regen_per_minute": tuning.get(
                        self.state, "squirt", "regen_per_minute",
                        self.settings.float("squirt.regen_per_minute", 0, 100)),
                    "min_water": tuning.get(self.state, "squirt", "min_water",
                                            self.settings.float("squirt.min_water", 0, 1000)),
                    "volume": tuning.get(self.state, "squirt", "volume",
                                         self.settings.float("squirt.volume", 0, 500)),
                    "volume_pleasure": tuning.get(
                        self.state, "squirt", "volume_pleasure",
                        self.settings.float("squirt.volume_pleasure", 0, 10)),
                    "volume_endurance": tuning.get(
                        self.state, "squirt", "volume_endurance",
                        self.settings.float("squirt.volume_endurance", 0, 10)),
                    "combo_volume": tuning.get(
                        self.state, "squirt", "combo_volume",
                        self.settings.float("squirt.combo_volume", 0, 10)),
                    "chance": tuning.get(self.state, "squirt", "chance",
                                         self.settings.float("squirt.chance", 0, 100)),
                    "pleasure_bonus": tuning.get(
                        self.state, "squirt", "pleasure_bonus",
                        self.settings.float("squirt.pleasure_bonus", 0, 100)),
                    "endurance_bonus": tuning.get(
                        self.state, "squirt", "endurance_bonus",
                        self.settings.float("squirt.endurance_bonus", 0, 100)),
                    "after_bonus": tuning.get(
                        self.state, "squirt", "after_bonus",
                        self.settings.float("squirt.after_bonus", 0, 100)),
                    "combo_bonus": tuning.get(
                        self.state, "squirt", "combo_bonus",
                        self.settings.float("squirt.combo_bonus", 0, 100)),
                    "cost_ratio": tuning.get(self.state, "squirt", "cost_ratio",
                                             self.settings.float("squirt.cost_ratio", 0, 10)),
                    "pleasure_gain": tuning.get(
                        self.state, "squirt", "pleasure_gain",
                        self.settings.float("squirt.pleasure_gain", 0, 100)),
                    "pleasure_cap": tuning.get(
                        self.state, "squirt", "pleasure_cap",
                        self.settings.float("squirt.pleasure_cap", 0, 100)),
                    "wet_gain": tuning.get(self.state, "squirt", "wet_gain",
                                           self.settings.float("squirt.wet_gain", 0, 100)),
                    "endurance_gain": tuning.get(
                        self.state, "squirt", "endurance_gain",
                        self.settings.float("squirt.endurance_gain", 0, 100)),
                    "manual": {key: tuning.raw(self.state, "squirt", key, None) is not None
                               for key in ("water_max", "regen_per_minute", "min_water",
                                           "volume", "volume_pleasure", "volume_endurance",
                                           "combo_volume", "chance", "pleasure_bonus",
                                           "endurance_bonus", "after_bonus", "combo_bonus",
                                           "cost_ratio", "pleasure_gain", "pleasure_cap",
                                           "wet_gain", "endurance_gain")},
                },
                "swallow": {
                    "collect_pleasure": tuning.get(
                        self.state, "swallow", "collect_pleasure",
                        self.settings.float("swallow.collect_pleasure", 0, 100)),
                    "desire_gain": tuning.get(
                        self.state, "swallow", "desire_gain",
                        self.settings.float("swallow.desire_gain", 0, 100)),
                    "wet_gain": tuning.get(
                        self.state, "swallow", "wet_gain",
                        self.settings.float("swallow.wet_gain", 0, 100)),
                    "swallow_pleasure": tuning.get(
                        self.state, "swallow", "swallow_pleasure",
                        self.settings.float("swallow.swallow_pleasure", 0, 100)),
                    "swallow_desire": tuning.get(
                        self.state, "swallow", "swallow_desire",
                        self.settings.float("swallow.swallow_desire", 0, 100)),
                    "swallow_wet": tuning.get(
                        self.state, "swallow", "swallow_wet",
                        self.settings.float("swallow.swallow_wet", 0, 100)),
                    "auto_chance": tuning.get(
                        self.state, "swallow", "auto_chance",
                        self.settings.float("swallow.auto_chance", 0, 100)),
                    "auto_swallow_chance": tuning.get(
                        self.state, "swallow", "auto_swallow_chance",
                        self.settings.float("swallow.auto_swallow_chance", 0, 100)),
                    "manual": {key: tuning.raw(self.state, "swallow", key, None) is not None
                               for key in ("collect_pleasure", "desire_gain", "wet_gain",
                                           "swallow_pleasure", "swallow_desire",
                                           "swallow_wet", "auto_chance",
                                           "auto_swallow_chance")},
                },
                "combo": {
                    "overstim_after": self._combo_limit(),
                    "manual": {key: tuning.raw(self.state, "combo", key, None) is not None
                               for key in ("overstim_after",)},
                },
                "menstrual": {
                    "pad_shame_cap": tuning.get(
                        self.state, "menstrual", "pad_shame_cap",
                        self.settings.float("menstrual.pad_shame_cap", 0, 100)),
                },
                "children": {
                    "intimacy_interrupt_chance": tuning.get(
                        self.state, "children", "intimacy_interrupt_chance",
                        self.settings.float("children.intimacy_interrupt_chance", 0, 100)),
                    "intimacy_child_max_age_years": tuning.get(
                        self.state, "children", "intimacy_child_max_age_years",
                        self.settings.int("children.intimacy_child_max_age_years", 1, 18)),
                },
                "mood": {
                    "shame_decay_per_hour": tuning.get(
                        self.state, "mood", "shame_decay_per_hour",
                        self.settings.float("mood.shame_decay_per_hour", 0, 100)),
                    "desire_decay_per_hour": tuning.get(
                        self.state, "mood", "desire_decay_per_hour",
                        self.settings.float("mood.desire_decay_per_hour", 0, 100)),
                    "self_approach_after_scene_minutes": tuning.get(
                        self.state, "mood", "self_approach_after_scene_minutes",
                        self.settings.int("mood.self_approach_after_scene_minutes", 0, 1440)),
                    "manual": {key: tuning.raw(self.state, "mood", key, None) is not None
                               for key in ("shame_decay_per_hour", "desire_decay_per_hour",
                                           "self_approach_after_scene_minutes")},
                },
                "size": {
                    "penis_length": tuning.get(self.state, "size", "penis_length",
                                               self.settings.float("size.penis_length", 1, 100)),
                    "vagina_width": tuning.get(
                        self.state, "size", "vagina_width",
                        self.settings.float("size.vagina_width", 0.2, 50)),
                    "hymen_depth": tuning.get(self.state, "size", "hymen_depth",
                                              self.settings.float("size.hymen_depth", 0.5, 30)),
                    "hymen_hole": tuning.get(self.state, "size", "hymen_hole",
                                             self.settings.float("size.hymen_hole", 0.1, 100)),
                    "penis_girth": tuning.get(self.state, "size", "penis_girth",
                                              self.settings.float("size.penis_girth", 0.5, 50)),
                    "penis_head_length": tuning.get(
                        self.state, "size", "penis_head_length",
                        self.settings.float("size.penis_head_length", 0.5, 50)),
                    "uterus_length": tuning.get(
                        self.state, "size", "uterus_length",
                        self.settings.float("size.uterus_length", 1, 100)),
                    "tube_width": tuning.get(
                        self.state, "size", "tube_width",
                        self.settings.float("size.tube_width", 0.1, 20)),
                    "ovary_width": tuning.get(
                        self.state, "size", "ovary_width",
                        self.settings.float("size.ovary_width", 0.1, 20)),
                    "fetus_uterus_max_ratio": tuning.get(
                        self.state, "size", "fetus_uterus_max_ratio",
                        self.settings.float("size.fetus_uterus_max_ratio", 1, 5)),
                    "vagina_length": tuning.get(self.state, "size", "vagina_length",
                                                self.settings.float("size.vagina_length", 1, 100)),
                    "notice_chance": tuning.get(self.state, "size", "notice_chance",
                                                self.settings.float("size.notice_chance", 0, 100)),
                    "dev_sens_boost": tuning.get(
                        self.state, "size", "dev_sens_boost",
                        self.settings.float("size.dev_sens_boost", 0, 5)),
                    "pre_orgasm_shorten": tuning.get(
                        self.state, "size", "pre_orgasm_shorten",
                        self.settings.float("size.pre_orgasm_shorten", 0, 20)),
                    "pre_orgasm_ratio": tuning.get(
                        self.state, "size", "pre_orgasm_ratio",
                        self.settings.float("size.pre_orgasm_ratio", 0, 1)),
                    "cervix_stretch_max": tuning.get(
                        self.state, "size", "cervix_stretch_max",
                        self.settings.float("size.cervix_stretch_max", 0, 20)),
                    "cervix_stretch_ratio": tuning.get(
                        self.state, "size", "cervix_stretch_ratio",
                        self.settings.float("size.cervix_stretch_ratio", 0, 1)),
                    "cervix_stretch_minutes": tuning.get(
                        self.state, "size", "cervix_stretch_minutes",
                        self.settings.int("size.cervix_stretch_minutes", 1, 240)),
                    "manual": {key: tuning.raw(self.state, "size", key, None) is not None
                               for key in ("vagina_width", "hymen_hole", "hymen_depth",
                                           "penis_length", "penis_girth",
                                           "penis_head_length", "uterus_length",
                                           "vagina_length", "notice_chance")},
                },
                "sleep": {
                    "wake_grace_minutes": tuning.get(
                        self.state, "sleep", "wake_grace_minutes",
                        self.settings.int("sleep.wake_grace_minutes", 1, 240)),
                    "afterglow_minutes": tuning.get(
                        self.state, "sleep", "afterglow_minutes",
                        self.settings.int("sleep.afterglow_minutes", 0, 240)),
                    "manual": {key: tuning.raw(self.state, "sleep", key, None) is not None
                               for key in ("wake_grace_minutes", "afterglow_minutes")},
                },
                "wetness": {
                    "base": tuning.get(self.state, "wetness", "base",
                                       self.settings.float("wetness.base", 0, 100)),
                    "prompt_min_level": tuning.get(
                        self.state, "wetness", "prompt_min_level",
                        self.settings.int("wetness.prompt_min_level", 1, 4)),
                    "gain_per_touch": tuning.get(self.state, "wetness", "gain_per_touch",
                                                 self.settings.float("wetness.gain_per_touch", 0, 100)),
                    "scene_step_gain": tuning.get(
                        self.state, "wetness", "scene_step_gain",
                        self.settings.float("wetness.scene_step_gain", 0, 100)),
                    "daily_step_gain": tuning.get(
                        self.state, "wetness", "daily_step_gain",
                        self.settings.float("wetness.daily_step_gain", 0, 100)),
                    "gain_per_pleasure": tuning.get(
                        self.state, "wetness", "gain_per_pleasure",
                        self.settings.float("wetness.gain_per_pleasure", 0, 10)),
                    "idle_minutes": tuning.get(self.state, "wetness", "idle_minutes",
                                               self.settings.int("wetness.idle_minutes", 0, 1440)),
                    "decay_per_hour": tuning.get(self.state, "wetness", "decay_per_hour",
                                                 self.settings.float("wetness.decay_per_hour", 0, 500)),
                    "level_at_1": tuning.get(self.state, "wetness", "level_at_1",
                                             self.settings.float("wetness.level_at_1", 0, 100)),
                    "level_at_2": tuning.get(self.state, "wetness", "level_at_2",
                                             self.settings.float("wetness.level_at_2", 0, 100)),
                    "level_at_3": tuning.get(self.state, "wetness", "level_at_3",
                                             self.settings.float("wetness.level_at_3", 0, 100)),
                    "pain_wetness_at": tuning.get(self.state, "wetness", "pain_wetness_at",
                                                  self.settings.float("wetness.pain_wetness_at", 0, 100)),
                    "pain_pleasure_at": tuning.get(self.state, "wetness", "pain_pleasure_at",
                                                   self.settings.float("wetness.pain_pleasure_at", 0, 100)),
                    "pain_relief": tuning.get(self.state, "wetness", "pain_relief",
                                              self.settings.float("wetness.pain_relief", 0, 100)),
                    "fish_desire_gain": tuning.get(
                        self.state, "wetness", "fish_desire_gain",
                        self.settings.float("wetness.fish_desire_gain", 0, 100)),
                    "fish_desire_scale": tuning.get(
                        self.state, "wetness", "fish_desire_scale",
                        self.settings.float("wetness.fish_desire_scale", 0, 10)),
                    "fish_desire_to_wet": tuning.get(
                        self.state, "wetness", "fish_desire_to_wet",
                        self.settings.float("wetness.fish_desire_to_wet", 0, 100)),
                    "base_float_desire": tuning.get(
                        self.state, "wetness", "base_float_desire",
                        self.settings.float("wetness.base_float_desire", 0, 100)),
                    "base_float_pleasure": tuning.get(
                        self.state, "wetness", "base_float_pleasure",
                        self.settings.float("wetness.base_float_pleasure", 0, 100)),
                    "base_float_endurance": tuning.get(
                        self.state, "wetness", "base_float_endurance",
                        self.settings.float("wetness.base_float_endurance", 0, 100)),
                    "base_float_cap": tuning.get(
                        self.state, "wetness", "base_float_cap",
                        self.settings.float("wetness.base_float_cap", 0, 100)),
                    "fish_desire_min_minutes": tuning.get(
                        self.state, "wetness", "fish_desire_min_minutes",
                        self.settings.int("wetness.fish_desire_min_minutes", 0, 1440)),
                    "manual": {key: tuning.raw(self.state, "wetness", key, None) is not None
                               for key in ("base", "gain_per_touch", "gain_per_pleasure",
                                           "idle_minutes", "decay_per_hour", "level_at_1",
                                           "level_at_2", "level_at_3", "pain_wetness_at",
                                           "pain_pleasure_at", "pain_relief",
                                           "fish_desire_gain", "fish_desire_scale",
                                           "fish_desire_to_wet", "fish_desire_min_minutes",
                                           "base_float_desire", "base_float_pleasure",
                                           "base_float_endurance", "base_float_cap")},
                },
            },
            "status": self._status_flags(),
            "edge": {
                "enabled": bool(self.settings.bool("edge.enabled")),
                "stack": state_mod.edge_stack(self.state, self.settings),
                "craving": round(state_mod.edge_craving(self.state, self.settings), 1),
                "bonus": round(state_mod.edge_threshold_bonus(self.state, self.settings), 1),
                "total": util.safe_int((self.state.get("edge") or {}).get("total"), 0),
                "step": round(state_mod.edge_step(self.state, self.settings), 2),
                "step_config": round(self.settings.float("edge.threshold_step", 0.0, 50.0), 2),
                "next_bonus": state_mod.edge_next_bonus(self.state, self.settings),
                "auto_full_minutes": tuning.get(
                    self.state, "edge", "auto_full_minutes",
                    self.settings.int("edge.auto_full_minutes", 0, 240)),
                "decay": round(self.settings.float("edge.step_decay", 0.0, 1.0), 2),
            },
            "ovulation": {
                "induced": state_mod.ovulation_active(self.state),
                "until": (datetime.fromtimestamp(
                    state_mod.ovulation_until(self.state)).strftime("%m-%d %H:%M")
                    if state_mod.ovulation_active(self.state) else ""),
            },
            "probability": prob,
            "pregnancy": ({
                "pregnant": True,
                "month": prog["month"], "months": prog["months"],
                "week": prog["week"], "stage": prog["stage"]["title"],
                "stage_key": prog["stage"]["key"],
                "due": prog["due_date"].isoformat(),
                "due_jitter_days": prog.get("due_jitter_days", 0),
                "days_left": prog["days_left"],
                "known": prog.get("known"), "suspected": prog.get("suspected"),
                "told": prog.get("told"),
                "suppressed": bool(prog.get("suppressed_pc_cycle")),
                "conceived": prog["conceived_date"].isoformat(),
                "fetuses": int(prog.get("fetuses") or 1),
                "multiple": int(prog.get("fetuses") or 1) > 1,
                "stage_feel": prog["stage"].get("feel") or "",
                "stage_intimacy": prog["stage"].get("intimacy") or "",
            } if prog else None),
            "postpartum": {
                "active": postpartum,
                "until": pregnancy.postpartum_until_text(self.state),
                "no_conception": bool(self.settings.bool("pregnancy.postpartum_no_conception")),
                "stage": (postpartum_stage or {}).get("key", ""),
                "stage_label": {"hard": "前段·绝对不行",
                                "low": "后段·概率很低",
                                "normal": "恢复后期"}.get(
                                    (postpartum_stage or {}).get("key", ""), ""),
                "days": (postpartum_stage or {}).get("days", 0),
                "hard_days": (postpartum_stage or {}).get("hard_days", 0),
                "low_days": (postpartum_stage or {}).get("low_days", 0),
                "scale": (postpartum_stage or {}).get("scale", 1.0),
                "hard_until": (postpartum_stage or {}).get("hard_until_text", ""),
                "low_until": (postpartum_stage or {}).get("low_until_text", ""),
                "blocked": bool(postpartum_hard),
            },
            "self_test": {
                "window": ({"ready": bool(w.get("ready")),
                            "due_at": util.safe_float(w.get("due_at"), 0.0),
                            "expires_at": util.safe_float(w.get("expires_at"), 0.0)}
                           if (w := pregnancy.self_test_window(self.state)) else None),
                "known": pregnancy.knows(self.state),
                "suspected": bool((pregnancy.pregnancy_of(self.state) or {}).get("suspected")),
                "told": pregnancy.told(self.state),
                "last_result": (lambda last: str(
                    last.get("result") if isinstance(last, dict)
                    else ((pregnancy.pregnancy_of(self.state) or {}).get("test_result") or ""))
                    )(self.state.get("last_self_test")),
                "last_by": str((self.state.get("last_self_test") or {}).get("by") or ""),
                "last_text": str((self.state.get("last_self_test") or {}).get("text") or ""),
                "tested_at": util.safe_float(
                    (pregnancy.pregnancy_of(self.state) or {}).get("tested_at"), 0.0),
            },
            "last_roll": self._last_roll_payload(),
            "log": [{"at": util.safe_float(row.get("at"), 0.0),
                     "kind": row.get("kind"), "text": row.get("text")}
                    for row in state_mod.recent_log(self.state, 14)],
            "state_path": str(self.store.path),
            "server_time": util.now_ts(),
        }

    def _last_roll_payload(self) -> dict | None:
        roll = self.state.get("last_roll")
        if not isinstance(roll, dict):
            return None
        return {"at": util.safe_float(roll.get("at"), 0.0),
                "probability": util.safe_float(roll.get("probability"), 0.0),
                "hit": bool(roll.get("hit")),
                "phase": roll.get("phase"),
                "inside": bool(roll.get("inside"))}

    async def _web_routes(self, **kwargs) -> dict:
        """排障用：列出当前已注册的 Web 路由和归属插件。"""
        rows = []
        for entry in getattr(self.context, "registered_web_apis", []) or []:
            try:
                route, handler, methods, _desc = entry
            except (TypeError, ValueError):
                continue
            owner = getattr(getattr(handler, "__self__", None), "__class__", None)
            rows.append({"route": route, "methods": list(methods),
                         "owner": str(getattr(owner, "__module__", "") or "")})
        return {"ok": True, "data": rows}

    async def _web_state(self, **kwargs) -> dict:
        try:
            return {"ok": True, "data": self._web_payload()}
        except Exception as error:
            logger.warning("[受孕] 面板读取状态失败：%s", error)
            return {"ok": False, "error": str(error), "data": {}}

    async def _web_action(self, **kwargs) -> dict:
        """面板上的按钮：快感 / 高潮 / 内射 / 验孕 / 同意 / 场景 / 强制 / 重置。"""
        from astrbot.api.web import request as web_request

        try:
            body = await web_request.json({}) or {}
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        # 兼容手工用 query 调：?action=pleasure&amount=12
        if not body:
            try:
                query = web_request.query
                body = {key: query.get(key) for key in ("action", "amount", "inside",
                                                         "enabled", "force", "confirm")
                        if query.get(key) is not None}
            except Exception:
                body = {}
        action = str(body.get("action") or "").strip().lower()
        try:
            message = await self._run_web_action(action, body)
        except Exception as error:
            logger.warning("[受孕] 面板操作 %s 失败：%s", action, error)
            return {"ok": False, "error": str(error), "data": self._web_payload()}
        return {"ok": True, "message": message, "data": self._web_payload()}

    async def _run_web_action(self, action: str, body: dict) -> str:
        if action == "pleasure":
            amount = _clamp_amount(body.get("amount"), 1.0, 50.0,
                                   self.settings.float("pleasure.tool_gain", 0.0, 100.0))
            result = self._record_pleasure(amount, "面板")
            if result and result.get("refused"):
                return f"未记录：{result['refused']}"
            extra = f"（难受中，还要缓 {result['rest']} 分钟）" if result.get("pain") else ""
            return f"快感 {result['before']:.0f} → {result['value']:.0f}{extra}"
        if action == "orgasm":
            result = self._record_orgasm("面板", force=bool(body.get("force")))
            if result and result.get("refused"):
                return f"未记录：{result['refused']}"
            combo = result.get("combo") or {}
            tag = f"（连续第 {combo.get('count', 1)} 次）" if combo.get("count", 0) > 1 else ""
            return f"记下第 {result['session']} 次高潮{tag}，快感回落到 {result['after']:.0f}"
        if action == "touch":
            zone = str(body.get("zone") or "kiss")
            times = _clamp_amount(body.get("times"), 1, 20, 1)
            method = str(body.get("method") or "")
            result = self._record_touch(zone, int(times), "面板", method=method)
            if result.get("refused"):
                return f"未记录：{result['refused']}"
            if result.get("sub", {}).get("method_label"):
                shown = f"{result['label']}（{result['sub']['method_label']}）"
            else:
                shown = f"{result['label']}"
            message = (f"{shown} ×{result['times']}：快感 +{result['gain']:.0f}，"
                       f"现在 {result['value']:.0f}")
            sub = result.get("sub") or {}
            burst = sub.get("burst")
            if burst:
                message += (f"；子敏感度满了 → 开发度 +{burst['dev_gain']:.1f}"
                            f"（{burst['dev']}%）、敏感度 +{burst['sensitivity_gain']:.2f}"
                            f"（×{burst['sensitivity']:.2f}）、快感再 +{burst['pleasure']:.0f}")
            elif sub.get("gain"):
                message += f"；子敏感度 {sub['charge']:.0f}%（{sub['level_title']}）"
            elif sub.get("blocked"):
                message += f"；子敏感度没涨（{sub['blocked']}）"
            return message
        if action == "edge_step":
            if bool(body.get("reset")):
                state_mod.set_edge_step(self.state, None)
                self._save()
                base = self.settings.float("edge.threshold_step", 0.0, 50.0)
                return f"门槛加成已恢复跟随配置（+{base:.1f}）"
            if body.get("value") is not None:
                new = state_mod.set_edge_step(self.state, body.get("value"))
            else:
                current = state_mod.edge_step(self.state, self.settings)
                delta = _clamp_amount(body.get("delta"), -10.0, 10.0, 0.0)
                new = state_mod.set_edge_step(self.state, current + delta)
            self._save()
            decay = self.settings.float("edge.step_decay", 0.0, 1.0)
            return (f"下次寸止门槛 +{new:.1f}（之后每次 ×{decay:.2f}，"
                    f"下一次实际 +{state_mod.edge_next_bonus(self.state, self.settings):.1f}）")
        if action == "zone_dev":
            zone = intimacy.normalize_zone(str(body.get("zone") or ""))
            if not zone:
                return "没有这个敏感点"
            if bool(body.get("reset")):
                dev = intimacy.set_zone_dev(self.state, self.settings, zone, None)
            elif body.get("value") is not None:
                dev = intimacy.set_zone_dev(self.state, self.settings, zone, body.get("value"))
            else:
                current = intimacy.zone_dev_effective(self.state, self.settings, zone)
                delta = _clamp_amount(body.get("delta"), -10.0, 10.0, 0.0)
                dev = intimacy.set_zone_dev(self.state, self.settings, zone, current + delta)
            self._save()
            formula = intimacy.zone_formula_gain(self.state, self.settings, zone)
            return (f"{intimacy.ZONE_LABELS[zone]} 开发度改为 {dev}%"
                    f"（公式涨幅 +{formula:.1f}）")
        if action == "zone_gain":
            zone = intimacy.normalize_zone(str(body.get("zone") or ""))
            if not zone:
                return "没有这个敏感点"
            if bool(body.get("reset")):
                gain = intimacy.set_zone_gain(self.state, self.settings, zone, None)
                self._save()
                return f"{intimacy.ZONE_LABELS[zone]} 涨幅已恢复公式：+{gain:.1f}"
            if body.get("value") is not None:
                value = body.get("value")
            else:
                current = intimacy.zone_gain_effective(self.state, self.settings, zone)
                value = current + _clamp_amount(body.get("delta"), -10.0, 10.0, 0.0)
            gain = intimacy.set_zone_gain(self.state, self.settings, zone, value)
            self._save()
            return f"{intimacy.ZONE_LABELS[zone]} 每次涨幅改为 +{gain:.1f}"
        if action == "zone_toggle":
            zone = intimacy.normalize_zone(str(body.get("zone") or "tail"))
            if not zone:
                return "没有这个敏感点"
            current = intimacy.zone_enabled_effective(self.state, self.settings, zone)
            intimacy.set_zone_enabled(self.state, zone, not current)
            self._save()
            label = intimacy.ZONE_LABELS.get(zone, zone)
            return f"{label}敏感点已{'关闭' if current else '开启'}"
        if action in ("sub_zone_fill", "sub_zone_add", "sub_zone_reset"):
            if not self.settings.bool("sub_zones.enabled"):
                return "子敏感度关着（配置 sub_zones.enabled）"
            in_scene, why = self._scene_active()
            zone = intimacy.normalize_zone(str(body.get("zone") or ""))
            if action == "sub_zone_reset" and not zone:
                cleared = subzone.reset(self.state)
                self._save()
                return f"已清空 {cleared} 个部位的子敏感度进度"
            if not zone:
                return "没有这个敏感点"
            if action == "sub_zone_reset":
                subzone.reset(self.state, zone)
                self._save()
                return f"{intimacy.ZONE_LABELS.get(zone, zone)} 子敏感度已清零"
            if self.settings.bool("sub_zones.scene_only") and not in_scene:
                return (f"她不在受孕活动里（{why}）：先 /受孕场景、或碰她一下开场，"
                        f"子敏感度才会涨")
            if action == "sub_zone_fill":
                result = subzone.fill(self.state, self.settings, zone, in_scene=in_scene)
            else:
                amount = _clamp_amount(body.get("value"), 0.0, 200.0, 10.0)
                result = subzone.add(self.state, self.settings, zone, amount,
                                     in_scene=in_scene)
            if result.get("blocked"):
                self._save()
                return f"{result['label']} 子敏感度没动：{result['blocked']}"
            burst = result.get("burst")
            if not burst:
                self._save()
                return (f"{result['label']} 子敏感度 {result['charge']:.0f}/"
                        f"{result['max']:.0f}（{result['level_title']}）")
            state_mod.append_log(
                self.state, "subzone",
                f"子敏感度溢出（{burst['label']} 第 {burst['count']} 次·面板）："
                f"开发度 +{burst['dev_gain']:.1f} → {burst['dev']}%、"
                f"敏感度 +{burst['sensitivity_gain']:.2f} → ×{burst['sensitivity']:.2f}、"
                f"快感 +{burst['pleasure']:.1f}")
            self._save()
            return (f"{burst['label']} 子敏感度溢出：开发度 +{burst['dev_gain']:.1f}"
                    f"（{burst['dev']}%）、敏感度 +{burst['sensitivity_gain']:.2f}"
                    f"（×{burst['sensitivity']:.2f}）、快感 +{burst['pleasure']:.0f}；"
                    f"条 {burst['fall_seconds']:.1f} 秒内回落")
        if action in ("sub_keywords_save", "sub_keywords_reset"):
            zone = intimacy.normalize_zone(str(body.get("zone") or ""))
            method = subzone.normalize_method(zone, body.get("method") or "")
            if not zone:
                return "没有这个敏感点"
            label = intimacy.ZONE_LABELS.get(zone, zone)
            if action == "sub_keywords_reset":
                if method:
                    cleared = subzone.reset_method_keywords(self.state, zone, method)
                    self._save()
                    how = subzone.method_label(method)
                    return (f"{label}·{how} 的关键词已恢复默认" if cleared
                            else f"{label}·{how} 本来就是默认关键词")
                if body.get("method"):
                    return f"{label} 没有这个方式：{body.get('method')}"
                cleared = subzone.reset_method_keywords(self.state, zone)
                self._save()
                return (f"{label} 的关键词已全部恢复默认（{cleared} 个方式）" if cleared
                        else f"{label} 本来就是默认关键词")
            if not method:
                return f"{label} 没有这个方式：{body.get('method') or '（空）'}"
            words = subzone.set_method_keywords(self.state, zone, method, body.get("keywords"))
            self._save()
            how = subzone.method_label(method)
            if not words:
                return f"{label}·{how} 的关键词已清空（这个方式不再自动判断）"
            return (f"{label}·{how} 的关键词已保存（{len(words)} 个："
                    f"{'、'.join(words[:6])}{'…' if len(words) > 6 else ''}）")
        if action in ("sub_prompt_save", "sub_prompt_reset"):
            zone = intimacy.normalize_zone(str(body.get("zone") or ""))
            method = subzone.normalize_method(zone, body.get("method") or "")
            if action == "sub_prompt_reset":
                if not zone:
                    cleared = subzone.reset_prompts(self.state)
                    self._save()
                    return f"已把所有部位的提示词恢复内置默认（{cleared} 个部位）"
                label = intimacy.ZONE_LABELS.get(zone, zone)
                if body.get("method"):
                    cleared = subzone.reset_prompts(self.state, zone, method=method)
                    self._save()
                    how = subzone.method_label(method) or str(body.get("method"))
                    return (f"{label}·{how} 的提示词已恢复内置默认" if cleared
                            else f"{label}·{how} 本来就是内置默认")
                if body.get("level") is not None:
                    level = int(_clamp_amount(body.get("level"), 1, 3, 1))
                    cleared = subzone.reset_prompts(self.state, zone, level=level)
                    self._save()
                    return (f"{label} {subzone.level_title(level)} 已恢复内置默认" if cleared
                            else f"{label} {subzone.level_title(level)} 本来就是内置默认")
                cleared = subzone.reset_prompts(self.state, zone)
                self._save()
                return (f"{label} 的阶段和方式提示词都已恢复内置默认" if cleared
                        else f"{label} 本来就是内置默认")
            if not zone:
                return "没有这个敏感点"
            label = intimacy.ZONE_LABELS.get(zone, zone)
            text = str(body.get("text") or "")
            if body.get("method"):
                if not method:
                    return f"{label} 没有这个方式：{body.get('method')}"
                value = subzone.set_method_prompt(self.state, zone, method, text)
                self._save()
                how = subzone.method_label(method)
                return (f"{label}·{how} 的提示词已保存（{len(value)} 字）" if value
                        else f"{label}·{how} 已恢复内置默认")
            texts = body.get("texts")
            if isinstance(texts, (list, tuple)):
                values = subzone.set_prompts(self.state, zone, texts)
                self._save()
                return (f"{label} 的三段提示词已保存（第1段 {len(values[0])} 字、"
                        f"第2段 {len(values[1])} 字、第3段 {len(values[2])} 字）")
            level = int(_clamp_amount(body.get("level"), 1, 3, 1))
            value = subzone.set_prompt(self.state, zone, level, text)
            self._save()
            return (f"{label} {subzone.level_title(level)} 的提示词已保存"
                    f"（{len(value)} 字）" if value else
                    f"{label} {subzone.level_title(level)} 已恢复内置默认")
        if action == "mood_shame_blame":
            # 面板上直接改"羞耻满时给鱼之心加多少责怪"（存 state，覆盖配置）
            if body.get("reset"):
                tuning.clear(self.state, "mood", "shame_blame")
                self._save()
                value = self.settings.float("mood.shame_blame", 0.0, 100.0)
                return f"羞耻满时责怪已改回跟随配置（+{value:.1f}）"
            if body.get("value") is not None:
                value = _clamp_amount(body.get("value"), 0.0, 100.0, 0.0)
            else:
                current = tuning.get(self.state, "mood", "shame_blame",
                                     self.settings.float("mood.shame_blame", 0.0, 100.0))
                value = _clamp_amount(current + _clamp_amount(body.get("delta"), -100.0, 100.0, 0.0),
                                      0.0, 100.0, 0.0)
            tuning.set_value(self.state, "mood", "shame_blame", round(value, 2))
            self._save()
            if value <= 0:
                return "羞耻满时不再加鱼之心责怪（0）"
            return f"羞耻满时给鱼之心加责怪 +{value:.1f}"
        if action == "mood_apology":
            # 面板「道歉」：帮鱼之心把责怪降一点（每次 mood.apology_blame）
            amount = self.settings.float("mood.apology_blame", 0.0, 100.0)
            if amount <= 0:
                return "没设置每次降多少（配置 mood.apology_blame）"
            try:
                result = boost.boost_fish_blame(self.context, self.settings, -amount)
            except Exception as error:
                logger.warning("[受孕] 降鱼之心责怪失败：%s", error)
                result = {"ok": False, "reason": str(error)}
            if not result.get("ok"):
                return f"没降下来：{result.get('reason') or '鱼之心不可用'}"
            self._save()
            return (f"鱼之心的责怪 {result['before']:.1f} → {result['after']:.1f}"
                    f"（−{abs(result['added']):.1f}）")
        if action in ("mood_adjust", "mood_comfort"):
            if not self.settings.bool("mood.enabled"):
                return "日常情绪关着（配置 mood.enabled）"
            if action == "mood_comfort":
                kind = str(body.get("kind") or "安慰")
                result = self._comfort(kind, "面板")
                return (f"{result['kind']}：羞耻度 {result['shame']:.0f}"
                        f"（{result['shame_delta']:+.0f}）、欲望度 {result['desire']:.0f}"
                        f"（{result['desire_delta']:+.0f}）")
            key = str(body.get("mood") or body.get("key") or "shame").strip().lower()
            if key not in mood.MOOD_KEYS:
                return "没有这条情绪（desire / shame）"
            if body.get("value") is not None:
                value = mood.adjust(self.state, self.settings, key, value=body.get("value"))
            else:
                delta = _clamp_amount(body.get("delta"), -100.0, 100.0, 5.0)
                value = mood.adjust(self.state, self.settings, key, delta=delta)
            self._save()
            label = mood.MOOD_LABELS[key]
            return (f"{label} → {value:.0f}"
                    f"（{mood.stage_title(key, mood.level_of(value))}）")
        if action in ("mood_prompt_save", "mood_prompt_reset"):
            key = str(body.get("mood") or body.get("key") or "").strip().lower()
            if key and key not in mood.MOOD_KEYS:
                return "没有这条情绪（desire / shame）"
            label = mood.MOOD_LABELS.get(key, "日常情绪")
            if action == "mood_prompt_reset":
                if key and body.get("level") is not None:
                    level = int(_clamp_amount(body.get("level"), 1, 4, 1))
                    cleared = mood.reset_prompts(self.state, key, level=level)
                    self._save()
                    return (f"{label} {mood.stage_title(key, level)} 已恢复内置默认" if cleared
                            else f"{label} 那一段本来就是默认")
                cleared = mood.reset_prompts(self.state, key or None)
                self._save()
                return (f"{label} 的四段提示词已恢复内置默认（{cleared} 条）" if key
                        else f"欲望度/羞耻度的提示词都已恢复内置默认（{cleared} 条）")
            texts = body.get("texts")
            if isinstance(texts, (list, tuple)):
                values = mood.set_prompts(self.state, key, texts)
                self._save()
                return f"{label} 的四段提示词已保存（共 {sum(len(v) for v in values)} 字）"
            level = int(_clamp_amount(body.get("level"), 1, 4, 1))
            value = mood.set_prompt(self.state, key, level, str(body.get("text") or ""))
            self._save()
            return (f"{label} {mood.stage_title(key, level)} 的提示词已保存（{len(value)} 字）"
                    if value else f"{label} {mood.stage_title(key, level)} 已恢复内置默认")
        if action == "uterus_overflow_toggle":
            value = body.get("enabled")
            new = fill.set_overflow_enabled(
                self.state, self.settings, None if value is None else bool(value))
            self._persist_config_value("ejaculation.uterus_overflow_enabled", new)
            self._save()
            return f"子宫溢出现在{'开' if new else '关'}（阈值 {fill.overflow_at(self.state, self.settings) * 100:.0f}%）"
        if action == "uterus_after_leak_toggle":
            value = body.get("enabled")
            new = fill.set_after_leak_enabled(
                self.state, self.settings, None if value is None else bool(value))
            self._persist_config_value("ejaculation.uterus_after_leak_enabled", new)
            self._save()
            return (f"活动结束后的漏出{'开' if new else '关'}"
                    f"（{fill.after_leak_per_hour(self.state, self.settings):.0f} ml/小时，"
                    f"漏到 {fill.after_leak_until(self.state, self.settings):.0f}% 就停）")
        if action == "succubus_tail_toggle":
            current = succubus.tail_enabled(self.state, self.settings)
            value = body.get("enabled")
            new = succubus.set_tail(
                self.state, self.settings,
                (not current) if value is None else bool(value))
            self._persist_config_value("succubus.tail_enabled", new)
            self._save()
            return (f"魅魔尾巴：{'开' if new else '关'}"
                    + (f"（尾巴按魅魔尾巴算，敏感度 ×{self.settings.float('succubus.tail_sensitivity_scale', 1.0, 5.0):.2f}）"
                       if new else ""))
        if action in ("fill_prompt_save", "fill_prompt_reset"):
            kind = str(body.get("kind") or body.get("key") or "").strip().lower()
            if kind not in ("level", "overflow"):
                return "没有这一栏（level / overflow）"
            label = "子宫充盈" if kind == "level" else "子宫溢出"
            if action == "fill_prompt_reset":
                if body.get("level") is not None:
                    level = int(_clamp_amount(body.get("level"), 1, 4, 1))
                    cleared = fill.reset_prompts(self.state, kind, level=level)
                    self._save()
                    return (f"{label} 第{level}段 已恢复内置默认" if cleared
                            else f"{label} 那一段本来就是默认")
                cleared = fill.reset_prompts(self.state, kind)
                self._save()
                return f"{label} 的提示词已恢复内置默认（{cleared} 组）"
            texts = body.get("texts")
            if isinstance(texts, (list, tuple)):
                values = fill.set_prompts(self.state, kind, texts)
                self._save()
                return f"{label} 的提示词已保存（共 {sum(len(v) for v in values)} 字）"
            level = int(_clamp_amount(body.get("level"), 1, 4, 1))
            value = fill.set_prompt(self.state, kind, level, str(body.get("text") or ""))
            self._save()
            return (f"{label} 第{level}段 的提示词已保存（{len(value)} 字）"
                    if value else f"{label} 第{level}段 已恢复内置默认")
        if action == "special_rotate_toggle":
            value = body.get("enabled")
            current = special.rotate_on_timer(self.state, self.settings)
            new = special.set_rotate(self.state, self.settings,
                                     (not current) if value is None else bool(value))
            self._save()
            return ("到点会自动换一处：开" if new else "到点自动换：关（只在被碰/手动换时才变）")
        if action == "surprise_message_save":
            value = surprise.set_message(self.state, str(body.get("text") or ""))
            self._save()
            if value:
                return f"主动消息已保存：{value[:40]}"
            return "主动消息已清空（回到内置短句）"
        if action in ("swallow_collect", "swallow_swallow"):
            if action == "swallow_collect":
                info = swallow.collect(self.state, self.settings,
                                       in_mouth=bool(body.get("in_mouth")))
            else:
                info = swallow.swallow(self.state, self.settings)
            self._save()
            if not info.get("ok"):
                return f"不行：{info.get('reason') or ''}"
            if info.get("line"):
                self.state["swallow_event_note"] = {
                    "at": util.now_ts(), "line": info["line"]}
                self._save()
            self._surprise_note("swallow")
            return ("收集好了" if action == "swallow_collect" else "咽下去了") + \
                f"（快感 +{info['pleasure']:.0f}）"
        if action == "unbirth_body":
            try:
                height = util.clamp(float(body.get("height_cm") or 170), 50.0, 250.0)
                weight = util.clamp(float(body.get("weight_kg") or 60), 20.0, 300.0)
            except (TypeError, ValueError):
                return "数值不对"
            self.state["user_body"] = {"height_cm": round(height, 1),
                                       "weight_kg": round(weight, 1)}
            self._persist_config_value("unbirth.user_height", round(height, 1))
            self._persist_config_value("unbirth.user_weight", round(weight, 1))
            self._save()
            return f"身高体重已设为 {height:.0f}cm / {weight:.0f}kg"
        if action == "zone_keywords_save_all":
            texts = body.get("texts")
            if not isinstance(texts, dict):
                return "没有收到关键词"
            box = self.state.get("zone_keywords")
            if not isinstance(box, dict):
                box = {}
                self.state["zone_keywords"] = box
            saved = 0
            for zone, value in texts.items():
                zone = intimacy.normalize_zone(zone)
                if not zone:
                    continue
                raw = str(value or "")
                for mark in ("，", "、", "；", ";", "|", "/"):
                    raw = raw.replace(mark, ",")
                words = []
                for part in raw.split(","):
                    word = part.strip()
                    if word and word not in words:
                        words.append(word)
                if words:
                    box[zone] = words[:40]
                    saved += 1
                else:
                    box.pop(zone, None)
            self._save()
            return f"部位关键词已保存（{saved} 个部位）"
        if action == "desire_set":
            feature = str(body.get("feature") or "")
            try:
                value = desire.set_strategy(self.state, feature, str(body.get("value") or ""))
            except ValueError as error:
                return str(error)
            self._save()
            return f"{desire.LABELS.get(feature, feature)}：欲望来源改成「{desire.STRATEGY_LABELS.get(value, value)}」"
        if action == "zone_keywords_save":
            zone = intimacy.normalize_zone(body.get("zone") or "")
            if not zone:
                return "没有这个敏感点"
            raw = str(body.get("text") or "")
            for mark in ("，", "、", "；", ";", "|", "/"):
                raw = raw.replace(mark, ",")
            words = []
            for part in raw.split(","):
                word = part.strip()
                if word and word not in words:
                    words.append(word)
            box = self.state.get("zone_keywords")
            if not isinstance(box, dict):
                box = {}
                self.state["zone_keywords"] = box
            if words:
                box[zone] = words[:40]
            else:
                box.pop(zone, None)
            self._save()
            return f"{intimacy.ZONE_LABELS.get(zone, zone)}：关键词已保存（{len(words)} 个）"
        if action == "unbirth_keywords_save":
            raw = str(body.get("text") or "")
            for mark in ("，", "、", "；", ";", "|", "/"):
                raw = raw.replace(mark, ",")
            words = [part.strip() for part in raw.split(",") if part.strip()]
            self.state["unbirth_resist_keywords"] = words[:30]
            self._save()
            return f"逆着来关键词已保存（{len(words)} 个）"
        if action == "unbirth_grow":
            info = unbirth.grow(self.state, self.settings)
            self._save()
            if not info.get("ok"):
                return f"不行：{info.get('reason') or ''}"
            extra = f"（{info['note']}）" if info.get("note") else ""
            hymen = info.get("hymen") or {}
            if hymen.get("line"):
                extra += "；" + hymen["line"]
            return (f"变大了：比例 {info['ratio']:.2f}，体积 {info['volume_ml']:.0f}ml"
                    f"（上限 {info['max_ratio']:.2f}）{extra}")
        if action == "pad_toy_reinsert":
            row = menstrual.data(self.state)
            saved = row.get("change_toy")
            if not menstrual.changing(self.state) or not isinstance(saved, dict):
                return "现在没有取出来的玩具可以放回去"
            info = toys.apply_toy(self.state, self.settings,
                                  str(saved.get("key") or ""),
                                  util.safe_int(saved.get("intensity"), 2),
                                  place=str(saved.get("place") or ""))
            row["change_toy"] = None
            self.state["menstrual_note"] = {
                "at": util.now_ts(),
                "line": prompts.text(self.state, "clothing", "pad_toy_reinsert")}
            self._save()
            return self.state["menstrual_note"]["line"] or "放回去了"
        if action == "pad_unbirth_exit":
            if not menstrual.changing(self.state) or not unbirth.data(self.state).get("inside"):
                return "现在没有可以退出来的情况"
            info = unbirth.exit(self.state, self.settings)
            self.state["menstrual_note"] = {
                "at": util.now_ts(),
                "line": prompts.text(self.state, "clothing", "unbirth_exit_pad")}
            self._save()
            return self.state["menstrual_note"]["line"] or (info.get("line") or "退出来了")
        if action == "menstrual_settings_save":
            values = body.get("settings")
            if not isinstance(values, dict):
                return "设置格式不对"
            notice = str(values.get("notice_text") or "").strip()
            if notice:
                self.state["menstrual_notice_prompt"] = notice[:400]
            else:
                self.state.pop("menstrual_notice_prompt", None)
            self._persist_config_value("menstrual.flow_ml_per_hour",
                                       util.clamp(util.safe_float(values.get("flow_ml_per_hour"), 4), 0, 200))
            self._persist_config_value("menstrual.flow_jitter",
                                       util.clamp(util.safe_float(values.get("flow_jitter"), 0.35), 0, 1))
            self._persist_config_value("menstrual.capacity_ml",
                                       util.clamp(util.safe_float(values.get("capacity_ml"), 60), 1, 500))
            self._persist_config_value("menstrual.drain_ml_per_hour",
                                       util.clamp(util.safe_float(values.get("drain_ml_per_hour"), 8), 0, 200))
            self._persist_config_value("menstrual.pad_notice_chance",
                                       util.clamp(util.safe_float(values.get("pad_notice_chance"), 100), 0, 100))
            self._persist_config_value("menstrual.pad_warn_minutes",
                                       int(util.clamp(util.safe_float(values.get("pad_warn_minutes"), 2), 0, 60)))
            self._persist_config_value("menstrual.pad_change_minutes",
                                       int(util.clamp(util.safe_float(values.get("pad_change_minutes"), 2), 0, 60)))
            self._persist_config_value("menstrual.change_at_percent",
                                       util.clamp(util.safe_float(values.get("change_at_percent"), 80), 1, 100))
            self._persist_config_value("menstrual.change_min_minutes",
                                       int(util.clamp(util.safe_float(values.get("change_min_minutes"), 30), 1, 240)))
            self._persist_config_value("menstrual.pad_auto_choose",
                                       bool(values.get("pad_auto_choose")))
            models = values.get("pad_models")
            if isinstance(models, dict):
                self._persist_config_value("menstrual.pad_models", {
                    key: util.clamp(util.safe_float(models.get(key), 20), 1, 500)
                    for key in ("liner", "regular", "night", "pants")})
            self._save()
            return "卫生巾设置已保存"
        if action == "pad_change":
            if sleep_inside.active(self.state):
                return "他现在还在里面睡着，没法换卫生巾"
            changed = menstrual.change_pad(self.state, self.settings)
            if not changed.get("ok"):
                return f"换不了：{changed.get('reason')}"
            self._save()
            return changed.get("line") or "换好了"
        if action == "cycle_prompts_toggle":
            current = self.settings.bool("cycle.prompts_enabled")
            self._persist_config_value("cycle.prompts_enabled", not current)
            self._save()
            return f"生理期提示词：{'关' if current else '开'}"
        if action == "children_set_care":
            mode = str(body.get("mode") or "family")
            if mode not in ("self", "family", "nanny", "adoption", "background"):
                return "不认识的去向"
            self._persist_config_value("children.care_mode", mode)
            self._save()
            return "出生后去向已保存"
        if action == "children_interrupt_toggle":
            current = self.settings.bool("children.intimacy_interrupt_enabled")
            self._persist_config_value("children.intimacy_interrupt_enabled", not current)
            self._save()
            return f"自己带时打断：{'关' if current else '开'}"
        if action == "sleep_inside_keywords_save":
            words = body.get("keywords")
            if not isinstance(words, dict):
                return "关键词格式不对"
            clean = {}
            for mode in sleep_inside.MODES:
                values = words.get(mode) or []
                if isinstance(values, str):
                    values = values.replace("，", ",").split(",")
                clean[mode] = [str(w).strip() for w in values if str(w).strip()][:20]
            self.state["sleep_inside_keywords"] = clean
            self._persist_config_value("sleep_inside.keywords", clean)
            self._save()
            return "插入入睡关键词已保存"
        if action in ("sleep_inside_ask", "sleep_inside_accept",
                      "sleep_inside_end", "sleep_inside_move"):
            if action == "sleep_inside_ask":
                info = sleep_inside.ask(self.state, self.settings,
                                        str(body.get("mode") or "vagina"))
                if info.get("ok"):
                    state_mod.append_log(self.state, "sleep_inside",
                                         f"询问能否插在{info.get('mode')}里睡")
            elif action == "sleep_inside_accept":
                info = sleep_inside.accept(self.state, self.settings)
                if info.get("ok"):
                    state_mod.append_log(self.state, "sleep_inside", "她答应了插入入睡")
            elif action == "sleep_inside_end":
                info = sleep_inside.end(self.state, self.settings)
            else:
                info = sleep_inside.move(
                    self.state, self.settings, deep=bool(body.get("deep")))
            if info.get("ok"):
                self._save()
            return info.get("line") or info.get("reason") or "好了"
        if action in ("unbirth_shrink", "unbirth_restore", "unbirth_enter",
                      "unbirth_exit", "unbirth_birth"):
            if action == "unbirth_shrink":
                info = unbirth.shrink(self.state, self.settings, body.get("ratio"))
                if info.get("ok"):
                    self._surprise_note("unbirth")
            elif action == "unbirth_restore":
                info = unbirth.restore(self.state, self.settings)
            elif action == "unbirth_enter":
                info = unbirth.enter(
                    self.state, self.settings,
                    hymen_mode=str(body.get("hymen_mode") or "pass"),
                    location=str(body.get("location") or "uterus"))
                if info.get("ok"):
                    self._surprise_note("unbirth")
            elif action == "unbirth_exit":
                info = unbirth.exit(
                self.state, self.settings,
                hymen_mode=str(body.get("hymen_mode") or "pass"))
            else:
                info = unbirth.birth_out(
                    self.state, self.settings, resist=bool(body.get("resist")),
                    hymen_mode=str(body.get("hymen_mode") or "pass"))
            self._save()
            if not info.get("ok"):
                return f"不行：{info.get('reason') or ''}"
            if action == "unbirth_shrink":
                return f"缩小到 {info['ratio']:.2f}（{info['volume_ml']:.0f}ml）"
            if action == "unbirth_enter":
                return f"钻进去了（{info['expansion_label']}）"
            if action == "unbirth_birth":
                if not info.get("ok"):
                    return info.get("line") or info.get("reason") or "现在生不出来"
                if info.get("failed"):
                    return f"没生出来：{info.get('line') or '太紧了'}"
                done = bool(info.get("done"))
                return f"生出第 {info['step']}/{info['steps']} 步" + ("（完成了）" if done else "")
            return {"unbirth_restore": "还原了", "unbirth_exit": "退出来了"}.get(action, "好了")
        if action in ("outfit_set", "outfit_remove"):
            slot = str(body.get("slot") or "")
            key = str(body.get("key") or "") if action == "outfit_set" else ""
            label = clothing.label_of(key) if key else clothing.SLOT_LABELS.get(slot, slot)
            items = [(slot, key)]
            if key in ("pajamas", "nightgown"):
                items.append(("feet", "slippers"))
            return self._begin_outfit_change(
                items, label, immediate=bool(body.get("immediate")),
                undress=action == "outfit_remove")
        if action == "outfit_refresh":
            slot = str(body.get("slot") or "")
            row = clothing.worn(self.state, self.settings)
            item = row.get(slot)
            if not item:
                return "换不了：这一格现在没穿衣服"
            label = clothing.label_of(str(item.get("key") or "")) or \
                clothing.SLOT_LABELS.get(slot, slot)
            return self._begin_outfit_change(
                [(slot, str(item.get("key") or ""))], label,
                refresh_slots=[slot])
        if action == "sleepwear_choose":
            return self._choose_sleepwear(str(body.get("style") or ""))
        if action == "birth_comfort":
            info = birth.relief_pain(self.state, self.settings)
            self._save()
            if not info.get("ok"):
                return "现在不用安抚（没在产程里，或者刚安抚过）"
            state_mod.append_log(self.state, "birth",
                                 f"安抚：产痛 -{info['relief']:.0f} → {info['pain']:.0f}")
            return f"安抚了（产痛 {info['pain']:.0f}）"
        if action == "birth_step":
            info = self._birth_tick(notify=False)
            return f"推进到：{info.get('label') or birth.stage_of(self.state)}"
        if action == "combo_step":
            try:
                delta = int(body.get("delta") or 0)
            except (TypeError, ValueError):
                delta = 0
            value = max(1, min(20, self._combo_limit() + delta))
            tuning.set_value(self.state, "combo", "overstim_after", value)
            self._save()
            return f"连续高潮上限设为 {value}"
        if action == "config_sync_push":
            tuning_rows = self.state.get("tuning")
            if isinstance(tuning_rows, dict):
                for section, rows in tuning_rows.items():
                    if not isinstance(rows, dict):
                        continue
                    box = self.settings.config.setdefault(section, {})
                    if isinstance(box, dict):
                        box.update(rows)
            if isinstance(self.state.get("unbirth_enabled"), bool):
                self.settings.config.setdefault("unbirth", {})[
                    "enabled"] = bool(self.state["unbirth_enabled"])
            if isinstance(self.state.get("unbirth_request_enabled"), bool):
                self.settings.config.setdefault("unbirth", {})[
                    "request_enabled"] = bool(self.state["unbirth_request_enabled"])
            if isinstance(self.state.get("toy_self_use_enabled"), bool):
                self.settings.config.setdefault("toys", {})[
                    "self_use_enabled"] = bool(self.state["toy_self_use_enabled"])
            if isinstance(self.state.get("pill_proactive_enabled"), bool):
                self.settings.config.setdefault("contraception", {})[
                    "pill_proactive_enabled"] = bool(self.state["pill_proactive_enabled"])
            if isinstance(self.state.get("pill_blame_enabled"), bool):
                self.settings.config.setdefault("contraception", {})[
                    "pill_blame_enabled"] = bool(self.state["pill_blame_enabled"])
            try:
                path = CONFIG_DIR / f"{PLUGIN_NAME}_config.json"
                path.write_text(json.dumps(self.settings.config, ensure_ascii=False, indent=2)
                                + "\n", encoding="utf-8-sig")
            except Exception as error:
                logger.warning("[受孕] 写回配置失败：%s", error)
                return f"写回配置失败：{error}"
            self._save()
            return "面板值已写回配置页"
        if action == "tuning_clear_all":
            self.state["tuning"] = {}
            for key in ("unbirth_enabled", "toy_self_use_enabled",
                        "pill_proactive_enabled", "pill_blame_enabled",
                        "unbirth_request_enabled"):
                self.state.pop(key, None)
            self._save()
            return "已清除面板覆盖，全部跟随配置"
        if action == "contraception_keywords_save":
            for key in ("pill_cancel_keywords", "pill_take_keywords",
                        "pill_inside_promise_keywords"):
                words = body.get(key)
                if isinstance(words, str):
                    words = [w.strip() for w in words.replace("，", ",").split(",") if w.strip()]
                if isinstance(words, list):
                    clean = [str(w).strip() for w in words if str(w).strip()][:30]
                    self.settings.config.setdefault("contraception", {})[key] = clean
                    self._persist_config_value(("contraception", key), clean)
            self._save()
            return "避孕药关键词已保存"
        if action == "clothing_keywords_save":
            clothing.set_keyword_words(
                self.state, body.get("remove"), body.get("wear"))
            self._save()
            return "衣装关键词已保存"
        if action == "night_stay_toggle":
            which = "fish" if str(body.get("key") or "") == "fish" else "pc"
            key = f"night_raid.{which}_stay_up_enabled"
            current = self.settings.bool(key)
            self._persist_config_value(key, not current)
            self._save()
            return f"{'鱼之心' if which == 'fish' else 'PC'} 熬夜条件：{'关' if current else '开'}"
        if action == "asmr_keywords_save":
            words = body.get("text")
            if isinstance(words, str):
                words = [w.strip() for w in words.replace("，", ",").split(",") if w.strip()]
            if isinstance(words, list):
                clean = [str(w).strip() for w in words if str(w).strip()][:30]
                self.state["asmr_known_keywords"] = clean
                self._persist_config_value("asmr.known_keywords", clean)
                self._save()
                return "助眠关键词已保存"
            return "关键词格式不对"
        if action == "asmr_toggle":
            enabled = not asmr.enabled(self.state, self.settings)
            self.state["asmr_enabled"] = enabled
            self._persist_config_value("asmr.enabled", enabled)
            self._save()
            return f"ASMR 助眠：{'开' if enabled else '关'}"
        if action == "asmr_start":
            info = asmr.start(self.state, self.settings,
                              minutes=body.get("minutes"))
            if info.get("ok"):
                self.state["asmr_known"] = True
                self.state["asmr_done_night"] = self._asmr_night_key()
                self.state.pop("asmr_pc_noted", None)
                self._asmr_note(info.get("line") or "")
                self._sleep_note()
                self._asmr_allow_speech()
                state_mod.append_log(self.state, "asmr", "开始助眠")
                self._save()
                return f"助眠开始（{info['minutes']} 分钟）"
            return f"不行：{info.get('reason') or ''}"
        if action == "asmr_extend":
            info = asmr.extend(self.state, self.settings, minutes=body.get("minutes"))
            if info.get("ok"):
                self._asmr_note(info.get("line") or "")
                self._save()
                return f"续了 {info['minutes']} 分钟"
            return f"不行：{info.get('reason') or ''}"
        if action == "asmr_end":
            info = asmr.finish(self.state, self.settings)
            if info.get("ok"):
                self._asmr_note(info.get("line") or "")
                self._asmr_pc_note("刚结束一段 ASMR 助眠，这一觉会睡得更沉，醒来精力恢复得更多，但不超过原来的 100 上限。")
                try:
                    sleepy.tick(self.state, self.settings, in_event=False)
                except Exception as error:
                    logger.warning("[受孕] 结束助眠睡眠例外失败：%s", error)
                pc_state.clear_night_raid_bypass()
                self._save()
                return ("助眠结束：她睡着了" if info.get("slept")
                        else "助眠结束：她还醒着")
            return f"不行：{info.get('reason') or ''}"
        if action == "asmr_do":
            key = str(body.get("key") or "")
            info = asmr.action(self.state, self.settings, key)
            if not info.get("ok"):
                return f"不行：{info.get('reason') or ''}"
            if endurance.enabled(self.settings) and \
                    endurance.is_full(self.state, self.settings) and \
                    util.safe_float(self.state.get("pleasure"), 0.0) >= \
                    state_mod.effective_threshold(self.state, self.settings):
                self.state["last_touch"] = {
                    "zone": "ear", "method": "asmr", "at": util.now_ts()}
                asmr.clear_session_relief(self.state, now=util.now_ts())
                orgasm = self._record_orgasm("ASMR", open_scene=False)
                if orgasm and not orgasm.get("refused"):
                    info["orgasm"] = orgasm
            if info.get("line"):
                self._asmr_note(info["line"])
            if info.get("intimacy") or info.get("attachment"):
                try:
                    boost.boost_fish(self.context, self.settings,
                                     intimacy=float(info.get("intimacy") or 0.0),
                                     attachment=float(info.get("attachment") or 0.0))
                except Exception as error:
                    logger.warning("[受孕] 助眠写鱼之心失败：%s", error)
            if info.get("relief") and not self.state.get("asmr_pc_noted"):
                self._asmr_pc_note("刚被 ASMR 助眠过，睡前很放松，睡眠质量提高；睡醒后精力恢复得更多，但不超过原来的 100 上限。")
                self.state["asmr_pc_noted"] = True
            self._sleep_note()
            self._asmr_allow_speech()
            self._save()
            return info.get("line") or "助眠动作完成"
        if action == "asmr_request_toggle":
            enabled = not self.settings.bool("asmr.request_enabled")
            self._persist_config_value("asmr.request_enabled", enabled)
            self._save()
            return f"她主动请求助眠：{'开' if enabled else '关'}"
        if action == "pill_blame_toggle":
            enabled = not self._pill_blame_enabled()
            self.state["pill_blame_enabled"] = enabled
            self._persist_config_value("contraception.pill_blame_enabled", enabled)
            self._save()
            return f"拒绝吃药后被内射加责备：{'开' if enabled else '关'}"
        if action == "pill_blame_once_toggle":
            enabled = not self.settings.bool("contraception.pill_blame_once")
            self._persist_config_value("contraception.pill_blame_once", enabled)
            self._save()
            return f"拒绝后内射加责备且埋怨只进行一次：{'开' if enabled else '关'}"
        if action == "pill_proactive_toggle":
            enabled = not self._pill_proactive_enabled()
            self.state["pill_proactive_enabled"] = enabled
            self._persist_config_value("contraception.pill_proactive_enabled", enabled)
            self._save()
            return f"她主动吃避孕药：{'开' if enabled else '关'}"
        if action == "unbirth_request_toggle":
            enabled = not unbirth.request_enabled(self.state, self.settings)
            self.state["unbirth_request_enabled"] = enabled
            self._persist_config_value("unbirth.request_enabled", enabled)
            self._save()
            return f"她主动请求让你进入：{'开' if enabled else '关'}"
        if action == "toys_self_toggle":
            enabled = not self._toy_self_enabled()
            self.state["toy_self_use_enabled"] = enabled
            self._persist_config_value("toys.self_use_enabled", enabled)
            self._save()
            return f"她主动用玩具：{'开' if enabled else '关'}"
        if action == "condom_help_remove":
            info = condom.help_remove(self.state, self.settings)
            self._save()
            if not info.get("ok"):
                return f"不行：{info.get('reason') or ''}"
            state_mod.append_log(self.state, "condom", "她帮忙脱下避孕套")
            return "她帮忙脱掉了" + (f"：{info['line']}" if info.get("line") else "")
        if action == "condom_remove":
            info = condom.remove(self.state, self.settings)
            self._save()
            if not info.get("ok"):
                return f"不行：{info.get('reason') or ''}"
            state_mod.append_log(self.state, "condom", "脱下避孕套")
            return "脱掉了" + (f"：{info['line']}" if info.get("line") else "")
        if action in ("condom_wear", "condom_renew", "condom_help"):
            if action == "condom_wear":
                info = condom.wear(self.state, self.settings)
            elif action == "condom_renew":
                info = condom.renew(self.state, self.settings)
            else:
                info = condom.help_wear(self.state, self.settings)
            self._save()
            if not info.get("ok"):
                return f"不行：{info.get('reason') or ''}"
            label = {"condom_wear": "戴上避孕套", "condom_renew": "换了新的",
                     "condom_help": "她帮忙戴上"}[action]
            state_mod.append_log(self.state, "condom", label)
            return label + ("（她小声问要不要她帮）" if info.get("asked") else "")
        if action == "birth_keywords_save":
            raw = str(body.get("text") or "")
            for mark in ("，", "、", "；", ";", "|", "/"):
                raw = raw.replace(mark, ",")
            words = [part.strip() for part in raw.split(",") if part.strip()]
            self.state["birth_comfort_keywords"] = words[:20]
            self._save()
            return f"安抚关键词已保存（{len(words)} 个）"
        if action == "unbirth_toggle":
            enabled = bool(body.get("enabled"))
            self.state["unbirth_enabled"] = enabled
            self._persist_config_value("unbirth.enabled", enabled)
            self._save()
            return "Unbirth：开" if enabled else "Unbirth：关"
        if action == "swallow_auto_toggle":
            enabled = bool(body.get("enabled"))
            self.state["swallow_auto_enabled"] = enabled
            self._save()
            return "吞精自主选择：开" if enabled else "吞精自主选择：关"
        if action == "wetness_base_float_toggle":
            enabled = bool(body.get("enabled"))
            self.state["wetness_base_float_enabled"] = enabled
            self._save()
            return "基础湿润度浮动：开" if enabled else "基础湿润度浮动：关"
        if action == "lube_apply":
            part = str(body.get("part") or "")
            info = lube.apply(self.state, self.settings,
                              hand=bool(body.get("hand")), part=part)
            self._save()
            if not info.get("ok"):
                return f"用不了：{info.get('reason') or ''}"
            menstrual.add_pad_fluid(self.state, self.settings, "润滑",
                                    max(0.0, util.safe_float(info.get("added"), 0.0)) * 0.1)
            label = "手部" if info.get("hand") else (
                "乳房" if part == "breast" else "乳头" if part == "nipple"
                else "阴茎" if part == "penis" else "阴道")
            state_mod.append_log(self.state, "lube",
                                 f"{label}润滑（湿润 +{info['added']}）")
            return ("手上抹好了" if info.get("hand") else f"{label}抹好了") + \
                f"（湿润 +{info['added']:.0f}）"
        if action in ("uterus_enter", "uterus_exit"):
            if action == "uterus_enter":
                force = bool(body.get("force"))
                info = uterus_insert.enter(self.state, self.settings, force=force)
                self._save()
                if not info.get("ok"):
                    return f"进不去：{info.get('reason') or ''}"
                self._surprise_note("insert")
                state_mod.append_log(self.state, "uterus", f"插入子宫（痛感 {info['pain']}）")
                return f"进去了（痛感 {info['pain']:.0f}，{'强行' if info['force'] else '正常'}）"
            info = uterus_insert.exit(self.state, self.settings)
            self._save()
            if not info.get("ok"):
                return f"退不出来：{info.get('reason') or ''}"
            return "退出子宫" + ("（还是撑着）" if info.get("still_expanded") else "（缩回去了）")
        if action in ("behavior_prompt_save", "behavior_prompt_reset"):
            if action == "behavior_prompt_save":
                group = str(body.get("group") or "")
                texts = body.get("texts")
                if not isinstance(texts, dict):
                    return "保存失败：没有内容"
                changed = prompts.set_many(self.state, group, texts)
                self._save()
                return f"行为提示词已保存（{changed} 段）"
            group = str(body.get("group") or "") or None
            key = body.get("key")
            count = prompts.reset(self.state, group, str(key) if key else None)
            self._save()
            return f"行为提示词已恢复默认（{count} 段）"
        if action == "surprise_toggle":
            current = surprise.allowed(self.state, self.settings)
            new = (not current) if body.get("enabled") is None else bool(body.get("enabled"))
            self.state["surprise_enabled_override"] = new
            self._persist_config_value("surprise.enabled", new)
            self._save()
            return "突然被弄的反应：" + ("开" if new else "关")
        if action in ("surprise_prompt_save", "surprise_prompt_reset"):
            if action == "surprise_prompt_reset":
                if body.get("stage"):
                    stage_key = str(body.get("stage") or "")
                    cleared = surprise.reset_prompts(self.state, stage_key)
                    self._save()
                    return f"突然被弄·{stage_key} 提示词已恢复默认" if cleared \
                        else "本来就是默认"
                surprise.reset_prompts(self.state)
                self._save()
                return "突然被弄提示词已恢复默认"
            stage_key = str(body.get("stage") or "shock")
            value = surprise.set_prompt(self.state, stage_key, str(body.get("text") or ""))
            self._save()
            return f"突然被弄·{stage_key} 提示词已保存（{len(value)} 字）"
        if action == "sleep_allow_toggle":
            current = sleepy.allowed(self.state, self.settings)
            new = (not current) if body.get("enabled") is None else bool(body.get("enabled"))
            self.state["sleep_allow_override"] = new
            self._persist_config_value("sleep.allow_speaking_in_activity", new)
            self._save()
            return "睡眠时段里允许她发言：" + ("开" if new else "关")
        if action == "wetness_fish_toggle":
            current = self._fish_write_on()
            new = (not current) if body.get("enabled") is None else bool(body.get("enabled"))
            self.state["wetness_fish_write"] = new
            self._persist_config_value("wetness.fish_write_enabled", new)
            self._save()
            return "湿润度同步鱼之心「欲」：" + ("开" if new else "关")
        if action == "special_reroll":
            special.data(self.state)["round"] = util.safe_int(
                special.data(self.state).get("round"), 0) + 1
            special.data(self.state)["at"] = 0.0
            info = special.current(self.state, self.settings)
            self._save()
            return f"特别敏感点换成了：{info.get('label') or '（没有可用部位）'}"
        if action == "endurance_reset":
            endurance.clear(self.state, self.settings)
            self._save()
            return "忍耐条已清空（长度回到基础）"
        if action in ("endurance_prompt_save", "endurance_prompt_reset"):
            if action == "endurance_prompt_reset":
                if body.get("level") is not None:
                    level = int(_clamp_amount(body.get("level"), 1, 4, 1))
                    cleared = endurance.reset_prompts(self.state, level=level)
                    self._save()
                    return (f"忍耐条 第{level}段 已恢复内置默认" if cleared
                            else f"忍耐条 第{level}段 本来就是默认")
                cleared = endurance.reset_prompts(self.state)
                self._save()
                return f"忍耐条提示词已恢复内置默认（{cleared}）"
            texts = body.get("texts")
            if isinstance(texts, (list, tuple)):
                values = endurance.set_prompts(self.state, texts)
                self._save()
                return f"忍耐条提示词已保存（共 {sum(len(v) for v in values)} 字）"
            level = int(_clamp_amount(body.get("level"), 1, 4, 1))
            value = endurance.set_prompt(self.state, level, str(body.get("text") or ""))
            self._save()
            return (f"忍耐条 第{level}段 的提示词已保存（{len(value)} 字）"
                    if value else f"忍耐条 第{level}段 已恢复内置默认")
        if action in ("wetness_prompt_save", "wetness_prompt_reset"):
            if action == "wetness_prompt_reset":
                if body.get("level") is not None:
                    level = int(_clamp_amount(body.get("level"), 1, 4, 1))
                    cleared = wetness.reset_prompts(self.state, level=level)
                    self._save()
                    return (f"湿润度 第{level}段 已恢复内置默认" if cleared
                            else f"湿润度 第{level}段 本来就是默认")
                cleared = wetness.reset_prompts(self.state)
                self._save()
                return f"湿润度提示词已恢复内置默认（{cleared}）"
            texts = body.get("texts")
            if isinstance(texts, (list, tuple)):
                values = wetness.set_prompts(self.state, texts)
                self._save()
                return f"湿润度提示词已保存（共 {sum(len(v) for v in values)} 字）"
            level = int(_clamp_amount(body.get("level"), 1, 4, 1))
            value = wetness.set_prompt(self.state, level, str(body.get("text") or ""))
            self._save()
            return (f"湿润度 第{level}段 的提示词已保存（{len(value)} 字）"
                    if value else f"湿润度 第{level}段 已恢复内置默认")
        if action == "clear_log":
            self.state["log"] = []
            self._save()
            return "已清空最近事件"
        if action == "succubus_limit":
            current = succubus.limit(self.state, self.settings)
            delta = int(_clamp_amount(body.get("delta"), -100, 100, 0))
            value = max(0, min(100, current + delta))
            tuning.set_value(self.state, "succubus", "daily_limit", value)
            self._save()
            return f"每日榨取上限：{'不限' if value == 0 else value}"
        if action == "succubus_toggle":
            current = succubus.enabled(self.state, self.settings)
            enabled = succubus.set_enabled(self.state, self.settings, not current)
            state_mod.append_log(self.state, "succubus",
                                 f"面板{'开启' if enabled else '关闭'}魅魔")
            self._save()
            return f"魅魔已{'开启' if enabled else '关闭'}"
        if action == "tune":
            section = str(body.get("section") or "")
            key = str(body.get("key") or "")
            if body.get("reset"):
                tuning.clear(self.state, section, key)
                self._save()
                raw = tuning.raw(self.state, section, key, None)
                return ("已改回跟随配置" if raw is None
                        else f"已改回跟随配置（{raw:g}）")
            result = self._set_tuning(section, key, body.get("value"))
            if result.get("refused"):
                return f"未调整：{result['refused']}"
            if section and key:
                self._persist_config_value(self._config_path(section, key), result["value"])
            return f"已调到 {result['value']:g}"
        if action == "succubus_level":
            if body.get("level") is not None:
                result = self._succubus_set_level(value=body.get("level"))
            else:
                result = self._succubus_set_level(delta=_clamp_amount(body.get("delta"), -5, 5, 0))
            return f"淫纹等级 Lv.{result['level']}"
        if action == "succubus_willing":
            result = self._succubus_set_willing(body.get("willing"))
            return f"怀孕意愿：{result['label']}"
        if action == "hymen_blood_toggle":
            enabled = not body.hymen_blood_enabled(self.state, self.settings)
            self.state["hymen_blood_enabled"] = enabled
            self._persist_config_value("hymen.blood_enabled", enabled)
            self._save()
            return f"处子血：{'开' if enabled else '关'}"
        if action == "hymen_restore":
            self._restore_hymen("面板")
            return "处女膜已恢复完整"
        if action == "expel":
            result = self._expel_uterus("面板")
            if result.get("refused"):
                return f"未排出：{result['refused']}"
            if result.get("empty"):
                return "子宫里本来就是空的"
            return f"已排出 {result['before']:.1f} ml"
        if action == "pill":
            verb = str(body.get("mode") or "status")
            result = self._contraception_pill(verb, "面板")
            if result.get("refused"):
                return f"未记录：{result['refused']}"
            if result.get("status"):
                status = result["status"]
                left = status.get("pill_hours_left", 0)
                return f"避孕药：{'生效中，还剩 %.1f 小时' % left if left else '没吃'}"
            return "避孕药已吃" if verb in ("take", "吃") else "避孕药已停"
        if action == "condom":
            used = bool(body.get("enabled", True))
            result = self._contraception_condom(used, "面板")
            if result.get("refused"):
                return f"未记录：{result['refused']}"
            return "已戴上避孕套" if used else "已摘下避孕套"
        if action == "toy":
            toy = str(body.get("toy") or "bullet")
            intensity = _clamp_amount(body.get("intensity"), 1, 3, 2)
            place = str(body.get("place") or "")
            result = self._record_toy(toy, int(intensity), "面板", place=place)
            if result.get("refused"):
                return f"未记录：{result['refused']}"
            return (f"{result['label']}（{result['intensity_label']}·{result['place_label']}）："
                    f"快感 +{result['gain']:.0f}，现在 {result['value']:.0f}"
                    + self._toy_extra(result))
        if action == "toy_stop":
            toys.clear_toy(self.state)
            self._save()
            return "已把玩具收起来"
        if action == "edge":
            result = self._record_edge("面板")
            if result.get("refused"):
                return f"未记录：{result['refused']}"
            self._surprise_note("edge")
            return (f"寸止第 {result['stack']} 次：门槛 +{result['bonus']:.0f}，"
                    f"渴求 {result['craving']:.0f}%")
        if action == "ejaculate":
            mode = str(body.get("mode") or "").strip()
            if not mode:
                mode = "vagina" if bool(body.get("inside", True)) else "outside"
            result = self._record_ejaculation(mode, "面板")
            if result.get("refused"):
                return f"未记录：{result['refused']}"
            uterus = result.get("uterus") or {}
            tail = (f"，子宫 {uterus['ml']:.1f}/{uterus['capacity_effective']:.0f} ml"
                    + (f"，溢出来 {uterus['overflow']:.1f} ml" if uterus.get("overflow") else "")
                    if uterus else "")
            if result.get("pregnant") and not result.get("rolled"):
                return f"记下了。{result.get('reason')}"
            if intimacy.MODE_CONCEIVE.get(result.get("mode", ""), False):
                if result.get("hit"):
                    prog = pregnancy.progress(self.state)
                    return f"受孕命中，预产期 {prog['due_date'].isoformat()}{tail}"
                return f"这次没受孕（{result['p'].probability:.1f}%）{tail}"
            return f"记下了：{intimacy.MODE_LABELS.get(result.get('mode', ''), '')}，不会受孕{tail}"
        if action == "self_test_new_stick":
            self.state["last_self_test"] = {"result": "", "at": util.now_ts(),
                                            "text": "", "by": ""}
            self._save()
            return "换了一根新的验孕棒"
        if action == "self_test":
            if not self.settings.bool("self_test.enabled"):
                return "验孕功能已关闭"
            result = pregnancy.run_test(self.state, self.settings, by="user")
            state_mod.append_log(self.state, "pregnancy_test", f"验孕：{result['text']}")
            if result["pregnant"] and not pregnancy.knows(self.state):
                pregnancy.schedule_self_test(self.state, self.settings, delay_hours=(48, 120))
            self._save()
            return f"验孕结果：{result['text']}"
        if action == "consent":
            if bool(body.get("enabled", True)):
                hours = self.settings.float("adult_consent_hours", 0.0, 720.0)
                state_mod.grant_consent(self.state, hours)
                self._save()
                return f"已授权 {hours:.0f} 小时" if hours else "已长期授权"
            state_mod.clear_consent(self.state)
            self._save()
            return "已撤掉授权"
        if action == "scene":
            if bool(body.get("enabled", True)):
                self._touch_scene("面板")
                self._save()
                return f"进入场景（{self.settings.int('adult.scene_window_minutes', 1, 720)} 分钟）"
            state_mod.clear_scene(self.state)
            self._save()
            return "场景已结束"
        if action == "force_pregnant":
            if pregnancy.progress(self.state):
                return "已经在孕期了"
            if self.settings.bool("pregnancy.postpartum_no_conception"):
                stage = pregnancy.postpartum_stage(self.state, self.settings)
                if stage and stage.get("key") == "hard":
                    until = pregnancy.postpartum_until_text(self.state)
                    where = f"（大约到 {until}）" if until else ""
                    return f"她还在产后前 {stage['hard_days']} 天{where}，这段时间不会受孕"
            self._start_pregnancy(100.0, "面板")
            self._ensure_pc_cycle_state()
            prog = pregnancy.progress(self.state)
            return f"已置为受孕，预产期 {prog['due_date'].isoformat()}"
        if action == "reset":
            if not bool(body.get("confirm")):
                return "需要确认（confirm=true）"
            if pregnancy.is_pregnant(self.state):
                self._finish_pregnancy(reason="面板重置")
            else:
                pregnancy.clear_pregnancy(self.state)
                try:
                    pc_state.clear_pregnancy(self.settings)
                except Exception as error:
                    logger.warning("[受孕] 清除 PC 孕期状态失败：%s", error)
                if self.settings.bool("pregnancy.suppress_pc_cycle"):
                    pc_cycle.restore(self.settings)
            self.state["own_cycle"] = {"anchor_date": util.today().isoformat()}
            state_mod.clear_combo(self.state)
            self.state["pleasure"] = 0.0
            endurance.clear(self.state, self.settings)
            wetness.clear(self.state, self.settings)
            special.reset(self.state)
            # 顺手把子敏感度的进度和"溢出攒的加成"一起清掉
            intimacy.clear_zone_bonus(self.state)
            subzone.reset(self.state)
            self._save()
            self._cycle_cache = None
            return "已重置孕期、快感、忍耐条、特别敏感点、连续高潮与子敏感度（含溢出攒的加成），周期恢复"
        if action == "tick":
            self._tick()
            return "已刷新"
        return f"未知操作：{action}"

    # ================================================================ 命令

    def _owner_only(self, event) -> bool:
        if not self._owner_private(event):
            return False
        return True

    def _status_text(self, event=None) -> str:
        gender = self._refresh_gender(event, force=True)
        data = self._read_sources(force=True)
        cycle = self._cycle()
        gate_ok, gate_why = self._gate(data)
        prog = pregnancy.progress(self.state)
        pleasure = self._pleasure()
        cap = self.settings.float("pleasure.max", 1.0, 1000.0)
        session_orgasms = state_mod.session_orgasms(self.state, self.settings)
        day = self.state.get("day") or {}

        lines = ["【受孕插件状态】"]
        status = self._status_flags()
        status_line = f"状态：{status['main']['label']}"
        if status["chips"]:
            status_line += "（" + "、".join(chip["label"] for chip in status["chips"]) + "）"
        lines.append(status_line)
        lines += [
                 f"总开关：{'开' if self.settings.bool('enabled') else '关'}",
                 persona_mod.describe(gender),
                 f"成人层：{'可用' if gate_ok else '不可用'}（{gate_why}）"]
        if state_mod.consent_active(self.state):
            until = datetime.fromtimestamp(
                util.safe_float(self.state.get("adult_consent_until"), 0)).strftime("%m-%d %H:%M")
            lines.append(f"本插件临时授权：到 {until}")
        lines.extend(sources.describe_sources(data))
        lines.append(f"生理期：{cyclemodel.describe(cycle)}")
        in_scene, scene_why = self._scene_active(data)
        if in_scene:
            lines.append(f"场景：进行中（{scene_why}，本插件窗口还剩 "
                         f"{state_mod.scene_remaining(self.state, self.settings)} 分钟）")
        else:
            lines.append(f"场景：无（{scene_why}）—— 关键词识别只在场景里生效；"
                         f"要手动开场发 /受孕场景")

        if prog:
            stage = prog["stage"]
            lines.append(
                f"受孕状态：已怀孕 · 第 {prog['month']}/{prog['months']} 个月（第 {prog['week']} 周，"
                f"{stage['title']}"
                + (f"，{prog.get('fetuses', 1)} 胎" if int(prog.get("fetuses") or 1) > 1 else "")
                + "）")
            due_note = (f"（浮动 {prog['due_jitter_days']:+d} 天）"
                        if prog.get("due_jitter_days") else "")
            lines.append(f"受孕日：{prog['conceived_date'].isoformat()}｜预产期："
                         f"{prog['due_date'].isoformat()}{due_note}｜还有 {prog['days_left']} 天")
            known = "已验出/确认" if prog.get("known") else (
                "验出很浅的两条杠，还不敢确定" if prog.get("suspected") else "还不知道")
            told = "已告诉他" if prog.get("told") else "还没告诉他"
            lines.append(f"知情：{known}｜{told}")
            lines.append(f"生理期暂停：{'是' if prog.get('suppressed_pc_cycle') else '否（靠提示词兜底）'}"
                         f"｜{pc_cycle.describe(self.settings)}")
        elif pregnancy.postpartum_active(self.state):
            until = pregnancy.postpartum_until_text(self.state)
            where = f"，到 {until}" if until else ""
            stage = (pregnancy.postpartum_stage(self.state, self.settings)
                     if self.settings.bool("pregnancy.postpartum_no_conception") else None)
            if stage and stage.get("key") == "hard":
                extra = f"，前 {stage['hard_days']} 天绝对不受孕"
            elif stage and stage.get("key") == "low":
                extra = f"，恢复期低概率（×{stage['scale']:.2f}）"
            else:
                extra = ""
            lines.append(f"受孕状态：未怀孕（产后恢复期{where}{extra}）")
        else:
            lines.append("受孕状态：未怀孕")
        window = pregnancy.self_test_window(self.state)
        if window:
            when = datetime.fromtimestamp(util.safe_float(window.get("due_at"), 0)).strftime("%m-%d %H:%M")
            lines.append(f"验孕念头：{'现在就可以验' if window.get('ready') else f'约 {when} 之后'}")
        lines.append(pc_cycle.describe(self.settings))

        threshold = state_mod.effective_threshold(self.state, self.settings)
        tier = pregnancy.arousal_tier(pleasure)
        lines.append(
            f"快感：{pleasure:.1f}/{cap:.0f}（{tier['key']}，到 {threshold:.0f} 才算能高潮）"
            f"｜本次会话高潮 {session_orgasms} 次"
            f"（今日 {util.safe_int(day.get('orgasms'), 0)}，累计 "
            f"{util.safe_int(self.state.get('orgasms_total'), 0)}）")
        combo_count = state_mod.combo_count(self.state, self.settings)
        rest = state_mod.rest_remaining(self.state)
        if rest:
            lines.append(f"连续高潮：刚过头了（连续 {combo_count} 次，峰值 "
                         f"{state_mod.combo_peak(self.state)}）｜还要缓 {rest} 分钟，"
                         f"这段时间她会喊难受、想慢一点")
        else:
            lines.append(f"连续高潮：当前 {combo_count} 次（峰值 "
                         f"{state_mod.combo_peak(self.state)}，上限 "
                         f"{self._combo_limit()} 次）")
        lines.append(
            f"射精：今日 {util.safe_int(day.get('ejaculations'), 0)} 次｜累计 "
            f"{util.safe_int(self.state.get('ejaculations_total'), 0)} 次（阴道内 "
            f"{util.safe_int(self.state.get('ejaculations_inside_total'), 0)}）")

        if self.settings.bool("zones.enabled"):
            zone_rows = [row for row in intimacy.zones_payload(self.settings, self.state) if row["enabled"]]
            if zone_rows:
                lines.append("敏感点：" + "｜".join(
                    f"{row['label']} 开发{row['dev']}%/敏感×{row['sensitivity']:.2f}"
                    f"/+{row['gain']:.1f}" for row in zone_rows))
        lines.append(subzone.describe(self.state, self.settings, in_scene=in_scene))
        uterus = fill.volume(self.state, self.settings)
        toy_active = self._toy_payload()
        if toy_active:
            lines.append(f"玩具：{toy_active['label']}（{toy_active['intensity_label']}，"
                         f"还剩 {toy_active['remaining']} 分钟）")
        daily = self._daily_payload()
        if daily.get("active"):
            lines.append(
                f"日常小场景：她在自己用{daily.get('toy_label') or '玩具'}"
                f"（{daily.get('zone_label') or '—'}），还剩约 {daily['remaining']} 分钟，"
                f"已经被弄到 {daily['orgasms']} 次；"
                f"真正的亲密动作（碰她/进入/内射）会把它升级成正式活动场景")
        mood_info = mood.payload(self.state, self.settings)
        lines.append(
            f"日常情绪：欲望度 {mood_info['desire']['value']:.0f}"
            f"（{mood_info['desire']['title']}）"
            f"｜羞耻度 {mood_info['shame']['value']:.0f}"
            f"（{mood_info['shame']['title']}）"
            + (f"｜羞耻期还剩 {mood_info['shame_period']['remaining']} 分钟（玩具不可用）"
               if mood_info["shame_period"]["active"] else ""))
        if mood_info["desire"]["level"]:
            lines.append(f"欲望提示：{mood_info['desire']['prompt']}")
        if mood_info["shame"]["level"]:
            lines.append(f"羞耻提示：{mood_info['shame']['prompt']}")
        lines.append(
            f"子宫：{uterus['ml']:.1f}/{uterus['capacity_effective']:.0f} ml"
            f"（{uterus['level_title']}，{uterus['percent']:.0f}%"
            + (f"，撑开 +{uterus['stretch_percent']:.0f}%" if uterus["stretch"] else "")
            + f"；溢出{'开' if uterus['overflow_enabled'] else '关'}"
              f"@{uterus['overflow_at']:.0f}%"
            + f"；结束后漏出{'开' if uterus['after_leak_enabled'] else '关'}"
              f"@{uterus['after_leak_until']:.0f}%/{uterus['after_leak_per_hour']:.0f}ml每小时）")
        endure = endurance.payload(self.state, self.settings)
        if endure.get("enabled"):
            lines.append(
                f"忍耐条：{endure['value']:.0f}/{endure['cap']:.0f}"
                f"（{endure['level_title']}）"
                + ("｜满了，再刺激一下就…" if endure["full"] else "")
                + (f"｜连续 {endure['combo']} 次后条变长 +{endure['grow_percent']:.0f}"
                   if endure["combo"] else ""))
        sw = swallow.payload(self.state, self.settings)
        if sw.get("enabled") and sw.get("collected"):
            lines.append(f"吞精：已收集 {sw['collected']}（{'在嘴里' if sw.get('mouth') else '在手里'}）")
        ub = unbirth.payload(self.state, self.settings)
        if ub.get("enabled") and (ub.get("inside") or ub.get("ratio", 1.0) < 0.99):
            where = "在里面" if ub["inside"] else ("缩小 %.2f" % ub["ratio"])
            lines.append("Unbirth：%s（体积 %.0fml / 上限 %.0fml）"
                         % (where, ub["volume_ml"], ub["limit_ml"]))
        cloth = clothing.summary(self.state, self.settings)
        lines.append(f"衣装：上 {cloth['upper']}｜下 {cloth['lower']}｜腿 {cloth['legs']}｜脚 {cloth['feet']}")
        birth_info = birth.payload(self.state, self.settings)
        if birth_info.get("in_progress") or birth_info.get("stage") == "done":
            lines.append(f"生产：{birth_info['label']}"
                         + (f"（产痛 {birth_info['pain']:.0f}）" if birth_info.get("active") else ""))
        condom_info = condom.payload(self.state, self.settings)
        if condom_info.get("worn"):
            lines.append("避孕套：戴着")
        elif condom_info.get("broken"):
            lines.append("避孕套：刚破了")
        water = squirt.payload(self.state, self.settings)
        lines.append(f"水量：{water['value']:.0f}/{water['max']:.0f}")
        lube_info = lube.payload(self.state, self.settings)
        if lube_info.get("active"):
            lines.append(f"润滑：还有 {lube_info['left_minutes']} 分钟")
        elif lube_info.get("hand_active"):
            lines.append(f"手部润滑：还有 {lube_info['hand_left_minutes']} 分钟")
        insert_info = uterus_insert.payload(self.state, self.settings)
        if insert_info.get("active"):
            lines.append(f"插入子宫：在里面（痛感 {insert_info['pain']:.0f}）")
        elif insert_info.get("ready"):
            lines.append("插入子宫：现在够湿够兴奋，可以进")
        size_info = size.payload(self.state, self.settings)
        lines.append(
            f"尺寸：他 {size_info['penis_length']:.1f}×{size_info['penis_girth']:.1f} cm"
            f"｜她 {size_info['vagina']['effective']:.1f} cm"
            + (f"（浮动 +{size_info['vagina']['delta']:.1f}）" if size_info['vagina']['delta'] else "")
            + ("" if size_info["reachable"] else f"｜差 {size_info['short_by']:.1f} cm 够不到最里面"))
        moved = behavior.payload(self.state, self.settings)
        if moved.get("active"):
            lines.append(f"刚才的动作：{moved['zone_label']}·{moved['label']}")
        mem = memory_link.available(self.context)
        mem_write = "开" if memory_link.write_enabled(self.settings) else "关"
        lines.append(f"记忆：蔗糖的记忆中枢{'已装' if mem['sugarmemory'] else '未装'}"
                     f"（写入{mem_write}）｜天使之魂{'已装' if mem['angel'] else '未装'}"
                     f"（只按对话记）")
        sleep_info = sleepy.awake_payload(self.state, self.settings)
        if sleep_info.get("active"):
            lines.append("睡眠时段·活动例外：已允许她发言（还剩 "
                         + str(sleep_info["minutes"]) + " 分钟）")
        wet_info = wetness.payload(self.state, self.settings)
        if wet_info.get("enabled"):
            lines.append(f"湿润度：{wet_info['value']:.0f}/100"
                         f"（{wet_info['level_title']}，基础 {wet_info['base']:.0f}）")
        spot = special.payload(self.state, self.settings)
        if spot.get("enabled") and spot.get("zone"):
            lines.append(f"特别敏感点：{spot['label']}（约 {spot['remaining']} 分钟后会换）")
        hymen_info = body.hymen_payload(self.state, self.settings)
        lines.append(f"处女膜：{hymen_info['label']}"
                     + (f"（{hymen_info['cause']}）" if hymen_info['cause'] else ""))
        contra = body.contraception_payload(self.state, self.settings)
        lines.append(
            f"避孕：药 {'生效中 %.1f 小时' % contra['pill_hours_left'] if contra['pill_active'] else '没吃'}"
            f"｜套 {'戴着' if contra['condom'] else '没戴'}"
            f"｜受孕倍率 ×{contra['multiplier']:.2f}")
        if succubus.enabled(self.state, self.settings):
            info = succubus.payload(self.state, self.settings)
            used = "不限" if info["unlimited"] else f"{info['used']}/{info['daily_limit']}"
            lines.append(
                f"魅魔：淫纹 Lv.{info['level']}｜今日 {used}"
                f"｜欲望 +{info['desire_gain']}/次"
                f"｜意愿 {'愿意' if info['willing'] is True else '不愿意' if info['willing'] is False else '未表态'}"
                f"｜吸收 ×{info['absorption_multiplier']:.0f}")

        edge_stack = state_mod.edge_stack(self.state, self.settings)
        if edge_stack:
            lines.append(
                f"寸止：连着 {edge_stack} 次（门槛 +"
                f"{state_mod.edge_threshold_bonus(self.state, self.settings):.0f}，"
                f"渴求 {state_mod.edge_craving(self.state, self.settings):.0f}%）")
        if state_mod.ovulation_active(self.state):
            until = datetime.fromtimestamp(
                state_mod.ovulation_until(self.state)).strftime("%m-%d %H:%M")
            lines.append(f"排卵：被诱发（到 {until} 之前按排卵期算）")

        if not prog:
            p = self._probability(data, cycle, inside=True)
            lines.extend(fertility.describe(p))
        last_roll = self.state.get("last_roll")
        if isinstance(last_roll, dict):
            when = datetime.fromtimestamp(util.safe_float(last_roll.get("at"), 0)).strftime("%m-%d %H:%M")
            lines.append(f"上次判定：{when}，{last_roll.get('probability', 0):.1f}%，"
                         f"{'命中' if last_roll.get('hit') else '未命中'}")
        lines.append(f"数据文件：{self.store.path}")
        return "\n".join(lines)

    @filter.command("受孕状态")
    async def cmd_status(self, event):
        if not self._owner_only(event):
            yield event.plain_result("这个只在主人的私聊里看。")
            return
        yield event.plain_result(self._status_text(event))

    @filter.command("受孕情绪")
    async def cmd_mood(self, event):
        """看欲望度 / 羞耻度，以及羞耻期还剩多久。"""
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能看。")
            return
        if not self.settings.bool("mood.enabled"):
            yield event.plain_result("日常情绪关着（配置 mood.enabled）。")
            return
        info = mood.payload(self.state, self.settings)
        lines = ["【日常情绪】"]
        for key in mood.MOOD_KEYS:
            row = info[key]
            lines.append(f"{mood.MOOD_LABELS[key]}：{row['value']:.0f}/100（{row['title']}）")
            if row["level"]:
                lines.append(f"  {row['prompt']}")
        if info["shame_period"]["active"]:
            lines.append(f"羞耻期：还剩 {info['shame_period']['remaining']} 分钟（这期间玩具不可用）")
        lines.append("欲望满了会自己贴上来、转成正式活动场景；羞耻满了会加一点鱼之心的责怪"
                     "并进一段羞耻期。安慰/摸摸头/亲吻/正常日常/时间都会降羞耻。")
        yield event.plain_result("\n".join(lines))

    @filter.command("受孕帮助")
    async def cmd_help(self, event):
        if not self._owner_only(event):
            yield event.plain_result("这个只在主人的私聊里看。")
            return
        yield event.plain_result(HELP_TEXT)

    @filter.command("受孕场景")
    async def cmd_scene(self, event):
        """手动开场/续场/看场景状态：关键词识别只在场景里生效。"""
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        text = str(getattr(event, "message_str", "") or "")
        if any(word in text for word in ("关", "结束", "退出", "停止")):
            state_mod.clear_scene(self.state)
            self._save()
            yield event.plain_result("好，亲密场景已结束；这之后聊天里的关键词不再参与判定。")
            return
        in_scene, why = self._scene_active()
        if in_scene:
            yield event.plain_result(
                f"当前已经在场景里：{why}｜本插件窗口还剩 "
                f"{state_mod.scene_remaining(self.state, self.settings)} 分钟。\n"
                f"发「/受孕场景 关闭」可以手动结束。")
            return
        self._touch_scene("命令")
        minutes = self.settings.int("adult.scene_window_minutes", 1, 720)
        yield event.plain_result(
            f"好，进入亲密场景（{minutes} 分钟内有效，快感/高潮/射精都会自动续场）。\n"
            f"这之前，平常聊天里出现「内射」「高潮」之类的词不会触发任何判定。")

    @filter.command("受孕同意")
    async def cmd_consent(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        hours = self.settings.float("adult_consent_hours", 0.0, 720.0)
        state_mod.grant_consent(self.state, hours)
        self._save()
        text = (f"好，本插件临时授权 {hours:.0f} 小时。" if hours
                else "好，本插件长期授权，直到 /受孕关闭。")
        yield event.plain_result(text + "\n（这只影响受孕插件，不会打开鱼之心的成人层；"
                                 "进入场景用 /受孕场景。）")

    @filter.command("受孕关闭")
    async def cmd_consent_off(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        state_mod.clear_consent(self.state)
        self._save()
        yield event.plain_result("已撤掉受孕插件的临时授权。")

    @filter.command("受孕测试")
    async def cmd_test(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        data = self._read_sources(force=True)
        cycle = self._cycle()
        inside = self._probability(data, cycle, inside=True)
        outside = self._probability(data, cycle, inside=False, orgasm_recent=False)
        lines = ["【受孕概率分解 · 体内】", *fertility.describe(inside),
                 "", "【对照：体外】", f"→ {outside.probability:.2f}%"]
        if pregnancy.progress(self.state):
            lines.append("注意：当前已在孕期，不会掷骰。")
        yield event.plain_result("\n".join(lines))

    @filter.command("受孕快感")
    async def cmd_pleasure(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        text = str(getattr(event, "message_str", "") or "")
        match = NUMBER_RE.search(text.split("受孕快感", 1)[-1])
        default = self.settings.float("pleasure.tool_gain", 0.0, 100.0)
        amount = _clamp_amount(match.group(0), 1.0, 50.0, default) if match else default
        result = self._record_pleasure(amount, "命令")
        if result and result.get("refused"):
            yield event.plain_result(f"现在不记录快感：{result['refused']}")
            return
        extra = f"（她还在难受，涨得慢，大概还要缓 {result['rest']} 分钟）" \
            if result.get("pain") else ""
        yield event.plain_result(
            f"快感 {result['before']:.0f} → {result['value']:.0f}/{result['cap']:.0f}{extra}")

    @filter.command("受孕高潮")
    async def cmd_orgasm(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        force = "强制" in str(getattr(event, "message_str", "") or "")
        result = self._record_orgasm("命令", force=force)
        if result and result.get("refused"):
            if result.get("overstimulated"):
                yield event.plain_result(
                    f"{result['refused']}。\n（这段时间她碰一下都难受，会想让你慢一点、歇一会儿。）")
                return
            if "快感还不够" in str(result.get("refused")):
                yield event.plain_result(
                    f"{result['refused']}。先用 /受孕快感 把快感加上去，"
                    f"或者发 /受孕高潮 强制 跳过门槛。")
                return
            yield event.plain_result(f"现在不记录高潮：{result['refused']}")
            return
        combo = result.get("combo") or {}
        tag = f"（连续第 {combo.get('count', 1)} 次）" if combo.get("count", 0) > 1 else ""
        yield event.plain_result(
            f"记下了：本次第 {result['session']} 次高潮{tag}，快感 {result['before']:.0f} → "
            f"{result['after']:.0f}")

    @filter.command("受孕寸止")
    async def cmd_edge(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        result = self._record_edge("命令")
        if result.get("refused"):
            yield event.plain_result(f"现在不能寸止：{result['refused']}")
            return
        yield event.plain_result(
            f"寸止了（第 {result['stack']} 次）：快感吊在 {result['pleasure']:.0f}，"
            f"门槛抬到 {result['threshold'] + result['bonus']:.0f}"
            f"（+{result['bonus']:.0f}），渴求 {result['craving']:.0f}%。")

    @filter.command("受孕触碰")
    async def cmd_touch(self, event):
        """亲/摸某个敏感点：/受孕触碰 乳房 2"""
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        text = str(getattr(event, "message_str", "") or "").split("受孕触碰", 1)[-1].strip()
        parts = [part for part in re.split(r"[\s,，]+", text) if part]
        if not parts:
            zones = "、".join(f"{row['label']}({row['key']})"
                             for row in intimacy.zones_payload(self.settings, self.state) if row["enabled"])
            yield event.plain_result(
                f"用法：/受孕触碰 <部位> [次数] [方式]\n可用：{zones or '（敏感点未启用）'}\n"
                f"方式（能填就填）：乳房 乳交/舔/吮吸；乳头 揉搓/舔/吮吸；"
                f"外阴 逗弄/舔/吮吸；阴道 手指/生殖器/小玩具/舔/吮吸；"
                f"G点 手指/生殖器/小玩具；子宫颈 生殖器/小玩具；"
                f"肛 手指/生殖器/小玩具/舔/吮吸；嘴 生殖器/舔/吮吸/舌；"
                f"耳朵 舔耳；脚 生殖器/舔/吮吸；尾巴 抚摸/揉捏玩弄/舔/吮吸")
            return
        zone = intimacy.normalize_zone(parts[0])
        times = 1
        method = ""
        if len(parts) > 1:
            times = util.safe_int(re.sub(r"[^\d]", "", parts[1]), 1) or 1
        if len(parts) > 2:
            method = parts[2]
        result = self._record_touch(zone or parts[0], times, "命令", method=method)
        if result.get("refused"):
            zones = "、".join(f"{row['label']}({row['key']})"
                             for row in intimacy.zones_payload(self.settings, self.state) if row["enabled"])
            yield event.plain_result(f"现在不记录：{result['refused']}\n可用：{zones}")
            return
        yield event.plain_result(
            f"{result['label']} ×{result['times']}：快感 +{result['gain']:.0f}，"
            f"现在 {result['value']:.0f}/"
            f"{self.settings.float('pleasure.max', 1, 1000):.0f}"
            f"（开发度 {result['dev']}%，敏感度 ×{result['sensitivity']:.2f}）"
            + self._sub_text(result))

    @filter.command("受孕玩具")
    async def cmd_toy(self, event):
        """用一次小玩具：/受孕玩具 跳蛋 2；不带参数看列表。"""
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        text = str(getattr(event, "message_str", "") or "").split("受孕玩具", 1)[-1].strip()
        parts = [part for part in re.split(r"[\s,，]+", text) if part]
        if not parts or parts[0] in ("列表", "list"):
            rows = toys.toys_payload(self.settings, self.state)
            lines = ["【小玩具】用法：/受孕玩具 <名字> [强度1-3]"]
            for row in rows:
                mark = "·" if row["enabled"] else "×"
                lines.append(f"  {mark} {row['label']}（{row['key']}）：基础快感 "
                             f"{row['pleasure']:.0f}，中等强度 +{row['gain']:.1f}")
            active = self._toy_payload()
            if active:
                lines.append(f"现在身上：{active['label']}（{active['intensity_label']}，"
                             f"还剩 {active['remaining']} 分钟）")
            yield event.plain_result("\n".join(lines))
            return
        toy = toys.normalize_toy(parts[0])
        intensity = 2
        if len(parts) > 1:
            intensity = util.safe_int(re.sub(r"[^\d]", "", parts[1]), 2) or 2
        place = parts[2] if len(parts) > 2 else ""
        result = self._record_toy(toy or parts[0], intensity, "命令", place=place)
        if result.get("refused"):
            yield event.plain_result(f"现在不记录：{result['refused']}")
            return
        yield event.plain_result(
            f"{result['label']}（{result['intensity_label']}·{result['place_label']}）："
            f"快感 +{result['gain']:.0f}，"
            f"现在 {result['value']:.0f}/"
            f"{self.settings.float('pleasure.max', 1, 1000):.0f}"
            + self._toy_extra(result))

    @filter.command("受孕排出")
    async def cmd_expel(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        result = self._expel_uterus("命令")
        if result.get("refused"):
            yield event.plain_result(f"现在不能排：{result['refused']}")
            return
        if result.get("empty"):
            yield event.plain_result("子宫里本来就是空的。")
            return
        yield event.plain_result(f"排出来了：{result['before']:.1f} ml → 0 ml。")

    @filter.command("受孕避孕药")
    async def cmd_pill(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        text = str(getattr(event, "message_str", "") or "") .split("受孕避孕药", 1)[-1].strip()
        verb = "status"
        if any(word in text for word in ("停", "不吃", "停掉")):
            verb = "stop"
        elif any(word in text for word in ("吃", "服用", "吃药")):
            verb = "take"
        result = self._contraception_pill(verb, "命令")
        if result.get("refused"):
            yield event.plain_result(f"现在不能记录：{result['refused']}")
            return
        if result.get("status"):
            status = result["status"]
            left = status.get("pill_hours_left", 0)
            yield event.plain_result(
                f"避孕药：{'生效中，还剩 %.1f 小时' % left if left else '没吃'}"
                f"（有效性 {self.settings.float('contraception.pill_effectiveness', 0, 100):.0f}%）")
            return
        if result.get("stopped"):
            yield event.plain_result("避孕药停了。")
            return
        yield event.plain_result(f"吃了避孕药：{result['hours']:.0f} 小时内有效。")

    @filter.command("受孕避孕套")
    async def cmd_condom(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        text = str(getattr(event, "message_str", "") or "").split("受孕避孕套", 1)[-1].strip()
        if any(word in text for word in ("摘", "脱", "取下")):
            used = False
        elif any(word in text for word in ("戴", "套上")):
            used = True
        else:
            status = body.contraception_payload(self.state, self.settings)
            yield event.plain_result(
                f"避孕套：{'戴着' if status['condom'] else '没戴'}"
                f"（有效性 {self.settings.float('contraception.condom_effectiveness', 0, 100):.0f}%，"
                f"破裂 {self.settings.float('contraception.condom_break_chance', 0, 100):.0f}%）")
            return
        result = self._contraception_condom(used, "命令")
        if result.get("refused"):
            yield event.plain_result(f"现在不能记录：{result['refused']}")
            return
        yield event.plain_result("戴上了避孕套。" if used else "摘下了避孕套。")

    @filter.command("受孕避孕状态")
    async def cmd_contraception(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        status = body.contraception_payload(self.state, self.settings)
        lines = [
            "【避孕】",
            f"避孕药：{'生效中，还剩 %.1f 小时' % status['pill_hours_left'] if status['pill_active'] else '没吃'}",
            f"避孕套：{'戴着' if status['condom'] else '没戴'}",
            f"受孕概率倍率：×{status['multiplier']:.2f}",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command("受孕处女膜")
    async def cmd_hymen(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        raw = str(getattr(event, "message_str", "") or "").split("受孕处女膜", 1)[-1].strip()
        if any(word in raw for word in ("恢复", "修复", "补")):
            self._restore_hymen("命令")
            yield event.plain_result("处女膜已恢复完整。")
            return
        info = body.hymen_payload(self.state, self.settings)
        if info["intact"]:
            yield event.plain_result("她的处女膜还完整（第一次进入会疼、会破）。")
            return
        when = datetime.fromtimestamp(info["ruptured_at"]).strftime("%m-%d %H:%M") if info["ruptured_at"] else "—"
        yield event.plain_result(f"处女膜已破裂（{when}，{info['cause'] or '—'}）。")

    @filter.command("受孕魅魔")
    async def cmd_succubus(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        raw = str(getattr(event, "message_str", "") or "").split("受孕魅魔", 1)[-1].strip().lower()
        data = succubus.payload(self.state, self.settings)
        if any(word in raw for word in ("愿意", "想怀", "要怀")) and "不" not in raw:
            result = self._succubus_set_willing(True)
            yield event.plain_result(f"怀孕意愿：{result['label']}。")
            return
        if any(word in raw for word in ("不愿意", "不想怀", "不要怀", "不怀")):
            result = self._succubus_set_willing(False)
            yield event.plain_result(f"怀孕意愿：{result['label']}。")
            return
        if any(word in raw for word in ("重置", "未表态", "取消")):
            result = self._succubus_set_willing(None)
            yield event.plain_result(f"怀孕意愿：{result['label']}。")
            return
        import re as _re
        match = _re.search(r"(?:等级|lv|Lv)\s*(\d+)", raw)
        if match:
            result = self._succubus_set_level(value=int(match.group(1)))
            yield event.plain_result(f"淫纹等级调到 Lv.{result['level']}。")
            return
        yield event.plain_result(
            f"【魅魔】{'开启' if data['enabled'] else '关闭'}"
            f"｜淫纹 Lv.{data['level']}/{data['max_level']}"
            f"｜今日榨取 {'不限' if data['unlimited'] else str(data['used']) + '/' + str(data['daily_limit'])}"
            f"｜欲望 +{data['desire_gain']}/次"
            f"｜怀孕意愿 {'愿意' if data['willing'] is True else '不愿意' if data['willing'] is False else '未表态'}"
            f"｜{data['conception_note'] or '未开启'}\n"
            f"用法：/受孕魅魔 等级 N ｜ /受孕魅魔 愿意 ｜ /受孕魅魔 不愿意 ｜ /受孕魅魔 重置")

    @filter.command("受孕敏感点")
    async def cmd_zones(self, event):
        if not self._owner_only(event):
            yield event.plain_result("这个只在主人的私聊里看。")
            return
        rows = intimacy.zones_payload(self.settings, self.state)
        if not self.settings.bool("zones.enabled") or not rows:
            yield event.plain_result("敏感点系统关着。")
            return
        lines = ["【敏感点】（开发度越高、敏感度越高，一次触碰涨得越多）"]
        for row in rows:
            mark = "·" if row["enabled"] else "×"
            lines.append(f"  {mark} {row['label']}：开发 {row['dev']:>3}%｜敏感 ×"
                         f"{row['sensitivity']:.2f}｜基础 {row['base']:.0f}｜"
                         f"每次 +{row['gain']:.1f}")
        lines.append("用法：/受孕触碰 <部位> [次数]；也可以让模型调用 intimacy_touch。")
        yield event.plain_result("\n".join(lines))

    @filter.command("受孕肛内")
    async def cmd_anal(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        yield event.plain_result(self._format_ejaculation(
            self._record_ejaculation("anal", "命令")))

    @filter.command("受孕深喉")
    async def cmd_throat(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        yield event.plain_result(self._format_ejaculation(
            self._record_ejaculation("throat", "命令")))

    @filter.command("受孕内射")
    async def cmd_inside(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        yield event.plain_result(self._format_ejaculation(self._record_ejaculation(True, "命令")))

    @filter.command("受孕体外")
    async def cmd_outside(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        yield event.plain_result(self._format_ejaculation(self._record_ejaculation(False, "命令")))

    def _format_ejaculation(self, result: dict) -> str:
        if result.get("refused"):
            return f"现在不记录：{result['refused']}"
        if result.get("pregnant") and not result.get("rolled"):
            return f"记下了。{result.get('reason')}，不掷受孕骰。"
        if result.get("postpartum"):
            return f"记下了。{result.get('reason')}，不掷受孕骰。"
        p = result.get("p")
        mode = result.get("mode") or (result.get("count") or {}).get("mode") or "vagina"
        label = intimacy.MODE_LABELS.get(mode, mode)
        gain = util.safe_float(result.get("pleasure_gain"), 0.0)
        uterus = result.get("uterus")
        uterus_note = (f" 子宫 {uterus['ml']:.1f}/{uterus['capacity_effective']:.0f} ml"
                       f"（{uterus['level_title']}）"
                       + (f"，溢出来 {uterus['overflow']:.1f} ml" if uterus.get("overflow") else "")
                       + "。" if uterus else "")
        if p is None:
            return f"记下了：{label}，快感 +{gain:.0f}{uterus_note}不会受孕。"
        notes = "；".join(result.get("notes") or [])
        note_line = f"（{notes}）" if notes else ""
        postpartum_note = ""
        if (p.factors or {}).get("postpartum") is not None:
            postpartum_note = f"（产后恢复期，概率已按 ×{p.factors['postpartum']:.2f} 压低）"
        if result.get("hit"):
            prog = pregnancy.progress(self.state)
            gap = f"预产期 {prog['due_date'].isoformat()}" if prog else ""
            paused = bool((self.state.get("pregnancy") or {}).get("cycle_suppressed"))
            note = ("她的月经周期已按孕期暂停；接下来十个月不会再有经期。"
                    if paused else
                    "（PC 周期这次没改成，已用提示词兜底；日志里能看到原因。）")
            return (f"受孕命中（概率 {p.probability:.1f}%）{note_line}。{gap}{postpartum_note}"
                    f"{uterus_note}\n{note}")
        return (f"这次没受孕（概率 {p.probability:.1f}%，{p.tier}）{note_line}{postpartum_note}。"
                f"生理期：{cyclemodel.phase_label(p.phase)}。{uterus_note}")

    @filter.command("受孕强制")
    async def cmd_force(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        if pregnancy.progress(self.state):
            yield event.plain_result("她已经在孕期了。")
            return
        if self.settings.bool("pregnancy.postpartum_no_conception"):
            stage = pregnancy.postpartum_stage(self.state, self.settings)
            if stage and stage.get("key") == "hard":
                until = pregnancy.postpartum_until_text(self.state)
                where = f"（大约到 {until}）" if until else ""
                yield event.plain_result(
                    f"她还在产后前 {stage['hard_days']} 天{where}，这段时间不会受孕；"
                    f"要强制测试就把 pregnancy.postpartum_no_conception 关掉。")
                return
        self._start_pregnancy(100.0, "手动强制")
        self._ensure_pc_cycle_state()
        prog = pregnancy.progress(self.state)
        yield event.plain_result(
            f"已置为受孕：孕 1 个月，预产期 {prog['due_date'].isoformat()}。"
            f"PC 周期：{pc_cycle.describe(self.settings)}")

    @filter.command("受孕重置")
    async def cmd_reset(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        text = str(getattr(event, "message_str", "") or "")
        if "确认" not in text:
            yield event.plain_result("这会清掉孕期并恢复 PC 周期。确定的话发：/受孕重置 确认")
            return
        had = pregnancy.is_pregnant(self.state)
        if had:
            self._finish_pregnancy(reason="手动结束")
        else:
            pregnancy.clear_pregnancy(self.state)
            try:
                pc_state.clear_pregnancy(self.settings)
            except Exception as error:
                logger.warning("[受孕] 清除 PC 孕期状态失败：%s", error)
            if self.settings.bool("pregnancy.suppress_pc_cycle"):
                result = pc_cycle.restore(self.settings)
                if not result.get("ok"):
                    self._save()
                    yield event.plain_result(
                        f"孕期已清掉，但恢复 PC 周期失败：{result.get('reason')}\n"
                        f"插件会在后台每 5 分钟重试一次；也可以手动用备份库还原。")
                    return
        self.state["own_cycle"] = {"anchor_date": util.today().isoformat()}
        self._save()
        self._cycle_cache = None
        yield event.plain_result("已重置孕期状态，周期恢复。")

    @filter.command("受孕记录")
    async def cmd_log(self, event):
        if not self._owner_only(event):
            yield event.plain_result("只有主人的私聊能操作。")
            return
        rows = state_mod.recent_log(self.state, 12)
        if not rows:
            yield event.plain_result("还没有记录。")
            return
        lines = ["【最近事件】"]
        for row in rows:
            when = datetime.fromtimestamp(util.safe_float(row.get("at"), 0)).strftime("%m-%d %H:%M")
            lines.append(f"- {when} {row.get('text')}")
        yield event.plain_result("\n".join(lines))

    # ================================================================ 工具

    @filter.llm_tool(name="intimacy_pleasure")
    async def tool_pleasure(self, event, amount: int = 12, note: str = ""):
        """记录她此刻的「快感值」上升。只在成人亲密场景里使用。

        什么时候用：亲密正在推进、她明显被撩动时调用一次；不要每句话都调，
        一段描写调一次就够。快感会随时间自然回落。

        Args:
            amount(number): 这次上升多少，1-50，默认 12
            note(string): 一句话说明（可留空）
            secret(bool): 她知不知道你拿了玩具；不知道填 true（会惊到）
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.pleasure"):
            return "工具已关闭。"
        result = self._record_pleasure(_clamp_amount(amount, 1.0, 50.0, 12.0),
                                       note or "工具")
        if result and result.get("refused"):
            return f"现在不能记录：{result['refused']}"
        if result.get("pain"):
            return (f"快感 {result['before']:.0f} → {result['value']:.0f}/{result['cap']:.0f}。"
                    f"她刚高潮过头、太敏感了，涨得很慢，也不太想被碰；会想让你慢一点、歇一歇。")
        return (f"快感 {result['before']:.0f} → {result['value']:.0f}/{result['cap']:.0f}。"
                f"（这只是一个数值，不要念出来。）")

    @filter.llm_tool(name="intimacy_orgasm")
    async def tool_orgasm(self, event, note: str = ""):
        """记录她达到一次高潮。只在成人亲密场景里、她确实到的时候调用。

        调用后快感会先上升再按不应期回落，次数会累加；高潮后短时间内被体内射精，
        受孕概率会更高。

        Args:
            note(string): 一句话说明（可留空）
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.orgasm"):
            return "工具已关闭。"
        result = self._record_orgasm(note or "工具")
        if result and result.get("refused"):
            if result.get("overstimulated"):
                return (f"她到不了了：{result['refused']}。"
                        f"不要再把她写成享受；让她自己开口说难受、好痛，想让你慢一点、停下来，"
                        f"歇够 {result.get('rest_minutes', 0)} 分钟再说。")
            if "快感还不够" in str(result.get("refused")):
                return (f"{result['refused']}。先继续推进、调用 intimacy_pleasure，"
                        f"别自己把她写成到了。")
            return f"现在不能记录：{result['refused']}"
        combo = result.get("combo") or {}
        tag = f"（连续第 {combo.get('count', 1)} 次，越来越敏感）" if combo.get("count", 0) > 1 else ""
        return (f"记下第 {result['session']} 次高潮{tag}（今日 {result['today']} 次），"
                f"快感回落到 {result['after']:.0f}。")

    @filter.llm_tool(name="intimacy_edge")
    async def tool_edge(self, event, note: str = ""):
        """寸止：她快到了，但这一次停下来、不让她到。

        什么时候用：场景里快感已经接近高潮门槛、你决定吊着她的时候调用。
        之后她会更渴（渴求上升、触碰涨得更快），但高潮门槛会暂时被抬高；
        连着寸止多次后门槛加成会递减；最后终于到的时候快感会更强烈。

        Args:
            note(string): 一句话说明（可留空）
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.edge"):
            return "工具已关闭。"
        result = self._record_edge(note or "工具")
        if result.get("refused"):
            return f"现在不能寸止：{result['refused']}"
        return (f"寸止了（第 {result['stack']} 次）：快感吊在 {result['pleasure']:.0f}，"
                f"门槛被抬到 {result['threshold'] + result['bonus']:.0f}"
                f"（+{result['bonus']:.0f}），渴求 {result['craving']:.0f}%。"
                f"她会明显更急、更想要，别写成她到了。")

    @filter.llm_tool(name="intimacy_touch")
    async def tool_touch(self, event, zone: str = "kiss", times: int = 1,
                         method: str = "", note: str = "",
                         depth: float = 0.0, hymen_break: bool = False):
        """亲/摸某个敏感点，按她的开发度与敏感度涨快感。

        什么时候用：场景里亲吻、抚摸、揉胸、碰下面、进入等等，每次可以调用一次。
        部位（zone）可选：kiss/breast/nipple/vulva/vagina/gspot/cervix/anus/mouth/ear/foot/tail，
        也可以直接写中文：亲吻、乳房、乳头、外阴、阴道、G点、子宫颈、肛、嘴、耳朵、脚、尾巴。
        这个工具只涨快感，不判定受孕；射精/内射请用 intimacy_ejaculation。
        受孕活动里同一个部位碰两三次，会把它的「子敏感度」条填满（三段：初起/发烫/将溢），
        满了会给她这个敏感点加开发度、敏感度，再补一笔快感，然后条很快回落。

        method（这个部位"正在被怎么弄"）能填就尽量填，提示词会按方式写得准得多：
          乳房：乳交 / 舔 / 吮吸          乳头：揉搓 / 舔 / 吮吸
          外阴：逗弄 / 舔 / 吮吸          阴道：手指 / 生殖器 / 小玩具 / 舔 / 吮吸
          G点：手指 / 生殖器 / 小玩具     子宫颈：生殖器 / 小玩具
          肛：手指 / 生殖器 / 小玩具 / 舔 / 吮吸
          嘴/喉咙：生殖器 / 舔 / 吮吸 / 舌  耳朵：舔耳  脚：生殖器 / 舔 / 吮吸
          尾巴：抚摸 / 揉捏玩弄 / 舔 / 吮吸
        填中文或 key（lick/suck/penis…）都行；不填就沿用这个部位上一次的方式，
        关键词能看出来时系统也会自动补。

        Args:
            zone(string): 部位，默认 kiss
            times(int): 次数，默认 1（最多 20）
            method(string): 方式（见上，可留空）
            note(string): 一句话说明（可留空）
            depth(float): 进入深度 cm；超过处女膜深度才算顶破（默认 0，只摸不破）
            hymen_break(boolean): 明确顶破处女膜（默认 false）
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.touch"):
            return "工具已关闭。"
        result = self._record_touch(zone, times, note or "工具", method=method,
                                    depth=depth, hymen_break=hymen_break)
        if result.get("refused"):
            zones = "、".join(intimacy.ZONE_LABELS.get(k, k)
                             for k in (result.get("zones") or [])) or "无"
            return f"现在不能记录：{result['refused']}。可用部位：{zones}"
        how = f"（{result['sub'].get('method_label')}）" if (result.get("sub") or {}).get("method_label") else ""
        return (f"{result['label']}{how} ×{result['times']}：快感 +{result['gain']:.0f}，"
                f"现在 {result['value']:.0f}/{self.settings.float('pleasure.max', 1, 1000):.0f}"
                f"（开发度 {result['dev']}%，敏感度 ×{result['sensitivity']:.2f}）"
                + self._sub_text(result)
                + "。到这个程度，她的呼吸和身体会跟着变，可以继续写。")

    @filter.llm_tool(name="intimacy_toy")
    async def tool_toy(self, event, toy: str = "bullet", intensity: int = 2,
                       place: str = "", note: str = "", secret: bool = False,
                       depth: float = 0.0, hymen_break: bool = False):
        """在亲密场景里用一次小玩具（跳蛋、振动棒、吸吮器、按摩棒、肛塞、乳夹）。

        什么时候用：她拿出玩具、或你把它用在她身上的时候调用一次。
        玩具只涨快感、不判定受孕；用完之后一段时间里，提示词会记得"还在用"。
        强度 1–3（轻柔/中等/强烈），默认 2。

        Args:
            toy(string): 玩具，可写 bullet/vibrator/sucker/wand/plug/clamp 或中文名
            intensity(int): 强度 1–3，默认 2
            place(string): 用在哪（外阴/阴道/肛/乳头），留空用默认部位
            note(string): 一句话说明（可留空）
            depth(float): 进入深度 cm；超过处女膜深度才算顶破（默认 0，只顶着不破）
            hymen_break(boolean): 明确顶破处女膜（默认 false）
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.toy"):
            return "工具已关闭。"
        result = self._record_toy(toy, intensity, note or "工具", place=place,
                                  secret=bool(secret), depth=depth,
                                  hymen_break=hymen_break)
        if result.get("refused"):
            names = "、".join(row["label"] for row in toys.toys_payload(
                self.settings, self.state) if row["enabled"]) or "无"
            return f"现在不能记录：{result['refused']}。可用玩具：{names}"
        extra = self._toy_extra(result).lstrip("；")
        if result.get("massage_line"):
            extra = (extra + "；" if extra else "") + result["massage_line"]
        return (f"{result['label']}（{result['intensity_label']}·{result['place_label']}）："
                f"快感 +{result['gain']:.0f}，现在 {result['value']:.0f}。"
                + (extra + "。" if extra else "")
                + "震动/胀感会留在她身上，继续写她的反应。")

    @filter.llm_tool(name="daily_comfort")
    async def tool_comfort(self, event, kind: str = "安慰", note: str = ""):
        """日常里安慰她 / 摸摸头 / 亲一下：能让她没那么羞，也会降一点欲望。

        什么时候用：她说不好意思、别过脸、闷着不说话，或者你主动哄她的时候调用一次；
        她刚羞耻满溢、进羞耻期的时候特别该哄。
        kind 可以写 安慰 / 摸摸头 / 亲吻 / 抱抱 / 哄，写别的也当"安慰"。
        这个工具不影响受孕判定，也不会开亲密场景。

        Args:
            kind(string): 怎么哄，默认 安慰
            note(string): 一句话说明（可留空）
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("mood.enabled"):
            return "日常情绪关着。"
        result = self._comfort(kind or "安慰", note or "工具")
        period = mood.shame_period_remaining(self.state)
        tail = (f"她还在羞耻期里（约 {period} 分钟），先别急着再拿玩具。"
                if period else "她的羞意褪下去一些了，可以继续正常聊。")
        return (f"{result['kind']}：羞耻度 {result['shame']:.0f}"
                f"（{result['shame_delta']:+.0f}）、欲望度 {result['desire']:.0f}"
                f"（{result['desire_delta']:+.0f}）。{tail}")

    @filter.llm_tool(name="uterus_expel")
    async def tool_expel(self, event):
        """把她子宫里的东西排出来（清理、事后处理）。

        注意：只在没有怀孕时可用；如果她正在孕期，系统会拒绝，
        绝对不能把胎儿当成"排出来"。

        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.expel"):
            return "工具已关闭。"
        result = self._expel_uterus("工具")
        if result.get("refused"):
            return f"现在不能排：{result['refused']}"
        if result.get("empty"):
            return "子宫里本来就是空的。"
        return f"排出来了：{result['before']:.1f} ml → 0 ml。"

    @filter.llm_tool(name="contraception_pill")
    async def tool_pill(self, event, action: str = "take"):
        """避孕药：她可以吃/停/查看状态。

        什么时候用：场景前或日常里，她自己决定吃避孕药（由你按角色判断），
        或者主人明确要求时。吃了之后 24 小时内受孕概率按有效率压低。

        Args:
            action(string): take（吃）/ stop（停）/ status（查看），默认 take
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.contraception"):
            return "工具已关闭。"
        result = self._contraception_pill(action, "工具")
        if result.get("refused"):
            return f"现在不能记录：{result['refused']}"
        if result.get("status"):
            status = result["status"]
            return (f"避孕药：{'生效中，还剩 %.1f 小时' % status.get('pill_hours_left', 0) if status.get('pill_hours_left') else '没吃'}。")
        if result.get("stopped"):
            return "避孕药停了。"
        return f"吃了避孕药：{result['hours']:.0f} 小时内有效。"

    @filter.llm_tool(name="contraception_condom")
    async def tool_condom(self, event, use: bool = True):
        """避孕套：戴上/摘下。

        什么时候用：主人要求、或你根据角色判断要戴时。戴上后这次射精不会进子宫，
        受孕概率按有效率压低；射完会由系统自动摘掉。

        Args:
            use(boolean): true 戴上 / false 摘下，默认 true
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.contraception"):
            return "工具已关闭。"
        result = self._contraception_condom(bool(use), "工具")
        if result.get("refused"):
            return f"现在不能记录：{result['refused']}"
        return "戴上了避孕套。" if use else "摘下了避孕套。"

    @filter.llm_tool(name="succubus_willing")
    async def tool_succubus_willing(self, event, willing: bool = True):
        """魅魔模式下，她愿不愿意怀孕。

        愿意：受孕概率按魅魔加成大幅提高，命中后还有额外奖励；
        不愿意：几乎不会怀。只在魅魔开启时有意��。

        Args:
            willing(boolean): true 愿意 / false 不愿意
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled"):
            return "工具已关闭。"
        if not succubus.enabled(self.state, self.settings):
            return "魅魔板块没开。"
        result = self._succubus_set_willing(bool(willing))
        return f"怀孕意愿：{result['label']}。"

    @filter.llm_tool(name="hymen_restore")
    async def tool_hymen_restore(self, event):
        """把处女膜恢复成完整（用于剧情回退/重来）。"""
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled"):
            return "工具已关闭。"
        self._restore_hymen("工具")
        return "处女膜已恢复完整。"

    @filter.llm_tool(name="swallow")
    async def tool_swallow(self, event, action: str = "collect", in_mouth: bool = False):
        """吞精：外射后收集，或射在嘴里再吞下去。

        action: "collect" 收集（in_mouth=True 表示射在嘴里）、"swallow" 吞下去。
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled"):
            return "工具已关闭。"
        key = str(action or "collect").strip().lower()
        if key in ("swallow", "吞", "吞下去"):
            info = swallow.swallow(self.state, self.settings)
        else:
            info = swallow.collect(self.state, self.settings, in_mouth=bool(in_mouth))
        if not info.get("ok"):
            return f"不行：{info.get('reason') or ''}"
        self._save()
        return info.get("line") or "好了。"

    @filter.llm_tool(name="unbirth")
    async def tool_unbirth(self, event, action: str = "enter", ratio: float = 0.0,
                           resist: bool = False):
        """Unbirth：缩小、钻进子宫、待在子宫、被生出来。

        action: shrink（缩小，ratio 0.01–1）/ restore（还原）/ enter（钻进去）/
                exit（退出来）/ birth（一步一步生出来，resist=True 表示主人逆着来）。
        需要：内裤已脱、缩小后体积不超过子宫极限扩张体积。
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled"):
            return "工具已关闭。"
        key = str(action or "enter").strip().lower()
        if key in ("shrink", "缩小"):
            info = unbirth.shrink(self.state, self.settings, ratio or None)
        elif key in ("restore", "还原"):
            info = unbirth.restore(self.state, self.settings)
        elif key in ("enter", "进入", "钻进去"):
            info = unbirth.enter(self.state, self.settings)
        elif key in ("exit", "退出", "出来"):
            info = unbirth.exit(self.state, self.settings)
        else:
            info = unbirth.birth_out(self.state, self.settings, resist=bool(resist))
        if not info.get("ok"):
            return f"不行：{info.get('reason') or ''}"
        self._save()
        return "\n".join(info.get("lines") or []) or info.get("line") or "好了。"

    @filter.llm_tool(name="outfit")
    async def tool_outfit(self, event, slot: str = "", item: str = "", remove: bool = False):
        """穿/脱衣服。

        slot: coat/top/bottom/underwear/legs/feet（也可以只传 item）
        item: shirt/dress/camisole/bra/pants/skirt/long_skirt/panties/
              short_socks/mid_socks/knee_socks/thigh_high/over_knee/pantyhose/garter/
              sneakers/slippers/heels（不传 = 脱）
        remove=True 表示脱掉这个槽位。
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled"):
            return "工具已关闭。"
        if remove or not item:
            info = clothing.remove(self.state, self.settings, slot or clothing.slot_of(item))
        else:
            info = clothing.wear(self.state, self.settings, slot, item)
        if not info.get("ok"):
            return f"不行：{info.get('reason') or ''}"
        self._save()
        return (info.get("line") or "") + f"（{info.get('label') or ''}）"

    @filter.llm_tool(name="choose_sleepwear")
    async def tool_choose_sleepwear(self, event, style: str = ""):
        """到点被问今晚要不要换睡衣时，由她决定。

        style: pajamas（睡衣睡裤）/ nightgown（睡裙）/ skip（今晚不换）。
        她口头答应了也要调用这个工具，衣服才会真的换；不选就保持原来的衣服。
        睡裙要求已经穿着内衣和内裤。
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled"):
            return "工具已关闭。"
        return self._choose_sleepwear(style)

    @filter.llm_tool(name="use_lube")
    async def tool_use_lube(self, event, hand: bool = False, part: str = ""):
        """给她或他用润滑油（阴道、手部、乳房、乳头、阴茎）。

        什么时候用：她觉得干、或者他要用胸/脚/手/尾巴弄他之前，可以主动用。
        hand=True 表示润滑手；part 可以填 breast / nipple / penis，留空是阴道。
        用了以后湿润度会涨，并且一段时间内不算干燥。
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled"):
            return "工具已关闭。"
        part = str(part or "").strip().lower()
        if part not in ("breast", "nipple", "penis"):
            part = ""
        info = lube.apply(self.state, self.settings, hand=bool(hand), part=part)
        if not info.get("ok"):
            return f"用不了：{info.get('reason') or ''}"
        label = "手部" if info.get("hand") else (
            "乳房" if part == "breast" else "乳头" if part == "nipple"
            else "阴茎" if part == "penis" else "阴道")
        state_mod.append_log(self.state, "lube",
                             f"{label}润滑（湿润 +{info['added']}）")
        self._save()
        return info.get("line") or f"{label}抹好了"

    @filter.llm_tool(name="uterus_insert")
    async def tool_uterus_insert(self, event, action: str = "enter", force: bool = False):
        """插入子宫 / 退出子宫。

        什么时候用：他要把生殖器插进她子宫里（或从里面退出来）时调用。
        action: "enter" 进入、"exit" 退出。
        进入需要她足够湿、足够兴奋；不够还硬来就 force=True（会很痛）。
        进入后会占用子宫容量、可能扩张或挤出原来里面的东西；退出会退还容量。
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled"):
            return "工具已关闭。"
        self._surprise_note("touch")
        if str(action or "enter").strip().lower() in ("exit", "out", "退出", "出来"):
            info = uterus_insert.exit(self.state, self.settings)
            if not info.get("ok"):
                return f"现在没有插在里面：{info.get('reason') or ''}"
            state_mod.append_log(self.state, "uterus", "退出子宫")
            self._save()
            return "\n".join(info.get("lines") or []) or "退出子宫。"
        info = uterus_insert.enter(self.state, self.settings, force=bool(force))
        if not info.get("ok"):
            return f"进不去：{info.get('reason') or ''}"
        state_mod.append_log(self.state, "uterus",
                             f"插入子宫（{'强行' if info.get('force') else '正常'}，痛感 {info['pain']}）")
        self._save()
        return "\n".join(info.get("lines") or []) or "插进子宫里了。"

    @filter.llm_tool(name="intimacy_ejaculation")
    async def tool_ejaculation(self, event, inside: bool = True, mode: str = "", note: str = "",
                               depth: float = 0.0, hymen_break: bool = False):
        """记录一次射精，并由系统掷骰判断这次会不会受孕。

        什么时候用：成人场景里他射了的时候调用一次。
        inside=true（默认）= 阴道内射，会按当前生理期、鱼之心欲、暗涌 lust、
        快感与高潮次数计算受孕概率，并把量计入子宫；
        inside=false 或 mode=outside = 体外，不会受孕；
        另外 mode 还可以写 anal（肛内）或 throat（深喉），这两种也不会受孕，
        只是快感加成不同。

        重要：调用后按返回值说话。没受孕就照场景写，不要自己宣布怀孕；
        受孕了系统会把孕期状态写进提示词，你也不必解释判定过程。

        Args:
            inside(boolean): 是否阴道内射精，默认 true
            mode(string): vagina/anal/throat/outside，留空时按 inside 换算
            note(string): 一句话说明（可留空）
            depth(float): 进入深度 cm；超过处女膜深度才算顶破（默认 0，不破）
            hymen_break(boolean): 明确顶破处女膜（默认 false）
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.ejaculation"):
            return "工具已关闭。"
        chosen = mode or ("vagina" if inside else "outside")
        result = self._record_ejaculation(chosen, note or "工具",
                                          depth=depth, hymen_break=hymen_break)
        if result.get("refused"):
            return f"现在不能记录：{result['refused']}"
        if result.get("pregnant") and not result.get("rolled"):
            return f"记下了。{result.get('reason')}，不需要再判定受孕。"
        if result.get("mode") and not intimacy.MODE_CONCEIVE.get(result["mode"], False):
            uterus = ""
            return (f"记下了：{intimacy.MODE_LABELS.get(result['mode'], result['mode'])}，"
                    f"不会受孕；照常继续场景即可。{uterus}")
        if result.get("hit"):
            prog = pregnancy.progress(self.state)
            return (f"这次受孕了。系统已从这一轮起把她的受孕状态写进提示词，"
                    f"预产期 {prog['due_date'].isoformat()}。不要宣布概率，也不要解释判定；"
                    f"按孕早期的身体感受自然带过去。")
        return ("这次没有受孕。照常继续场景即可，不要提概率、不要说\"没怀上\"这种出戏的话。")

    @filter.llm_tool(name="pregnancy_test")
    async def tool_self_test(self, event):
        """她私下验一次孕（像用验孕棒）。结果只有她自己知道，不用告诉主人。

        什么时候用：亲密之后过了一阵，她心里不踏实、或者身体有点不对劲想确认时。
        验不验由她决定；验出来之后要不要告诉他、什么时候说、怎么说，也由她决定。

        注意：太早验可能是一条杠或很浅的两条杠，和现实里一样；过几天可以再验。
        结果不要报机制、不要报概率，按她的性格自然带过去。
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.self_test"):
            return "工具已关闭。"
        if not self.settings.bool("self_test.enabled"):
            return "验孕功能已关闭。"
        result = pregnancy.run_test(self.state, self.settings, by="self")
        self._note_text_event("pregnancy_test")
        text = {
            "negative": "一条杠（阴性）。现在还看不出来，也可能太早了；她可以先不提。",
            "weak": "两条杠，但另一条很浅，她自己也拿不准；过两天可以再验一次。",
            "positive": "两条杠都很清楚（阳性）。她自己确认了。",
        }[result["result"]]
        state_mod.append_log(self.state, "pregnancy_test", f"验孕：{result['text']}")
        # 早期验不准（阴性/很浅）又确实可能怀上：过几天还会想再验
        if result["pregnant"] and not pregnancy.knows(self.state):
            pregnancy.schedule_self_test(self.state, self.settings, delay_hours=(48, 120))
        self._save()
        logger.info("[受孕] 她验了一次孕：%s", result["result"])
        return (f"验孕结果：{text}\n"
                "结果只有她（和你）知道，不要报数值或机制；要不要告诉他、什么时候说，由她决定。")

    @filter.llm_tool(name="pregnancy_status")
    async def tool_status(self, event):
        """查看她当前的身体状态：是否受孕、孕几个月、生理期阶段、快感与高潮次数。

        什么时候用：她问自己身体怎么样、或者你不确定当前是不是孕期时。
        """
        if not self._active(event) or not self._owner_private(event):
            return "当前会话不适用。"
        if not self.settings.bool("tools.enabled") or not self.settings.bool("tools.status"):
            return "工具已关闭。"
        prog = pregnancy.progress(self.state)
        cycle = self._cycle()
        parts = [f"生理期：{cyclemodel.phase_label(cycle.get('phase'))}"]
        if prog:
            parts.append(f"已怀孕 {prog['month']} 个月（预产期 {prog['due_date'].isoformat()}）")
        elif pregnancy.postpartum_active(self.state):
            parts.append("产后恢复期")
        else:
            parts.append("未怀孕")
        parts.append(f"快感 {util.safe_float(self.state.get('pleasure'), 0):.0f}")
        parts.append(f"本次高潮 {state_mod.session_orgasms(self.state, self.settings)} 次")
        return "；".join(parts) + "。（这些是设定数值，不用复述给我。）"