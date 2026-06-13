"""转录/摘要相关路由：提交任务、状态查询、SSE、文件下载、删除、重试、历史。"""
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from db import (
    create_task as _db_create_task,
    delete_task as _db_delete_task,
    delete_tasks as _db_delete_tasks,
    find_processing_task_by_url as _db_find_processing_task_by_url,
    get_task as _db_get_task,
    list_history as _db_list_history,
    list_recent_tasks as _db_list_recent,
    task_exists as _db_task_exists,
    update_task as _db_update_task,
)
from exceptions import TranscriberError
from summarizer import Summarizer
from services import UPLOAD_ALLOWED_EXT, UPLOAD_MAX_MB, summarizer as default_summarizer
from pipeline import (
    process_upload_task,
    process_video_task,
    regenerate_summary,
    sanitize_title_for_filename,
)
from task_store import (
    TEMP_DIR,
    active_tasks,
    broadcast_task_update,
    finish_task as _finish_task,
    init_task_stages as _init_task_stages,
    processing_urls,
    refresh_task_view_state,
    sse_connections,
    sse_lock,
)

logger = logging.getLogger(__name__)
router = APIRouter()


async def _enqueue_upload_job(
    file: UploadFile,
    summary_language: str,
    api_key: str,
    model_base_url: str,
    model_id: str,
) -> dict:
    raw_name = file.filename or "upload.bin"
    if ".." in raw_name or "/" in raw_name or "\\" in raw_name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    safe_name = os.path.basename(raw_name)
    ext = Path(safe_name).suffix.lower()
    if ext not in UPLOAD_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '(none)'}")

    max_bytes = UPLOAD_MAX_MB * 1024 * 1024
    task_id = str(uuid.uuid4())
    unique_stem = task_id.replace("-", "")[:12]
    dest = TEMP_DIR / f"upload_{unique_stem}{ext}"

    total = 0
    try:
        with open(dest, "wb") as out_f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"File exceeds limit of {UPLOAD_MAX_MB} MB")
                out_f.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    if total == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty file")

    video_title = sanitize_title_for_filename(Path(safe_name).stem) or "upload"
    source_label = f"upload:{safe_name}"

    await _db_create_task(task_id, {
        "status": "processing",
        "progress": 0,
        "message": "开始处理上传文件...",
        "script": None,
        "summary": None,
        "error": None,
        "url": source_label,
        "source_type": "file",
        "source_value": safe_name,
    })

    bg = asyncio.create_task(
        process_upload_task(task_id, dest, safe_name, video_title, ext, summary_language, api_key, model_base_url, model_id)
    )
    active_tasks[task_id] = bg

    return {"task_id": task_id, "message": "任务已创建，正在处理中..."}


@router.post("/api/process-video")
async def process_video(
    url: str = Form(default=""),
    summary_language: str = Form(default="zh"),
    api_key: str = Form(default=""),
    model_base_url: str = Form(default=""),
    model_id: str = Form(default=""),
    file: Optional[UploadFile] = File(None),
):
    try:
        if file is not None and (file.filename or "").strip():
            return await _enqueue_upload_job(file, summary_language, api_key, model_base_url, model_id)

        stripped = (url or "").strip()
        if not stripped:
            raise HTTPException(status_code=400, detail="Provide a video URL or upload a file")

        url = stripped

        # 通过 DB 查询是否已有该 URL 的处理中任务（去重）
        existing = await _db_find_processing_task_by_url(url)
        if existing:
            return {"task_id": existing["task_id"], "message": "该资源正在处理中，请等待..."}

        task_id = str(uuid.uuid4())
        processing_urls.add(url)

        await _db_create_task(task_id, {
            "status": "processing",
            "progress": 0,
            "message": "开始处理...",
            "script": None,
            "summary": None,
            "error": None,
            "url": url,
            "source_type": "url",
            "source_value": url,
        })

        task = asyncio.create_task(process_video_task(task_id, url, summary_language, api_key, model_base_url, model_id))
        active_tasks[task_id] = task

        return {"task_id": task_id, "message": "任务已创建，正在处理中..."}

    except HTTPException:
        raise
    except TranscriberError as e:
        logger.error(f"处理任务时出错: {e}")
        raise HTTPException(status_code=e.http_status, detail=str(e))
    except Exception as e:
        logger.error(f"处理任务时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str):
    task = await _db_get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await refresh_task_view_state(task_id)
    return await _db_get_task(task_id)


@router.get("/api/task-stream/{task_id}")
async def task_stream(task_id: str, request: Request):
    if not await _db_task_exists(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        queue = asyncio.Queue(maxsize=1)
        async with sse_lock:
            if task_id not in sse_connections:
                sse_connections[task_id] = []
            sse_connections[task_id].append(queue)

        try:
            current_task = await _db_get_task(task_id) or {}
            yield f"data: {json.dumps(current_task, ensure_ascii=False)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                    task_data = json.loads(data)
                    if task_data.get("status") in ["completed", "error"]:
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            logger.info(f"SSE连接被取消: {task_id}")
        except Exception as e:
            logger.error(f"SSE流异常: {e}")
        finally:
            async with sse_lock:
                if task_id in sse_connections and queue in sse_connections[task_id]:
                    sse_connections[task_id].remove(queue)
                    if not sse_connections[task_id]:
                        del sse_connections[task_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )


@router.get("/api/download/{filename}")
async def download_file(filename: str):
    try:
        if not filename.endswith('.md'):
            raise HTTPException(status_code=400, detail="仅支持下载.md文件")
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(status_code=400, detail="文件名格式无效")
        file_path = TEMP_DIR / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(file_path, filename=filename, media_type="text/markdown")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


@router.delete("/api/task/{task_id}")
async def delete_task(task_id: str):
    if not await _db_task_exists(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")

    task = active_tasks.get(task_id)
    if task and not task.done():
        task.cancel()
        logger.info(f"任务 {task_id} 已被取消")
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    # 广播已取消状态
    await _db_update_task(task_id, {"status": "cancelled", "message": "任务已取消"})
    task_data = await _db_get_task(task_id)
    if task_data:
        await broadcast_task_update(task_id, task_data)

    _finish_task(task_id, (task_data or {}).get("url"))
    await _db_delete_task(task_id)
    return {"message": "任务已取消并删除"}


@router.get("/api/active-tasks")
async def get_active_tasks():
    """返回当前处理中/最近完成的任务列表，供前端恢复状态。"""
    recent = await _db_list_recent(limit=20)
    for t in recent:
        await refresh_task_view_state(t["task_id"])
    # 重新读取以获取刷新后的视图字段
    result = []
    for t in recent:
        fresh = await _db_get_task(t["task_id"])
        if fresh:
            result.append(fresh)
    return {"tasks": result}


@router.get("/api/history")
async def get_history(
    search: str = Query(default=""),
    source_type: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
):
    """返回已完成的摘要任务列表，支持搜索和来源过滤。"""
    items = await _db_list_history(limit=limit, search=search, source_type=source_type)
    return {"items": items}


@router.delete("/api/history/{task_id}")
async def delete_history_item(task_id: str):
    if not await _db_task_exists(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    await _db_delete_task(task_id)
    return {"message": "已删除"}


@router.post("/api/history/delete")
async def delete_history_items(task_ids: list[str] = Form(default=[])):
    """批量删除历史记录。也接受 JSON body 中的 task_ids。"""
    if not task_ids:
        raise HTTPException(status_code=400, detail="请提供要删除的任务ID列表")
    await _db_delete_tasks(task_ids)
    return {"message": f"已删除 {len(task_ids)} 条记录"}


@router.get("/api/tasks/active")
async def get_active_tasks_count():
    """获取当前活跃任务计数（调试用）。"""
    return {
        "active_tasks": len(active_tasks),
        "processing_urls": len(processing_urls),
        "task_ids": list(active_tasks.keys()),
    }


@router.post("/api/retry/{task_id}")
async def retry_task(
    task_id: str,
    api_key: str = Form(default=""),
    model_base_url: str = Form(default=""),
    model_id: str = Form(default=""),
    summary_language: str = Form(default="zh"),
    use_two_step: bool = Form(default=True),
):
    try:
        old_task = await _db_get_task(task_id)
        if not old_task:
            raise HTTPException(status_code=404, detail="任务不存在")

        has_transcript = (
            old_task.get("script_path")
            or old_task.get("raw_script_file")
            or old_task.get("script")
        )
        if not has_transcript:
            raise HTTPException(status_code=400, detail="未找到转录文本，无法重试")

        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id or None)
        else:
            request_summarizer = default_summarizer

        summary_lang = summary_language or old_task.get("summary_language", "zh")

        await _db_update_task(task_id, {
            "status": "processing",
            "progress": 0,
            "message": "正在重试……",
        })

        bg = asyncio.create_task(
            regenerate_summary(task_id=task_id, request_summarizer=request_summarizer,
                               summary_language=summary_lang, use_two_step=use_two_step)
        )
        active_tasks[task_id] = bg

        return {"task_id": task_id, "message": "重试任务已创建"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/regenerate-summary/{task_id}")
async def regenerate_summary_endpoint(
    task_id: str,
    api_key: str = Form(default=""),
    model_base_url: str = Form(default=""),
    model_id: str = Form(default=""),
    summary_language: str = Form(default="zh"),
    use_two_step: bool = Form(default=True),
):
    try:
        if not await _db_task_exists(task_id):
            raise HTTPException(status_code=404, detail="任务不存在")

        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id or None)
        else:
            request_summarizer = default_summarizer

        summary_lang = summary_language or (await _db_get_task(task_id) or {}).get("summary_language", "zh")

        await _db_update_task(task_id, {
            "status": "processing",
            "progress": 0,
            "message": "正在重新生成摘要……",
        })

        bg = asyncio.create_task(
            regenerate_summary(task_id=task_id, request_summarizer=request_summarizer,
                               summary_language=summary_lang, use_two_step=use_two_step)
        )
        active_tasks[task_id] = bg

        return {"task_id": task_id, "message": "摘要重新生成任务已启动"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新生成摘要失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
