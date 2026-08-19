"""核心路由：前端入口页、模型列表代理与诊断/日志访问。"""
import asyncio
import logging
import os
import subprocess
import sys
from collections import deque
from pathlib import Path

import openai
from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from logging_config import get_log_file
from app_version import APP_VERSION
from task_store import PROJECT_ROOT, TEMP_DIR
from settings_store import get_app_settings
from release_config import get_release_llm_config
import whisper_models
import yt_dlp_updater

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
    saved = await get_app_settings()
    effective_key = api_key or saved.apiKey
    effective_url = (base_url or saved.baseUrl).rstrip("/") or None

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
    # 用后端实际解析到的绝对路径（含打包内置），而非仅查 PATH。
    from video_processor import FFMPEG_BIN, FFPROBE_BIN
    ffmpeg = FFMPEG_BIN if (os.path.sep in FFMPEG_BIN and Path(FFMPEG_BIN).exists()) else shutil.which("ffmpeg")
    ffprobe = FFPROBE_BIN if (os.path.sep in FFPROBE_BIN and Path(FFPROBE_BIN).exists()) else shutil.which("ffprobe")
    deno = shutil.which("deno")

    def _tool_version(binary: str | None, *args: str) -> str:
        if not binary:
            return "未找到"
        try:
            result = subprocess.run(
                [binary, *args], capture_output=True, text=True, timeout=5, check=False,
            )
            first_line = (result.stdout or result.stderr).splitlines()[0]
            return first_line.strip() or "版本未知"
        except (OSError, subprocess.SubprocessError, IndexError):
            return "版本未知"
    try:
        import mlx_whisper
        import mlx
        asr_ver = f"mlx-whisper {getattr(mlx_whisper, '__version__', '?')} / mlx {getattr(mlx, '__version__', '?')}"
    except Exception:
        asr_ver = "未安装"
    try:
        import yt_dlp
        ytdlp_ver = getattr(yt_dlp.version, "__version__", "?")
    except Exception:
        ytdlp_ver = "未安装"

    release_llm = get_release_llm_config()
    return {
        "platform": sys.platform,
        "app_version": APP_VERSION,
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "data_dir": str(TEMP_DIR),
        "log_file": str(log_file),
        "log_exists": log_file.exists(),
        "log_size_kb": round(log_file.stat().st_size / 1024, 1) if log_file.exists() else 0,
        "ffmpeg": ffmpeg or "未找到",
        "ffmpeg_version": _tool_version(ffmpeg, "-version"),
        "ffprobe": ffprobe or "未找到",
        "ffprobe_version": _tool_version(ffprobe, "-version"),
        "deno": deno or "未找到",
        "deno_version": _tool_version(deno, "--version"),
        "asr": asr_ver,
        "yt_dlp": ytdlp_ver,
        "yt_dlp_update": yt_dlp_updater.update_status(),
        "whisper_default": whisper_models.default_model_status(),
        "release_ai_configured": release_llm.configured,
        "release_ai_model": release_llm.model if release_llm.configured else "未配置",
    }


@router.get("/api/environment-status")
async def environment_status():
    """供启动界面、诊断和 Agent 读取；初始化动作都由后台自动完成。"""
    from runtime_environment import collect_runtime_environment

    return collect_runtime_environment()


@router.post("/api/environment-status/retry")
async def retry_environment_preparation():
    """网络恢复后允许立即唤醒所有后台准备，不要求用户选择具体组件。"""
    from runtime_environment import collect_runtime_environment

    whisper_models.retry_default_model_async()
    yt_dlp_updater.retry_update_async()
    return collect_runtime_environment()


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
    return FileResponse(str(log_file), filename="mediabrief.log", media_type="text/plain")


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

    hf_endpoint 非空时仅本次下载临时生效（镜像/代理），默认官方失败后换 ModelScope。
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
