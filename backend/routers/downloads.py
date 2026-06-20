"""下载路由（仅下载，不转录）。"""
import asyncio
import logging
import uuid

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse

from db import create_task as _db_create_task
from services import video_processor
from pipeline import (
    run_download_audio_task,
    run_download_subtitles_task,
    run_download_video_task,
)
from task_queue import queue_manager
from task_store import (
    TEMP_DIR,
    active_tasks,
    init_task_stages as _init_task_stages,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/download-video/formats")
async def get_video_formats(
    url: str = Form(...),
    auto_detect_browser_cookies: bool = Form(default=False),
):
    """获取媒体的可用格式列表（含视频轨道、音频轨道、字幕）"""
    cookie_token = video_processor.use_auto_detect_browser_cookies(auto_detect_browser_cookies)
    try:
        result = await video_processor.get_video_formats(url)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        video_processor.reset_auto_detect_browser_cookies(cookie_token)


@router.post("/api/download-audio")
async def start_download_audio(
    url: str = Form(...),
    format_id: str = Form(default="bestaudio/best"),
    filename: str = Form(default=""),
    audio_format: str = Form(default="m4a"),
    auto_detect_browser_cookies: bool = Form(default=False),
):
    """开始下载音频（仅音频，不转录）"""
    try:
        if not url.strip():
            raise HTTPException(status_code=400, detail="请提供URL")

        task_id = str(uuid.uuid4())
        await _db_create_task(task_id, {
            "status": "queued",
            "progress": 0,
            "message": "task.queued",
            "url": url,
            "type": "download_audio",
        })

        result = await queue_manager.enqueue("tasks", "download_audio", task_id, {
            "task_id": task_id,
            "url": url,
            "format_id": format_id,
            "filename": filename,
            "audio_format": audio_format,
            "auto_detect_browser_cookies": auto_detect_browser_cookies,
        })

        return {"task_id": task_id, "queue_id": result.get("id"), "status": result.get("status", "queued"), "message": "task.audio_download_queued"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建音频下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/download-subtitles")
async def start_download_subtitles(
    url: str = Form(...),
    lang: str = Form(default="en"),
    filename: str = Form(default=""),
    auto_detect_browser_cookies: bool = Form(default=False),
):
    """开始下载字幕文件"""
    try:
        if not url.strip():
            raise HTTPException(status_code=400, detail="请提供URL")

        task_id = str(uuid.uuid4())
        await _db_create_task(task_id, {
            "status": "queued",
            "progress": 0,
            "message": "task.queued",
            "url": url,
            "type": "download_subtitles",
        })

        result = await queue_manager.enqueue("tasks", "download_subtitles", task_id, {
            "task_id": task_id,
            "url": url,
            "lang": lang,
            "filename": filename,
            "auto_detect_browser_cookies": auto_detect_browser_cookies,
        })

        return {"task_id": task_id, "queue_id": result.get("id"), "status": result.get("status", "queued"), "message": "task.subtitle_download_queued"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建字幕下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/download-video")
async def start_download_video(
    url: str = Form(...),
    format_id: str = Form(default="best"),
    filename: str = Form(default=""),
    auto_detect_browser_cookies: bool = Form(default=False),
):
    """仅下载媒体文件（不转录）"""
    try:
        if not url.strip():
            raise HTTPException(status_code=400, detail="请提供URL")

        task_id = str(uuid.uuid4())

        await _db_create_task(task_id, {
            "status": "queued",
            "progress": 0,
            "message": "task.queued",
            "url": url,
            "type": "download",
        })

        result = await queue_manager.enqueue("tasks", "download_video", task_id, {
            "task_id": task_id,
            "url": url,
            "format_id": format_id,
            "filename": filename,
            "auto_detect_browser_cookies": auto_detect_browser_cookies,
        })

        return {"task_id": task_id, "queue_id": result.get("id"), "status": result.get("status", "queued"), "message": "task.download_queued"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/download-video/file/{filename}")
async def download_video_file(filename: str):
    """下载已保存的文件"""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="无效文件名")

    file_path = TEMP_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(file_path, filename=filename)
