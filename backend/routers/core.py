"""核心路由：前端入口页与模型列表代理。"""
import asyncio
import logging

import openai
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse

from task_store import PROJECT_ROOT
import whisper_models

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def read_root():
    """返回前端页面（React SPA 构建产物）"""
    return FileResponse(str(PROJECT_ROOT / "static" / "index.html"))


@router.post("/api/models")
async def list_models(
    base_url: str = Form(default=""),
    api_key: str = Form(default=""),
):
    """Proxy: fetch model list from any OpenAI-compatible API."""
    effective_key = api_key
    effective_url = base_url.rstrip("/") or None

    if not effective_key:
        raise HTTPException(status_code=400, detail="API key is required")

    try:
        client = openai.OpenAI(api_key=effective_key, base_url=effective_url)
        resp = await asyncio.to_thread(client.models.list)
        models = [{"id": m.id, "name": getattr(m, "name", m.id)} for m in resp.data]
        # Sort by id for readability
        models.sort(key=lambda x: x["id"])
        return {"data": models}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/whisper-models")
async def whisper_models_list():
    """列出可选 Whisper 模型及其本地下载状态。"""
    return {"data": whisper_models.list_models(), "default": whisper_models.DEFAULT_MODEL}


@router.post("/api/whisper-models/download")
async def whisper_model_download(
    size: str = Form(...),
    hf_endpoint: str = Form(default=""),
):
    """下载指定 Whisper 模型到本地缓存。阻塞至完成，前端凭返回状态刷新列表。

    hf_endpoint 非空时仅本次下载临时生效（镜像/代理），默认走官方 Hugging Face。
    """
    if size not in whisper_models.CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown model size: {size}")
    if whisper_models.is_downloaded(size):
        return {"size": size, "downloaded": True}
    try:
        await asyncio.to_thread(whisper_models.download, size, hf_endpoint)
    except Exception as e:
        logger.warning("Whisper 模型 %s 下载失败: %s", size, e)
        raise HTTPException(status_code=502, detail=f"下载失败: {e}")
    return {"size": size, "downloaded": whisper_models.is_downloaded(size)}


