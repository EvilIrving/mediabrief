"""Bot 路由：配置下发、状态查询、Token 连通性测试。

配置由前端下发（含跑摘要所需的 LLM 配置快照），BotManager 据此增量启停。
"""
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from bots import bot_manager, BotConfig, LLMConfig
from db import get_task as _db_get_task
from routers.export import _load_text_file, _remove_metadata, _remove_timestamps

logger = logging.getLogger(__name__)
router = APIRouter()

_CONTENT_FIELD = {"transcript": "script", "summary": "summary", "translation": "translation"}
_CONTENT_PATH_FIELD = {
    "transcript": "script_path", "summary": "summary_path", "translation": "translation_path",
}


class LLMConfigBody(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    summary_language: str = "zh"
    whisper_model: str = ""


class BotConfigBody(BaseModel):
    enabled: bool = False
    token: str = ""
    extras: dict = Field(default_factory=dict)


class ConfigureBody(BaseModel):
    # 平台 → 配置；LLM 配置全局共享一份（各平台共用同一套模型设置）。
    bots: dict[str, BotConfigBody] = Field(default_factory=dict)
    llm: LLMConfigBody = Field(default_factory=LLMConfigBody)


@router.post("/api/bots/configure")
async def configure_bots(body: ConfigureBody):
    llm = LLMConfig(
        api_key=body.llm.api_key.strip(),
        base_url=body.llm.base_url.strip().rstrip("/"),
        model=body.llm.model.strip(),
        summary_language=body.llm.summary_language or "zh",
        whisper_model=body.llm.whisper_model.strip(),
    )
    configs = {
        platform: BotConfig(
            enabled=b.enabled,
            token=b.token.strip(),
            llm=llm,
            extras=b.extras,
        )
        for platform, b in body.bots.items()
    }
    results = await bot_manager.apply_configs(configs)
    return {"bots": results}


@router.get("/api/bots/status")
async def bots_status():
    return {"bots": bot_manager.get_all_status()}


class SendBody(BaseModel):
    task_id: str
    content_type: str = "summary"


@router.post("/api/bots/telegram/send")
async def send_telegram(body: SendBody):
    """前端结果页「发送到 Telegram」按钮：把当前 Tab 内容发给配置好的 Chat ID。"""
    task = await _db_get_task(body.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get("status") != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    content_type = body.content_type.lower()
    if content_type not in _CONTENT_FIELD:
        raise HTTPException(status_code=400, detail="不支持的内容类型")

    path = task.get(_CONTENT_PATH_FIELD[content_type])
    content = _load_text_file(Path(path)) if path else (task.get(_CONTENT_FIELD[content_type]) or "")
    if content_type == "transcript":
        content = _remove_timestamps(_remove_metadata(content))
    if not content:
        raise HTTPException(status_code=400, detail="无可用内容")

    title = task.get("video_title") or task.get("safe_title") or ""
    try:
        await bot_manager.send_telegram(title, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


class TestBody(BaseModel):
    platform: str = "telegram"
    token: str = ""
    extras: dict = Field(default_factory=dict)


@router.post("/api/bots/test")
async def test_bot(body: TestBody):
    """校验 Token 连通性，返回 Bot 名称。前端「测试」按钮调用。"""
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="缺少 Token")
    if body.platform == "telegram":
        return await _test_telegram(token)
    if body.platform == "slack":
        return await _test_slack(token, str(body.extras.get("app_token", "")).strip())
    raise HTTPException(status_code=400, detail=f"暂不支持测试: {body.platform}")


async def _test_telegram(token: str):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"无法连接 Telegram: {e}")
    if not data.get("ok"):
        raise HTTPException(status_code=400, detail=data.get("description", "Token 无效"))
    u = data["result"]
    return {"ok": True, "bot_name": u.get("username") or u.get("first_name") or "bot"}


async def _test_slack(bot_token: str, app_token: str):
    if not app_token:
        raise HTTPException(status_code=400, detail="缺少 App Token (xapp-)")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            auth = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"},
            )
            auth_data = auth.json()
            if not auth_data.get("ok"):
                raise HTTPException(status_code=400, detail=f"Bot Token 无效: {auth_data.get('error')}")
            # 验证 app token 能开 Socket Mode 连接。
            conn = await client.post(
                "https://slack.com/api/apps.connections.open",
                headers={"Authorization": f"Bearer {app_token}"},
            )
            conn_data = conn.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"无法连接 Slack: {e}")
    if not conn_data.get("ok"):
        raise HTTPException(status_code=400, detail=f"App Token 无效: {conn_data.get('error')}")
    return {"ok": True, "bot_name": auth_data.get("user") or "bot"}
