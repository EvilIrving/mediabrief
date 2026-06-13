"""RSS 订阅相关路由。"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Form, HTTPException

from db import create_task as _db_create_task
from services import rss_reader
from pipeline import run_download_video_task, run_rss_summarize_task
from task_queue import queue_manager
from task_store import (
    active_tasks,
    init_task_stages as _init_task_stages,
)

# 触发 RSS 队列处理器的注册（副作用导入）
import rss_handlers  # noqa: F401

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/rss/parse")
async def parse_rss_feed(feed_url: str = Form(...)):
    """抓取并解析 RSS/Atom。订阅数据由前端保存，不写入服务器。"""
    try:
        feed_info = await rss_reader.fetch_feed(feed_url)
        return {"feed": feed_info}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/rss/subscribe")
async def subscribe_rss_feed(feed_url: str = Form(...)):
    """添加RSS订阅（兼容旧接口：服务器 JSON 持久化）"""
    try:
        feed_info = await rss_reader.add_feed(feed_url)
        return {"feed": feed_info}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/rss/feeds")
async def list_rss_feeds(full: bool = False):
    """列出所有RSS订阅。full=true 时包含条目详情。"""
    try:
        if full:
            feeds = list(rss_reader._feeds.values())
            return {"feeds": feeds}
        feeds = rss_reader.list_feeds()
        return {"feeds": feeds}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/rss/entries/{feed_id}")
async def list_rss_entries(feed_id: str):
    """获取订阅的条目列表"""
    try:
        entries = await rss_reader.get_entries(feed_id)
        return {"entries": entries}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/rss/enqueue")
async def enqueue_rss_task(
    feed_id: str = Form(...),
    entry_id: str = Form(...),
    action: str = Form(default="summarize"),
    summary_language: str = Form(default="zh"),
    api_key: str = Form(default=""),
    model_base_url: str = Form(default=""),
    model_id: str = Form(default=""),
    entry_json: str = Form(default=""),
):
    """将 RSS 任务加入持久化队列（串行执行，刷新不丢状态）。

    前端应订阅 GET /api/queue/stream/rss 获取实时队列状态。
    """
    try:
        entry = None
        if entry_json:
            try:
                entry = json.loads(entry_json)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="无效的RSS条目数据")
        else:
            entry = rss_reader.get_entry_by_id(feed_id, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="条目不存在")

        item_type = "rss_summarize" if action == "summarize" else "rss_download"
        item_key = f"{feed_id}:{entry_id}:{action}"

        if item_type == "rss_download" and not entry.get("enclosure_url"):
            raise HTTPException(status_code=400, detail="该条目没有可下载的媒体")

        payload = {
            "feed_id": feed_id,
            "entry_id": entry_id,
            "entry_data": entry,
            "summary_language": summary_language,
            "api_key": api_key,
            "model_base_url": model_base_url,
            "model_id": model_id,
        }

        result = await queue_manager.enqueue("tasks", item_type, item_key, payload)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"入队失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/rss/create-task")
async def create_rss_task(
    feed_id: str = Form(...),
    entry_id: str = Form(...),
    action: str = Form(default="summarize"),
    summary_language: str = Form(default="zh"),
    api_key: str = Form(default=""),
    model_base_url: str = Form(default=""),
    model_id: str = Form(default=""),
    entry_json: str = Form(default=""),
):
    """从RSS条目创建任务（摘要或下载）。支持前端本地订阅传入 entry_json。"""
    async def _mark_on_complete(coro, action_label: str):
        """在任务成功完成后标记 RSS 条目为已处理。"""
        try:
            await coro
            rss_reader.mark_entry_processed(feed_id, entry_id, action_label)
        except Exception:
            raise

    try:
        entry = None
        if entry_json:
            try:
                entry = json.loads(entry_json)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="无效的RSS条目数据")
        else:
            entry = rss_reader.get_entry_by_id(feed_id, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="条目不存在")

        task_id = str(uuid.uuid4())
        entry_url = entry.get("link", "") or entry.get("enclosure_url", "")
        entry_title = entry.get("title", "RSS条目")

        if action == "download":
            if not entry.get("enclosure_url"):
                raise HTTPException(status_code=400, detail="该条目没有可下载的媒体")

            await _db_create_task(task_id, {
                "status": "queued",
                "progress": 0,
                "message": "等待排队...",
                "url": entry.get("enclosure_url"),
                "type": "download",
                "rss_entry": entry_title,
                "source_type": "rss",
                "source_value": entry_url,
                "feed_id": feed_id,
                "entry_id": entry_id,
            })
            result = await queue_manager.enqueue("tasks", "rss_download", f"{feed_id}:{entry_id}:{action}", {
                "task_id": task_id,
                "feed_id": feed_id,
                "entry_id": entry_id,
                "entry_data": entry,
                "summary_language": summary_language,
                "api_key": api_key,
                "model_base_url": model_base_url,
                "model_id": model_id,
            })

        elif action == "summarize":
            await _db_create_task(task_id, {
                "status": "queued",
                "progress": 0,
                "message": "等待排队...",
                "url": entry_url,
                "type": "summary",
                "rss_entry": entry_title,
                "source_type": "rss",
                "source_value": entry_url,
                "feed_id": feed_id,
                "entry_id": entry_id,
            })
            result = await queue_manager.enqueue("tasks", "rss_summarize", f"{feed_id}:{entry_id}:{action}", {
                "task_id": task_id,
                "feed_id": feed_id,
                "entry_id": entry_id,
                "entry_data": entry,
                "summary_language": summary_language,
                "api_key": api_key,
                "model_base_url": model_base_url,
                "model_id": model_id,
            })

        else:
            raise HTTPException(status_code=400, detail=f"未知操作: {action}")

        return {"task_id": task_id, "queue_id": result.get("id"), "status": result.get("status", "queued"), "message": f"任务已排队"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/rss/feed/{feed_id}/favorite")
async def toggle_feed_favorite(feed_id: str):
    """切换订阅的收藏状态。"""
    try:
        if feed_id not in rss_reader._feeds:
            raise HTTPException(status_code=404, detail="订阅不存在")
        feed = rss_reader._feeds[feed_id]
        feed["favorite"] = not feed.get("favorite", False)
        rss_reader._save()
        return {"favorite": feed["favorite"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/rss/feed/{feed_id}")
async def delete_rss_feed(feed_id: str):
    """删除RSS订阅"""
    try:
        rss_reader.remove_feed(feed_id)
        return {"message": "订阅已删除"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/rss/refresh/{feed_id}")
async def refresh_rss_feed(feed_id: str):
    """刷新RSS订阅（增量拉取新条目）"""
    try:
        result = await rss_reader.refresh_feed(feed_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
