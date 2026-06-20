"""BotManager：按平台维护 Bot 单例，对比新旧配置做增量启停。

配置由前端 POST /api/bots/configure 下发，持久化到统一 app_settings。
后端重启时自动从 DB 恢复上次保存的配置并启动对应 Bot。
"""
from __future__ import annotations

import logging
from typing import Type

from settings_store import get_app_settings, merge_bot_settings

from .base import BaseBot, BotConfig, BotStatus, LLMConfig
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

    async def restore_from_db(self) -> dict:
        """启动时从统一设置恢复上次保存的配置，启动对应 Bot。"""
        saved = await get_app_settings()
        llm = LLMConfig(
            api_key=saved.apiKey,
            base_url=saved.baseUrl,
            model=saved.model,
            summary_language=saved.summaryLang or "zh",
            whisper_model=saved.whisperModel,
        )
        configs: dict[str, BotConfig] = {}
        for platform, data in saved.botConfigs.items():
            configs[platform] = BotConfig(
                enabled=data.enabled,
                token=data.token,
                llm=llm,
                extras=data.extras,
            )
        return await self.apply_configs(configs)

    async def apply_configs(self, configs: dict[str, BotConfig]) -> dict:
        """启用的平台启动/重启，未启用或移除的平台停止；返回各平台状态摘要。"""
        # 持久化到统一设置。空 token/extras secret 在 settings_store 中按“未改动”处理。
        serializable: dict[str, dict] = {}
        llm_snapshot: dict = {}
        for platform, cfg in configs.items():
            serializable[platform] = {
                "enabled": cfg.enabled,
                "token": cfg.token,
                "extras": cfg.extras,
            }
            llm_snapshot = {
                "api_key": cfg.llm.api_key,
                "base_url": cfg.llm.base_url,
                "model": cfg.llm.model,
                "summary_language": cfg.llm.summary_language,
                "whisper_model": cfg.llm.whisper_model,
            }
        await merge_bot_settings(serializable, llm_snapshot)

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
