"""暗涌（dsh-longing）→ AstrBot 桥接插件。

原版是 DSH 的 JavaScript 插件：每 60 秒算一次七维状态，产出「第一人称状态块」，
由通道插件读文件注入。这里不重写引擎——引擎仍由 Node 独立跑（C:\\DeepSeek\\暗涌\\runner.mjs），
本插件只做两件事：

1. 主人说话 → 推给引擎识别事件（夸奖、拒绝、安全词…），让数值随时间变化；
2. 主人私聊时 → 取引擎写好的状态块，拼进提示词。

设计约束（照原版）：
- 只在「私聊 + 主人」注入；群聊永远零注入。
- 引擎不可用时降级：先试本地注入文件（10 分钟内），再不行就完全不注入，
  绝不用过期或自造的内容糊弄。

作者: 本地部署  版本: 1.0.0
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

SWITCH_FILE = r"C:\DeepSeek\desire_switch.json"


def desire_owner() -> str:
    """谁的欲望说了算：fish / longing / both（由共享开关文件决定）。"""
    try:
        import json as _json
        with open(SWITCH_FILE, encoding="utf-8") as handle:
            value = str(_json.load(handle).get("owner") or "fish").strip().lower()
        return value if value in ("fish", "split", "both") else "fish"
    except Exception:
        return "fish"


PLUGIN_NAME = "astrbot_plugin_longing"
FALLBACK_MAX_AGE = 600          # 兜底文件超过 10 分钟就不用
INJECT_MAX_CHARS = 1200


def _minutes_text(seconds: float) -> str:
    minutes = max(0, int(round(seconds / 60)))
    if minutes < 1:
        return "不到一分钟"
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    return f"{hours} 小时 {rest} 分" if rest else f"{hours} 小时"


@register(PLUGIN_NAME, "Nyakori/DeepSeek", "按七维状态在私聊里注入第一人称状态块", "1.0.0")
class LongingBridge(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self._last_block = ""

    # ---------- 小工具 ----------

    def _cfg(self, key, default=None):
        value = self.config.get(key, default) if hasattr(self.config, "get") else default
        return default if value is None else value

    def _url(self, path: str) -> str:
        base = str(self._cfg("runner_url", "http://127.0.0.1:6399")).rstrip("/")
        return base + path

    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None):
        """访问运行器；失败返回 None，不抛异常。"""
        timeout = timeout or float(self._cfg("timeout_seconds", 3) or 3)
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self._url(path), data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError):
            return None
        except Exception as error:  # 兜底：桥接失败不能影响聊天
            logger.debug("[Longing] 请求失败 %s: %s", path, error)
            return None

    def _owner_qq(self) -> str:
        return str(self._cfg("owner_qq", "") or "").strip()

    def _is_owner_private(self, event: AstrMessageEvent) -> bool:
        owner = self._owner_qq()
        if not owner:
            return False
        try:
            if not event.is_private_chat():
                return False
            return str(event.get_sender_id()) == owner
        except Exception:
            return False

    # ---------- 兜底：读运行器写的注入文件 ----------

    def _file_block(self) -> str:
        path = Path(str(self._cfg("fallback_file", "")))
        try:
            if not path.is_file():
                return ""
            if time.time() - path.stat().st_mtime > FALLBACK_MAX_AGE:
                return ""
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    # ---------- 注入 ----------

    @filter.on_llm_request(priority=130)
    async def inject_desire_block(self, event: AstrMessageEvent, req):
        if self._cfg("enabled", True) is not True:
            return
        if desire_owner() == "fish":
            return          # 现在归鱼的心管，暗涌完全静默
        if not self._is_owner_private(event):
            return

        # 1) 先把主人这句话推给引擎，让事件即时生效（失败不影响注入）
        if self._cfg("feed_events", True) is True:
            text = str(getattr(event, "message_str", "") or "").strip()
            if text:
                self._request("/note", {"text": text[:500],
                                        "channel": self._cfg("channel", "qq")}, timeout=2)

        # 2) 取状态块：引擎优先，文件兜底
        block = ""
        payload = self._request("/block?channel=" + str(self._cfg("channel", "qq")))
        if isinstance(payload, dict) and payload.get("ok"):
            block = str(payload.get("block") or "").strip()
        source = "runner"
        if not block:
            block = self._file_block()
            source = "file"
        if not block:
            return

        limit = int(self._cfg("max_block_chars", INJECT_MAX_CHARS) or INJECT_MAX_CHARS)
        if len(block) > limit:
            block = block[:limit]

        mode = str(self._cfg("inject_mode", "system") or "system").lower()
        if mode == "temp":
            parts = getattr(req, "extra_user_content_parts", None)
            if isinstance(parts, list):
                from astrbot.core.agent.message import TextPart
                parts.append(TextPart(text="\n" + block))
            else:
                req.system_prompt = (getattr(req, "system_prompt", "") or "") + "\n" + block
        else:
            req.system_prompt = (getattr(req, "system_prompt", "") or "") + "\n" + block

        if block != self._last_block:
            self._last_block = block
            logger.info("[Longing] 已注入状态块（来源 %s，%d 字）", source, len(block))

    # ---------- 命令 ----------

    @filter.command("暗涌状态")
    async def show_state(self, event: AstrMessageEvent):
        if not self._is_owner_private(event):
            yield event.plain_result("这个只在主人的私聊里看。")
            return
        payload = self._request("/state")
        if not isinstance(payload, dict) or not payload.get("ok"):
            yield event.plain_result("连不上暗涌运行器（它没在跑？）。")
            return
        dims = payload.get("dims") or {}
        names = {"lust": "性欲", "lewd": "色情", "possess": "占有", "shame": "羞耻",
                 "resist": "理智", "fatigue": "疲劳", "affection": "好感"}
        lines = [f"{names.get(k, k)}：{float(v):.1f}" for k, v in dims.items()]
        paused = float(payload.get("pausedUntil") or 0)
        if paused > time.time() / 1000:
            lines.append(f"暂停中，还剩 {_minutes_text(paused - time.time() / 1000)}")
        yield event.plain_result("当前七维：\n" + "\n".join(lines))

    @filter.command("暗涌暂停")
    async def pause(self, event: AstrMessageEvent):
        if not self._is_owner_private(event):
            yield event.plain_result("只有主人能暂停。")
            return
        minutes = 30
        parts = str(getattr(event, "message_str", "") or "").split()
        if len(parts) > 1 and parts[-1].isdigit():
            minutes = max(1, min(720, int(parts[-1])))
        payload = self._request("/pause", {"minutes": minutes})
        if isinstance(payload, dict) and payload.get("ok"):
            yield event.plain_result(f"好，暂停 {minutes} 分钟，期间不注入欲望状态。")
        else:
            yield event.plain_result("暂停失败：运行器没响应。")

    @filter.command("暗涌继续")
    async def resume(self, event: AstrMessageEvent):
        if not self._is_owner_private(event):
            yield event.plain_result("只有主人能恢复。")
            return
        payload = self._request("/pause", {"minutes": 0})
        if isinstance(payload, dict) and payload.get("ok"):
            yield event.plain_result("好，恢复。")
        else:
            yield event.plain_result("恢复失败：运行器没响应。")
