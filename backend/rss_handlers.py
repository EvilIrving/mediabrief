"""RSS 任务队列处理器。

注册到 queue_manager 供 TaskQueueManager 串行调用。
每个处理器接收 payload dict，执行完整的任务生命周期，返回 result dict。
"""
import logging

import cancellation
from db import create_task as _db_create_task, get_task as _db_get_task, update_task as _db_update_task
from pipeline import run_download_video_task, run_rss_summarize_task
from task_queue import queue_manager
from services import rss_reader
from task_store import init_task_stages as _init_task_stages

logger = logging.getLogger(__name__)


async def _handle_rss_summarize(payload: dict) -> dict:
    """处理 RSS 摘要任务（由队列管理器串行调用）。"""
    feed_id = payload["feed_id"]
    entry_id = payload["entry_id"]
    entry_data = payload.get("entry_data", {})
    summary_language = payload.get("summary_language", "zh")
    api_key = payload.get("api_key", "")
    model_base_url = payload.get("model_base_url", "")
    model_id = payload.get("model_id", "")

    task_id = payload.get("task_id") or ""
    entry_url = entry_data.get("link", "") or entry_data.get("enclosure_url", "")

    if not task_id:
        raise ValueError("RSS 任务缺少 task_id")

    task = await _db_get_task(task_id)
    if not task:
        await _db_create_task(task_id, {
            "status": "queued",
            "progress": 0,
            "message": "等待排队...",
            "url": entry_url,
            "rss_entry": entry_data.get("title", "RSS条目"),
            "source_type": "rss",
            "source_value": entry_url,
            "feed_id": feed_id,
            "entry_id": entry_id,
        })

    await _db_update_task(task_id, {
        "status": "processing",
        "progress": 0,
        "message": "开始处理RSS条目...",
    })

    # 建立取消令牌：本 handler 直接在 worker 上下文里 await，深层 transcriber/
    # video_processor 通过 cancellation.current() 读取同一令牌实现协作取消。
    cancellation.create(task_id)
    try:
        await run_rss_summarize_task(
            task_id, entry_data, summary_language,
            api_key, model_base_url, model_id,
        )
    finally:
        cancellation.discard(task_id)

    rss_reader.mark_entry_processed(feed_id, entry_id, "summarized")

    task = await _db_get_task(task_id)
    return {
        "task_id": task_id,
        "status": task.get("status", "completed") if task else "completed",
    }


async def _handle_rss_download(payload: dict) -> dict:
    """处理 RSS 下载任务（由队列管理器串行调用）。"""
    feed_id = payload["feed_id"]
    entry_id = payload["entry_id"]
    entry_data = payload.get("entry_data", {})
    enclosure_url = entry_data.get("enclosure_url", "")
    entry_title = entry_data.get("title", "RSS条目")

    task_id = payload.get("task_id") or ""
    if not task_id:
        raise ValueError("RSS 任务缺少 task_id")

    task = await _db_get_task(task_id)
    if not task:
        await _db_create_task(task_id, {
            "status": "queued",
            "progress": 0,
            "message": "等待排队...",
            "url": enclosure_url,
            "rss_entry": entry_title,
            "source_type": "rss",
            "source_value": entry_data.get("link", ""),
            "feed_id": feed_id,
            "entry_id": entry_id,
        })

    await _db_update_task(task_id, {
        "status": "processing",
        "progress": 0,
        "message": "准备下载...",
    })

    await _init_task_stages(task_id, "download_only")
    cancellation.create(task_id)
    try:
        await run_download_video_task(task_id, enclosure_url, "best", entry_title)
    finally:
        cancellation.discard(task_id)

    rss_reader.mark_entry_processed(feed_id, entry_id, "downloaded")

    task = await _db_get_task(task_id)
    return {
        "task_id": task_id,
        "status": task.get("status", "completed") if task else "completed",
    }


# 模块加载时注册处理器（在 main.py 注册路由后生效）
queue_manager.register_handler("rss_summarize", _handle_rss_summarize)
queue_manager.register_handler("rss_download", _handle_rss_download)
logger.info("RSS 队列处理器已注册: rss_summarize, rss_download")
