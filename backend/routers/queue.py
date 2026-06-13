"""队列路由：REST 查询 + SSE 订阅。"""
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from task_queue import queue_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/queue/state")
async def queue_state(queue_name: str = Query(default="rss")):
    """获取队列完整状态（页面刷新时调用以恢复 UI）。"""
    state = await queue_manager.get_state(queue_name)
    return state


@router.post("/api/queue/enqueue")
async def queue_enqueue(body: dict):
    """将任务入队。body: {queue_name, item_type, item_key, payload}"""
    queue_name = body.get("queue_name", "rss")
    item_type = body.get("item_type", "")
    item_key = body.get("item_key", "")
    payload = body.get("payload", {})
    if not item_type or not item_key:
        raise HTTPException(status_code=400, detail="item_type and item_key are required")
    result = await queue_manager.enqueue(queue_name, item_type, item_key, payload)
    return result


@router.delete("/api/queue/{item_id}")
async def queue_remove(item_id: str, queue_name: str = Query(default="rss")):
    """从队列中移除一项。"""
    await queue_manager.remove_item(queue_name, item_id)
    return {"message": "已移除"}


@router.post("/api/queue/clear")
async def queue_clear_completed(queue_name: str = Query(default="rss")):
    """清除已完成/错误的队列项。"""
    count = await queue_manager.clear_completed(queue_name)
    return {"cleared": count}


@router.get("/api/queue/stream/{queue_name}")
async def queue_stream(queue_name: str, request: Request):
    """SSE 端点：前端订阅队列状态实时变更。"""
    async def event_generator():
        q = queue_manager.subscribe(queue_name)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    import asyncio as _asyncio
                    data = await _asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                except _asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except Exception as e:
            logger.error(f"队列 SSE 异常: {e}")
        finally:
            queue_manager.unsubscribe(queue_name, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )
