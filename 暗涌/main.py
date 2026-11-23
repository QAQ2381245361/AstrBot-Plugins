"""欲望归属：把设置里的档位写成共享开关，并负责暗涌引擎的启动/停止。

设计：
- 这张卡片就是「暗涌」的总开关：
    打开卡片 → 写归属（默认暗涌全权）+ 启动引擎（runner.mjs）
    关闭卡片 → 把归属交还鱼之心 + 停掉引擎
- 防抖：关卡片时先写 want=false、等 2 秒再复查；
  这 2 秒内又被打开（want=true）就不杀引擎，避免快速反复开关时把进程切碎。
- 引擎已经在跑（比如手动启动过）→ 直接复用，不重复启动。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path

from astrbot.api import logger
from astrbot.api.star import Context, Star, register

SWITCH = Path(r"C:\DeepSeek\desire_switch.json")
LONGING_DIR = Path(r"C:\DeepSeek\longing")
RUNNER = LONGING_DIR / "runner.mjs"
NODE = Path(r"C:\DeepSeek\SnowLuma\node.exe")
ENGINE_STATE = LONGING_DIR / "engine_state.json"
RUNNER_LOG = LONGING_DIR / "runner.log"
HOST, PORT = "127.0.0.1", 6399
STOP_DELAY = 4.0            # 关卡片后等多久再杀引擎（防抖 + 重启窗口）

VALID = ("longing", "split", "fish")
LABELS = {"longing": "默认·暗涌全权", "split": "分工（鱼之心九维 + 暗涌欲望）", "fish": "只有鱼之心"}


def _port_open(host: str = HOST, port: int = PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.6)
        return sock.connect_ex((host, port)) == 0


def _write_engine_state(want: bool, instance: str = "") -> None:
    """want=想要引擎开着吗；instance=写这条记录的插件实例。"""
    try:
        ENGINE_STATE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"want": bool(want), "instance": instance, "ts": time.time()}
        tmp = ENGINE_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(ENGINE_STATE)
    except Exception:
        pass


def _read_engine_state() -> dict:
    try:
        return json.loads(ENGINE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_engine_want() -> bool:
    return bool(_read_engine_state().get("want"))


def _read_engine_want() -> bool:
    try:
        return bool(json.loads(ENGINE_STATE.read_text(encoding="utf-8")).get("want"))
    except Exception:
        return False


def _spawn_engine() -> bool:
    """启动引擎；已经在跑就直接复用。"""
    if _port_open():
        logger.info("[DesireOwner] 引擎已在运行（端口 %s），直接复用", PORT)
        return True
    if not NODE.is_file() or not RUNNER.is_file():
        logger.warning("[DesireOwner] 找不到 node 或 runner.mjs，跳过后台引擎")
        return False
    try:
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        with open(RUNNER_LOG, "a", encoding="utf-8") as log:
            subprocess.Popen([str(NODE), str(RUNNER)], cwd=str(LONGING_DIR),
                             stdout=log, stderr=subprocess.STDOUT,
                             creationflags=flags, close_fds=True)
        logger.info("[DesireOwner] 引擎已启动（%s）", RUNNER)
        return True
    except Exception as error:
        logger.warning("[DesireOwner] 启动引擎失败：%s", error)
        return False


def _stop_engine() -> None:
    """按端口找进程并结束；只杀 node，避免误伤别的程序。"""
    if not _port_open():
        logger.info("[DesireOwner] 引擎本来就没在跑")
        return
    try:
        output = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=10).stdout
    except Exception as error:
        logger.warning("[DesireOwner] 查端口失败：%s", error)
        return
    pids = set()
    for line in output.splitlines():
        if f":{PORT}" in line and "LISTENING" in line.upper():
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(parts[-1])
    for pid in pids:
        try:
            info = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=10).stdout
            if "node" not in info.lower():
                logger.info("[DesireOwner] 端口 %s 的占用者不是 node，不动它", PORT)
                continue
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10)
            logger.info("[DesireOwner] 已停止引擎（pid %s）", pid)
        except Exception as error:
            logger.warning("[DesireOwner] 停止引擎失败 pid=%s：%s", pid, error)


@register("astrbot_plugin_desire_owner", "Nyakori/DeepSeek", "决定欲望归鱼之心还是暗涌，并随卡片启停引擎", "1.2.0")
class DesireOwner(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self.owner = self._write_switch()
        self.instance = uuid.uuid4().hex[:12]
        _write_engine_state(True, self.instance)
        _spawn_engine()

    def _write_switch(self) -> str:
        try:
            value = str(self.config.get("owner") or "longing").strip().lower()
        except Exception:
            value = "longing"
        if value not in VALID:
            value = "longing"
        try:
            SWITCH.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "owner": value,
                "note": "longing=暗涌全权；split=鱼之心九维+暗涌欲望；fish=只有鱼之心",
                "written_by": "astrbot_plugin_desire_owner",
            }
            tmp = SWITCH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(SWITCH)
            logger.info("[DesireOwner] 欲望归属已写入：%s（%s）", value, LABELS.get(value, value))
        except Exception as error:
            logger.warning("[DesireOwner] 写开关失败：%s", error)
        return value

    async def terminate(self):
        """卡片关闭：先交还归属，再延时停引擎（期间若被重新打开就不停）。"""
        try:
            payload = {"owner": "fish",
                       "note": "longing=暗涌全权；split=鱼之心九维+暗涌欲望；fish=只有鱼之心",
                       "written_by": "astrbot_plugin_desire_owner(terminate)"}
            tmp = SWITCH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(SWITCH)
            logger.info("[DesireOwner] 卡片关闭，归属交还鱼之心")
        except Exception as error:
            logger.warning("[DesireOwner] 交还失败：%s", error)

        _write_engine_state(False, self.instance)
        await asyncio.sleep(STOP_DELAY)
        latest = _read_engine_state()
        if latest.get("want") or (latest.get("instance") and latest["instance"] != self.instance):
            # 两种放行：卡片在这几秒内又被打开；或者已经换了新实例（重启场景）
            logger.info("[DesireOwner] 卡片重开或实例已更换，保留引擎")
            return
        await asyncio.to_thread(_stop_engine)
