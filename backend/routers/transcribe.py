"""转录/摘要相关路由：提交任务、状态查询、SSE、文件下载、删除、重试。"""
import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from summarizer import Summarizer
from services import UPLOAD_ALLOWED_EXT, UPLOAD_MAX_MB, summarizer as default_summarizer
from pipeline import (
    process_upload_task,
    process_video_task,
    regenerate_summary,
    run_post_extract_pipeline,
    sanitize_title_for_filename,
)
from task_store import (
    TEMP_DIR,
    active_tasks,
    broadcast_task_update,
    finish_task as _finish_task,
    init_task_stages as _init_task_stages,
    processing_urls,
    refresh_task_view_state as _refresh_task_view_state,
    save_tasks,
    sse_connections,
    tasks,
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
    """保存上传文件并入队 process_upload_task，返回 {task_id, message}。"""
    raw_name = file.filename or "upload.bin"
    if ".." in raw_name or "/" in raw_name or "\\" in raw_name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    safe_name = os.path.basename(raw_name)
    ext = Path(safe_name).suffix.lower()
    if ext not in UPLOAD_ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext or '(none)'}",
        )

    max_bytes = UPLOAD_MAX_MB * 1024 * 1024
    task_id = str(uuid.uuid4())
    unique_stem = task_id.replace("-", "")[:12]
    dest = TEMP_DIR / f"upload_{unique_stem}{ext}"

    total = 0
    with open(dest, "wb") as out_f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                try:
                    dest.unlink(missing_ok=True)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds limit of {UPLOAD_MAX_MB} MB",
                )
            out_f.write(chunk)

    if total == 0:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Empty file")

    video_title = sanitize_title_for_filename(Path(safe_name).stem) or "upload"
    source_label = f"upload:{safe_name}"

    tasks[task_id] = {
        "status": "processing",
        "progress": 0,
        "message": "开始处理上传文件...",
        "script": None,
        "summary": None,
        "error": None,
        "url": source_label,
    }
    save_tasks(tasks)

    bg = asyncio.create_task(
        process_upload_task(
            task_id,
            dest,
            safe_name,
            video_title,
            ext,
            summary_language,
            api_key,
            model_base_url,
            model_id,
        )
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
    """
    处理视频链接或本地上传（multipart 中带 file 且无有效 URL 时走上传流程）。
    上传与 URL 共用此路径，便于反向代理只放行 /api/process-video 的环境。
    """
    try:
        if file is not None and (file.filename or "").strip():
            return await _enqueue_upload_job(
                file, summary_language, api_key, model_base_url, model_id
            )

        stripped = (url or "").strip()
        if not stripped:
            raise HTTPException(
                status_code=400,
                detail="Provide a video URL or upload a file",
            )

        url = stripped

        # 检查是否已经在处理相同的URL
        if url in processing_urls:
            # 查找现有任务
            for tid, task in tasks.items():
                if task.get("url") == url:
                    return {"task_id": tid, "message": "该视频正在处理中，请等待..."}

        # 生成唯一任务ID
        task_id = str(uuid.uuid4())

        # 标记URL为正在处理
        processing_urls.add(url)

        # 初始化任务状态
        tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "开始处理视频...",
            "script": None,
            "summary": None,
            "error": None,
            "url": url  # 保存URL用于去重
        }
        save_tasks(tasks)

        # 创建并跟踪异步任务
        task = asyncio.create_task(process_video_task(task_id, url, summary_language, api_key, model_base_url, model_id))
        active_tasks[task_id] = task

        return {"task_id": task_id, "message": "任务已创建，正在处理中..."}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理视频时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.post("/api/process-upload")
async def process_upload(
    file: UploadFile = File(...),
    summary_language: str = Form(default="zh"),
    api_key: str = Form(default=""),
    model_base_url: str = Form(default=""),
    model_id: str = Form(default=""),
):
    """独立上传入口；逻辑与 multipart 带 file 的 /api/process-video 相同。"""
    return await _enqueue_upload_job(
        file, summary_language, api_key, model_base_url, model_id
    )


@router.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str):
    """
    获取任务状态
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    _refresh_task_view_state(task_id)
    return tasks[task_id]


@router.get("/api/task-stream/{task_id}")
async def task_stream(task_id: str):
    """
    SSE实时任务状态流
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        # 创建任务专用的队列
        queue = asyncio.Queue()

        # 将队列添加到连接列表
        if task_id not in sse_connections:
            sse_connections[task_id] = []
        sse_connections[task_id].append(queue)

        try:
            # 立即发送当前状态
            current_task = tasks.get(task_id, {})
            yield f"data: {json.dumps(current_task, ensure_ascii=False)}\n\n"

            # 持续监听状态更新
            while True:
                try:
                    # 等待状态更新，超时时间30秒发送心跳
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"

                    # 如果任务完成或失败，结束流
                    task_data = json.loads(data)
                    if task_data.get("status") in ["completed", "error"]:
                        break

                except asyncio.TimeoutError:
                    # 发送心跳保持连接
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            logger.info(f"SSE连接被取消: {task_id}")
        except Exception as e:
            logger.error(f"SSE流异常: {e}")
        finally:
            # 清理连接
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
    """
    直接从temp目录下载文件（简化方案）
    """
    try:
        # 检查文件扩展名安全性
        if not filename.endswith('.md'):
            raise HTTPException(status_code=400, detail="仅支持下载.md文件")

        # 检查文件名格式（防止路径遍历攻击）
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(status_code=400, detail="文件名格式无效")

        file_path = TEMP_DIR / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")

        return FileResponse(
            file_path,
            filename=filename,
            media_type="text/markdown"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


@router.delete("/api/task/{task_id}")
async def delete_task(task_id: str):
    """取消并删除任务"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = active_tasks.get(task_id)
    if task and not task.done():
        task.cancel()
        logger.info(f"任务 {task_id} 已被取消")

    _finish_task(task_id, tasks[task_id].get("url"))
    del tasks[task_id]
    save_tasks(tasks)
    return {"message": "任务已取消并删除"}


@router.get("/api/tasks/active")
async def get_active_tasks():
    """
    获取当前活跃任务列表（用于调试）
    """
    active_count = len(active_tasks)
    processing_count = len(processing_urls)
    return {
        "active_tasks": active_count,
        "processing_urls": processing_count,
        "task_ids": list(active_tasks.keys())
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
    """重新生成：基于原始转录重新执行优化+摘要管线，覆盖旧结果。"""
    try:
        if task_id not in tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        old_task = tasks[task_id]

        # 读取原始转录文本
        raw_script_file = old_task.get("raw_script_file")
        if not raw_script_file:
            raise HTTPException(status_code=400, detail="未找到原始转录文件，无法重试")

        raw_path = TEMP_DIR / raw_script_file
        if not raw_path.exists():
            raise HTTPException(status_code=400, detail="原始转录文件已丢失")

        raw_script = raw_path.read_text(encoding="utf-8")
        # 移除末尾 source 行 (原始文件末尾有 `\n\nsource: xxx`)
        raw_script = re.sub(r'\n\nsource:.*$', '', raw_script, flags=re.DOTALL)

        video_title = old_task.get("video_title", "Retry")
        source_ref = old_task.get("url", "retry")

        # 构造 Summarizer（优先用前端传入的 API 配置）
        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id or None)
        else:
            request_summarizer = default_summarizer

        summary_lang = summary_language or old_task.get("summary_language", "zh")

        # 创建新任务 ID，覆盖旧任务
        new_task_id = str(uuid.uuid4())

        tasks[new_task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "正在重试……",
            "script": None,
            "summary": None,
            "error": None,
            "url": source_ref,
            "video_title": video_title,
            "retry_of": task_id,
        }
        _init_task_stages(new_task_id, "retry")
        save_tasks(tasks)

        async def _retry_pipeline_wrapper():
            try:
                await run_post_extract_pipeline(
                    task_id=new_task_id,
                    raw_script=raw_script,
                    video_title=video_title,
                    source_ref=source_ref,
                    summary_language=summary_lang,
                    request_summarizer=request_summarizer,
                    dedup_url=None,
                    use_two_step=use_two_step,
                )
            except Exception as e:
                logger.error(f"重试任务 {new_task_id} 失败: {e}")
                _finish_task(new_task_id)
                if new_task_id in tasks:
                    tasks[new_task_id].update({
                        "status": "error",
                        "error": str(e),
                        "message": f"重试失败: {str(e)}",
                    })
                    save_tasks(tasks)
                    await broadcast_task_update(new_task_id, tasks[new_task_id])

        bg = asyncio.create_task(_retry_pipeline_wrapper())
        active_tasks[new_task_id] = bg

        return {"task_id": new_task_id, "message": "重试任务已创建"}

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
    """原地重新生成摘要（不重跑转录/优化），覆盖同一任务的 summary 字段。"""
    try:
        if task_id not in tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id or None)
        else:
            request_summarizer = default_summarizer

        summary_lang = summary_language or tasks[task_id].get("summary_language", "zh")

        # 标记为处理中，防止并发修改
        tasks[task_id].update({
            "status": "processing",
            "progress": 0,
            "message": "正在重新生成摘要……",
        })
        save_tasks(tasks)

        bg = asyncio.create_task(
            regenerate_summary(
                task_id=task_id,
                request_summarizer=request_summarizer,
                summary_language=summary_lang,
                use_two_step=use_two_step,
            )
        )
        active_tasks[task_id] = bg

        return {"task_id": task_id, "message": "摘要重新生成任务已启动"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新生成摘要失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
