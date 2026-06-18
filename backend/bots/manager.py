"""BotManager：按平台维护 Bot 单例，对比新旧配置做增量启停。

配置由前端 POST /api/bots/configure 下发，BotManager 持有运行期实例。
后端无状态约定的例外：Bot 是常驻连接，配置随前端保存时下发并在内存中保留，
后端重启后由前端再次推送恢复（与浏览器里保存的 API key 同理）。
"""
from __future__ import annotations

import logging
from typing import Type

from .base import BaseBot, BotConfig, BotStatus
from .slack import SlackBot
from .telegram import TelegramBot

logger = logging.getLogger(__name__)

# 平台 → Bot 实现。新增平台时在此登记。
_BOT_CLASSES: dict[str, Type[BaseBot]] = {
    "telegram": TelegramBot,
    "slack": SlackBot,
}


class BotManager:
    def __init__(self) -> None:
        self._bots: dict[str, BaseBot] = {}

    async def apply_configs(self, configs: dict[str, BotConfig]) -> dict:
        """启用的平台启动/重启，未启用或移除的平台停止；返回各平台状态摘要。"""
        results: dict[str, dict] = {}
        for platform, cfg in configs.items():
            cls = _BOT_CLASSES.get(platform)
            if cls is None:
                results[platform] = {"status": "error", "message": f"未支持的平台: {platform}"}
                continue

            bot = self._bots.get(platform)
            if not cfg.enabled:
                if bot:
                    await bot.stop()
                results[platform] = {"status": BotStatus.STOPPED.value, "message": "未启用"}
                continue

            if bot is None:
                bot = cls()
                self._bots[platform] = bot
            try:
                await bot.start(cfg)
                results[platform] = {"status": BotStatus.RUNNING.value, "message": "已启动"}
            except Exception as e:
                logger.warning("启动 %s Bot 失败: %s", platform, e)
                results[platform] = {"status": BotStatus.ERROR.value, "message": str(e)}

        return results

    def get_all_status(self) -> dict:
        return {platform: bot.get_status() for platform, bot in self._bots.items()}

    async def send_telegram(self, title: str, text: str) -> None:
        """供网页端「发送到 Telegram」按钮调用。"""
        bot = self._bots.get("telegram")
        if bot is None or not isinstance(bot, TelegramBot):
            raise ValueError("Telegram Bot 未启用")
        await bot.send_text(title, text)

    async def shutdown(self) -> None:
        for bot in self._bots.values():
            try:
                await bot.stop()
            except Exception as e:
                logger.warning("停止 Bot 失败: %s", e)


bot_manager = BotManager()
