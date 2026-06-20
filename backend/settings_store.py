"""统一应用设置持久化。

前端可把 LLM、Bot、TTS 与转录偏好保存到 SQLite。GET 接口只返回安全视图，
真正执行任务和启动 Bot 时由后端读取完整配置，避免把密钥重新暴露给页面。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from db import app_config_delete, app_config_get, app_config_set

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "app_settings"
_LEGACY_BOT_KEY = "bot_configs"


class ModelInfo(BaseModel):
    id: str = ""
    name: str | None = None


class BotPlatformSettings(BaseModel):
    enabled: bool = False
    token: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)


class TtsSettings(BaseModel):
    enabled: bool = False
    apiKey: str = ""
    speaker: str = ""
    resourceId: str = "seed-tts-2.0"


class AppSettings(BaseModel):
    baseUrl: str = ""
    apiKey: str = ""
    model: str = ""
    summaryLang: str = "en"
    useTwoStep: bool = True
    models: list[ModelInfo] = Field(default_factory=list)
    whisperModel: str = "base"
    hfEndpoint: str = ""
    browserCookiesAutoDetect: bool = False
    botConfigs: dict[str, BotPlatformSettings] = Field(default_factory=dict)
    ttsConfig: TtsSettings = Field(default_factory=TtsSettings)


def _dump(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()  # pydantic v2
    return model.dict()  # pydantic v1 fallback


def _validate(data: Any) -> AppSettings:
    if isinstance(data, AppSettings):
        return data
    if not isinstance(data, dict):
        data = {}
    if hasattr(AppSettings, "model_validate"):
        return AppSettings.model_validate(data)  # type: ignore[attr-defined]
    return AppSettings.parse_obj(data)


def _deep_merge_preserve_secrets(incoming: AppSettings, current: AppSettings) -> AppSettings:
    """合并设置；空 secret 表示“未改动”，保留 DB 中旧值。

    设置页从 GET 拿到的是安全视图，token/apiKey 字段会是空串。用户不重新输入时，
    PUT 不应清掉已有密钥；用户输入非空值时才覆盖。
    """
    data = _dump(incoming)
    cur = _dump(current)

    if not data.get("apiKey") and cur.get("apiKey"):
        data["apiKey"] = cur["apiKey"]

    tts = data.setdefault("ttsConfig", {})
    cur_tts = cur.get("ttsConfig", {}) or {}
    if not tts.get("apiKey") and cur_tts.get("apiKey"):
        tts["apiKey"] = cur_tts["apiKey"]

    bots = data.setdefault("botConfigs", {})
    cur_bots = cur.get("botConfigs", {}) or {}
    for platform, cfg in bots.items():
        if not isinstance(cfg, dict):
            continue
        cur_cfg = cur_bots.get(platform, {}) if isinstance(cur_bots.get(platform), dict) else {}
        if not cfg.get("token") and cur_cfg.get("token"):
            cfg["token"] = cur_cfg["token"]
        extras = cfg.setdefault("extras", {})
        cur_extras = cur_cfg.get("extras", {}) if isinstance(cur_cfg.get("extras"), dict) else {}
        # 平台 extras 里可能包含 Slack app_token 这类 secret。空串视为未改动。
        for key, value in cur_extras.items():
            if extras.get(key, None) in (None, "") and value:
                extras[key] = value

    return _validate(data)


async def get_app_settings() -> AppSettings:
    raw = await app_config_get(_SETTINGS_KEY)
    if not raw:
        return AppSettings()
    try:
        return _validate(json.loads(raw))
    except Exception as e:
        logger.warning("应用设置损坏，已回退默认值: %s", e)
        return AppSettings()


async def save_app_settings(settings: AppSettings | dict[str, Any], *, preserve_secrets: bool = True) -> AppSettings:
    incoming = _validate(settings)
    current = await get_app_settings()
    merged = _deep_merge_preserve_secrets(incoming, current) if preserve_secrets else incoming
    await app_config_set(_SETTINGS_KEY, json.dumps(_dump(merged), ensure_ascii=False))
    return merged


def public_settings(settings: AppSettings) -> dict[str, Any]:
    """返回前端可安全读取的设置视图，不包含明文密钥。"""
    data = _dump(settings)
    data["apiKey"] = ""
    data["apiKeyConfigured"] = bool(settings.apiKey.strip())

    tts = data.get("ttsConfig", {}) or {}
    tts["apiKey"] = ""
    tts["apiKeyConfigured"] = bool(settings.ttsConfig.apiKey.strip())
    data["ttsConfig"] = tts

    public_bots: dict[str, dict[str, Any]] = {}
    for platform, cfg in settings.botConfigs.items():
        item = _dump(cfg)
        item["token"] = ""
        item["tokenConfigured"] = bool(cfg.token.strip())
        extras = dict(cfg.extras or {})
        # Slack app_token 是 secret；chat_id 这类目标 ID 保留，方便用户看到。
        if "app_token" in extras:
            extras["app_token"] = ""
            item["appTokenConfigured"] = bool(str(cfg.extras.get("app_token", "")).strip())
        item["extras"] = extras
        public_bots[platform] = item
    data["botConfigs"] = public_bots
    return data


async def get_public_settings() -> dict[str, Any]:
    return public_settings(await get_app_settings())


async def merge_bot_settings(bot_configs: dict[str, dict[str, Any]], llm: dict[str, Any]) -> AppSettings:
    current = await get_app_settings()
    data = _dump(current)
    data["botConfigs"] = bot_configs
    if llm:
        if "api_key" in llm:
            data["apiKey"] = llm.get("api_key") or data.get("apiKey", "")
        if "base_url" in llm:
            data["baseUrl"] = llm.get("base_url") or data.get("baseUrl", "")
        if "model" in llm:
            data["model"] = llm.get("model") or data.get("model", "")
        if "summary_language" in llm:
            data["summaryLang"] = llm.get("summary_language") or data.get("summaryLang", "en")
        if "whisper_model" in llm:
            data["whisperModel"] = llm.get("whisper_model") or data.get("whisperModel", "base")
    return await save_app_settings(data)


async def fill_llm_defaults(
    summary_language: str = "",
    api_key: str = "",
    model_base_url: str = "",
    model_id: str = "",
    whisper_model: str = "",
    auto_detect_browser_cookies: bool = False,
) -> dict[str, Any]:
    settings = await get_app_settings()
    return {
        "summary_language": summary_language or settings.summaryLang or "zh",
        "api_key": api_key or settings.apiKey,
        "model_base_url": model_base_url or settings.baseUrl,
        "model_id": model_id or settings.model,
        "whisper_model": whisper_model or settings.whisperModel,
        "auto_detect_browser_cookies": bool(auto_detect_browser_cookies or settings.browserCookiesAutoDetect),
    }


async def migrate_legacy_bot_configs() -> None:
    raw = await app_config_get(_LEGACY_BOT_KEY)
    if not raw:
        return
    try:
        legacy = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        await app_config_delete(_LEGACY_BOT_KEY)
        return
    if not isinstance(legacy, dict):
        await app_config_delete(_LEGACY_BOT_KEY)
        return

    current = await get_app_settings()
    data = _dump(current)
    if not data.get("botConfigs"):
        bot_configs: dict[str, dict[str, Any]] = {}
        for platform, cfg in legacy.items():
            if not isinstance(cfg, dict):
                continue
            bot_configs[platform] = {
                "enabled": bool(cfg.get("enabled", False)),
                "token": cfg.get("token", ""),
                "extras": cfg.get("extras", {}) if isinstance(cfg.get("extras"), dict) else {},
            }
            llm = cfg.get("llm", {}) if isinstance(cfg.get("llm"), dict) else {}
            data["apiKey"] = data.get("apiKey") or llm.get("api_key", "")
            data["baseUrl"] = data.get("baseUrl") or llm.get("base_url", "")
            data["model"] = data.get("model") or llm.get("model", "")
            data["summaryLang"] = data.get("summaryLang") or llm.get("summary_language", "en")
            data["whisperModel"] = data.get("whisperModel") or llm.get("whisper_model", "base")
        data["botConfigs"] = bot_configs
        await save_app_settings(data, preserve_secrets=False)
    await app_config_delete(_LEGACY_BOT_KEY)
