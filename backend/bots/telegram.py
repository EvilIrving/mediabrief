"""Telegram Bot：长轮询（getUpdates）接收消息，零额外依赖（复用 httpx）。

流程：getUpdates 拉取 → 正则提取 URL → 回复「开始处理」→ 复用统一队列跑管线
→ sendMessage 发摘要（按 4096 上限分片）→ sendDocument 发完整转录 .md。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import httpx

from .base import BaseBot, BotConfig, BotStatus
from .common import extract_url, run_transcription, split_long_message

logger = logging.getLogger(__name__)

# Telegram sendMessage 单条上限 4096 字符，留出余量分片。
_TG_MSG_LIMIT = 4000
_GET_UPDATES_TIMEOUT = 30


class TelegramBot(BaseBot):
    platform = "telegram"

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._status = BotStatus.STOPPED
        self._last_error: Optional[str] = None
        self._bot_name: str = ""
        self._messages_processed = 0
        self._started_at: float = 0.0
        self._token = ""
        self._chat_id = ""

    # ── 生命周期 ──────────────────────────────────────────────
    async def start(self, config: BotConfig) -> None:
        await self.stop()
        self._token = config.token.strip()
        self._llm = config.llm
        self._chat_id = str(config.extras.get("chat_id") or "").strip()
        self._status = BotStatus.STARTING
        self._last_error = None

        # 启动前先校验 token（getMe），失败则直接进入 ERROR，不挂空轮询。
        bot_name = await self._get_me(self._token)
        if not bot_name:
            self._status = BotStatus.ERROR
            self._last_error = "Bot Token 无效"
            raise ValueError(self._last_error)

        self._bot_name = bot_name
        self._started_at = time.time()
        self._task = asyncio.create_task(self._polling_loop())
        self._status = BotStatus.RUNNING
        logger.info("Telegram Bot 已启动: @%s", bot_name)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        self._status = BotStatus.STOPPED

    def get_status(self) -> dict:
        uptime = int(time.time() - self._started_at) if self._status == BotStatus.RUNNING else 0
        return {
            "status": self._status.value,
            "uptime_seconds": uptime,
            "messages_processed": self._messages_processed,
            "last_error": self._last_error,
            "bot_name": self._bot_name,
        }

    # ── Telegram API 封装 ────────────────────────────────────
    async def _get_me(self, token: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            data = resp.json()
            if data.get("ok"):
                u = data["result"]
                return u.get("username") or u.get("first_name") or "bot"
        except Exception as e:
            logger.warning("Telegram getMe 失败: %s", e)
        return None

    async def _api(self, method: str, **params) -> dict:
        assert self._client is not None
        resp = await self._client.post(
            f"https://api.telegram.org/bot{self._token}/{method}", data=params
        )
        return resp.json()

    async def _send_message(self, chat_id: int, text: str) -> None:
        for chunk in split_long_message(text, _TG_MSG_LIMIT):
            await self._api("sendMessage", chat_id=chat_id, text=chunk)

    async def send_text(self, title: str, text: str) -> None:
        """供网页端「发送到 Telegram」按钮调用：发到配置好的默认 Chat ID。"""
        if self._status != BotStatus.RUNNING or self._client is None:
            raise ValueError("Telegram Bot 未运行")
        if not self._chat_id:
            raise ValueError("未配置接收 Chat ID（在 Bot 设置中填写）")
        body = f"{title}\n\n{text}" if title else text
        await self._send_message(self._chat_id, body)

    async def _send_document(self, chat_id: int, path, caption: str = "") -> None:
        assert self._client is not None
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption[:1024]  # Telegram caption 上限 1024
        with open(path, "rb") as f:
            await self._client.post(
                f"https://api.telegram.org/bot{self._token}/sendDocument",
                data=data,
                files={"document": (path.name, f, "text/markdown")},
            )

    # ── 长轮询主循环 ─────────────────────────────────────────
    async def _polling_loop(self) -> None:
        self._client = httpx.AsyncClient(timeout=_GET_UPDATES_TIMEOUT + 10)
        offset = 0
        while True:
            try:
                resp = await self._client.get(
                    f"https://api.telegram.org/bot{self._token}/getUpdates",
                    params={"offset": offset, "timeout": _GET_UPDATES_TIMEOUT,
                            "allowed_updates": '["message"]'},
                )
                data = resp.json()
                if not data.get("ok"):
                    self._last_error = data.get("description", "getUpdates 失败")
                    await asyncio.sleep(3)
                    continue
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    # 每条消息独立处理，避免一条长任务阻塞后续拉取。
                    asyncio.create_task(self._handle_update(update))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._last_error = str(e)
                logger.warning("Telegram 轮询出错，3 秒后重试: %s", e)
                await asyncio.sleep(3)

    async def _handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = message.get("text", "") or message.get("caption", "")
        if chat_id is None:
            return

        url = extract_url(text)
        if not url:
            await self._send_message(
                chat_id,
                "请发送一个链接，支持 YouTube / Bilibili / TikTok / 播客等 30+ 平台。",
            )
            return

        self._messages_processed += 1
        await self._send_message(chat_id, f"⏳ 开始处理：{url}")
        try:
            await self._api("sendChatAction", chat_id=chat_id, action="typing")
            result = await run_transcription(url, self._llm)
            if result.status == "completed":
                # 回传用文件更合适：摘要 + 全文合并为 .md 文档发送。
                title = result.video_title or "处理完成"
                if result.result_path:
                    await self._api("sendChatAction", chat_id=chat_id, action="upload_document")
                    await self._send_document(chat_id, result.result_path, caption=f"✅ {title}")
                else:
                    await self._send_message(chat_id, f"✅ {title}\n\n{result.summary or '（无内容）'}")
            else:
                await self._send_message(chat_id, f"❌ 处理失败：{result.error}")
        except Exception as e:
            logger.error("Telegram 处理消息失败: %s", e, exc_info=True)
            await self._send_message(chat_id, f"❌ 处理失败：{e}")
