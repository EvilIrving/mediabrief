"""应用设置路由：统一持久化前端配置。"""
from fastapi import APIRouter

from settings_store import AppSettings, get_public_settings, save_app_settings, public_settings

router = APIRouter()


@router.get("/api/settings")
async def read_settings():
    """读取安全视图：不返回 API Key / Bot Token / TTS Key 明文。"""
    return await get_public_settings()


@router.put("/api/settings")
async def write_settings(settings: AppSettings):
    saved = await save_app_settings(settings)
    return public_settings(saved)
