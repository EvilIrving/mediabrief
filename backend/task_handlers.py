"""Unified task queue handlers for user-initiated tasks."""
import asyncio
import logging
from pathlib import Path

from db import get_task as _db_get_task, update_task as _db_update_task
from pipeline import (
    process_upload_task,
    process_video_task,
    run_download_audio_task,
    run_download_subtitles_task,
    run_download_video_task,
)
from task_queue import queue_manager
from task_store import active_tasks, init_task_stages as _init_task_stages, processing_urls

logger = logging.getLogger(__name__)


async def _run_pipeline_task(task_id: str, dedup_url: str | None, message: str, pipeline_coro):
    if dedup_url:
        processing_urls.add(dedup_url)
    await _db_update_task(task_id, {
        "status": "processing",
        "progress": 0,
        "message": message,
    })

    task = asyncio.create_task(pipeline_coro)
    active_tasks[task_id] = task
    try:
        await task
    except asyncio.CancelledError:
        logger.info("队列任务被取消: %s", task_id)
        await _db_update_task(task_id, {
            "status": "cancelled",
            "message": "任务已取消",
        })
        task_data = await _db_get_task(task_id)
        if task_data:
            from task_store import broadcast_task_update
            await broadcast_task_update(task_id, task_data)
        return {"task_id": task_id, "status": "cancelled"}
    finally:
        active_tasks.pop(task_id, None)
        if dedup_url:
            processing_urls.discard(dedup_url)

    task_data = await _db_get_task(task_id)
    return {
        "task_id": task_id,
        "status": task_data.get("status", "completed") if task_data else "completed",
    }


async def _handle_process_video(payload: dict) -> dict:
    task_id = payload["task_id"]
    url = payload["url"]
    summary_language = payload.get("summary_language", "zh")
    api_key = payload.get("api_key", "")
    model_base_url = payload.get("model_base_url", "")
    model_id = payload.get("model_id", "")
    return await _run_pipeline_task(
        task_id,
        url,
        "开始处理...",
        process_video_task(task_id, url, summary_language, api_key, model_base_url, model_id),
    )


async def _handle_process_upload(payload: dict) -> dict:
    task_id = payload["task_id"]
    saved_path = payload["saved_path"]
    original_name = payload.get("original_name", "upload.bin")
    video_title = payload.get("video_title", "upload")
    ext_lower = payload.get("ext_lower", "")
    summary_language = payload.get("summary_language", "zh")
    api_key = payload.get("api_key", "")
    model_base_url = payload.get("model_base_url", "")
    model_id = payload.get("model_id", "")
    return await _run_pipeline_task(
        task_id,
        None,
        "开始处理上传文件...",
        process_upload_task(task_id, Path(saved_path), original_name, video_title, ext_lower, summary_language, api_key, model_base_url, model_id),
    )


async def _handle_download_video(payload: dict) -> dict:
    task_id = payload["task_id"]
    url = payload["url"]
    format_id = payload.get("format_id", "best")
    filename = payload.get("filename", "")
    await _init_task_stages(task_id, "download_only")
    return await _run_pipeline_task(
        task_id,
        url,
        "准备下载...",
        run_download_video_task(task_id, url, format_id, filename),
    )


async def _handle_download_audio(payload: dict) -> dict:
    task_id = payload["task_id"]
    url = payload["url"]
    format_id = payload.get("format_id", "bestaudio/best")
    filename = payload.get("filename", "")
    audio_format = payload.get("audio_format", "m4a")
    await _init_task_stages(task_id, "download_only")
    return await _run_pipeline_task(
        task_id,
        url,
        "准备下载音频...",
        run_download_audio_task(task_id, url, format_id, filename, audio_format),
    )


async def _handle_download_subtitles(payload: dict) -> dict:
    task_id = payload["task_id"]
    url = payload["url"]
    lang = payload.get("lang", "en")
    filename = payload.get("filename", "")
    await _init_task_stages(task_id, "download_only")
    return await _run_pipeline_task(
        task_id,
        url,
        "准备下载字幕...",
        run_download_subtitles_task(task_id, url, lang, filename),
    )


queue_manager.register_handler("process_video", _handle_process_video)
queue_manager.register_handler("process_upload", _handle_process_upload)
queue_manager.register_handler("download_video", _handle_download_video)
queue_manager.register_handler("download_audio", _handle_download_audio)
queue_manager.register_handler("download_subtitles", _handle_download_subtitles)
logger.info("通用任务队列处理器已注册: process_video, process_upload, download_video, download_audio, download_subtitles")
