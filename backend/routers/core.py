"""核心路由：前端入口页、模型列表代理与诊断/日志访问。"""
import asyncio
import logging
import sys
from collections import deque

import openai
from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from logging_config import get_log_file
from task_store import PROJECT_ROOT, TEMP_DIR
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


@router.get("/api/diagnostics")
async def diagnostics():
    """运行环境诊断信息，供「设置/关于」页展示与用户反馈问题时一键复制。

    暴露日志文件路径是关键：打包后日志在 Application Support 等隐蔽目录，
    用户几乎找不到。这里直接给出路径，并配合 /api/logs 让其在应用内查看/导出。
    """
    import shutil

    log_file = get_log_file()
    ffmpeg = shutil.which("ffmpeg")
    deno = shutil.which("deno")
    try:
        import faster_whisper
        fw_ver = getattr(faster_whisper, "__version__", "?")
    except Exception:
        fw_ver = "未安装"
    try:
        import yt_dlp
        ytdlp_ver = getattr(yt_dlp.version, "__version__", "?")
    except Exception:
        ytdlp_ver = "未安装"

    return {
        "platform": sys.platform,
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "data_dir": str(TEMP_DIR),
        "log_file": str(log_file),
        "log_exists": log_file.exists(),
        "log_size_kb": round(log_file.stat().st_size / 1024, 1) if log_file.exists() else 0,
        "ffmpeg": ffmpeg or "未找到",
        "deno": deno or "未找到",
        "faster_whisper": fw_ver,
        "yt_dlp": ytdlp_ver,
    }


@router.get("/api/logs", response_class=PlainTextResponse)
async def view_logs(lines: int = Query(default=500, ge=1, le=5000)):
    """返回日志文件末尾 N 行（纯文本），供应用内「查看日志」并一键复制。"""
    log_file = get_log_file()
    if not log_file.exists():
        return PlainTextResponse("（日志文件尚未生成）", media_type="text/plain; charset=utf-8")

    def _tail() -> str:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            return "".join(deque(f, maxlen=lines))

    content = await asyncio.to_thread(_tail)
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")


@router.get("/api/logs/download")
async def download_logs():
    """下载完整日志文件，便于用户反馈问题时直接附上。"""
    log_file = get_log_file()
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="日志文件尚未生成")
    return FileResponse(str(log_file), filename="ai-transcriber.log", media_type="text/plain")


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


