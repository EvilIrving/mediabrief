"""队列路由：REST 查询/操作 + SSE 订阅。"""
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from task_queue import queue_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class EnqueueBody(BaseModel):
    queue_name: str = "tasks"
    item_type: str = Field(..., min_length=1)
    item_key: str = Field(..., min_length=1)
    payload: dict = Field(default_factory=dict)


@router.get("/api/queue/state")
async def queue_state(queue_name: str = Query(default="tasks")):
    """获取队列完整状态（页面刷新时调用以恢复 UI）。"""
    state = await queue_manager.get_state(queue_name)
    return state


@router.get("/api/queue/{queue_name}/stats")
async def queue_stats(queue_name: str):
    """按状态聚合计数 + 队列长度（轻量，前端轮询徽标用）。"""
    return await queue_manager.get_stats(queue_name)


@router.get("/api/queue/{queue_name}/items")
async def queue_items(
    queue_name: str,
    status: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """分页 / 按状态过滤列出队列项。"""
    return await queue_manager.list_items(queue_name, status, limit, offset)


@router.get("/api/queue/item/{item_id}")
async def queue_item_detail(item_id: str):
    """单项详情（含 payload/result/时间戳/error）。"""
    item = await queue_manager.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="队列项不存在")
    return item


@router.post("/api/queue/enqueue")
async def queue_enqueue(body: EnqueueBody):
    """将任务入队。未注册的 item_type 直接拒绝，避免入队后才在 worker 报错。"""
    if not queue_manager.is_registered(body.item_type):
        raise HTTPException(status_code=400, detail=f"未注册的任务类型: {body.item_type}")
    return await queue_manager.enqueue(body.queue_name, body.item_type, body.item_key, body.payload)


@router.post("/api/queue/item/{item_id}/cancel")
async def queue_cancel(item_id: str, queue_name: str = Query(default="tasks")):
    """取消一项：杀掉运行中的下载/ffmpeg/Whisper 并删除记录。"""
    ok = await queue_manager.cancel_item(queue_name, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="队列项不存在")
    return {"message": "已取消"}


@router.delete("/api/queue/item/{item_id}")
async def queue_remove_item(item_id: str, queue_name: str = Query(default="tasks")):
    """删除一条队列记录（仅适用于终态项；运行中请用 cancel）。"""
    item = await queue_manager.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="队列项不存在")
    if item.get("status") == "processing":
        raise HTTPException(status_code=409, detail="任务运行中，请使用 cancel 接口")
    await queue_manager.remove_item(queue_name, item_id)
    return {"message": "已移除"}


@router.post("/api/queue/clear")
async def queue_clear_completed(queue_name: str = Query(default="tasks")):
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
