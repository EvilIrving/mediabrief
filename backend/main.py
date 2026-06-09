from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import os
import asyncio
import logging
from pathlib import Path
from typing import Optional
import aiofiles
import uuid
import json
import re
import openai

from video_processor import VideoProcessor
from transcriber import Transcriber
from summarizer import Summarizer
from translator import Translator
from rss_reader import RSSReader

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from task_store import (
    PROJECT_ROOT,
    TEMP_DIR,
    active_tasks,
    broadcast_stage as _broadcast_stage,
    broadcast_task_update,
    finish_task as _finish_task,
    init_task_stages as _init_task_stages,
    processing_urls,
    refresh_task_view_state as _refresh_task_view_state,
    save_tasks,
    skip_task_stages as _skip_task_stages,
    sse_connections,
    tasks,
)

app = FastAPI(title="AI视频转录器", version="1.0.0")

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")

# 初始化处理器
video_processor = VideoProcessor()
transcriber = Transcriber()
summarizer = Summarizer()
translator = Translator()
rss_reader = RSSReader(data_dir=TEMP_DIR)


async def _llm_call(fn, *args, llm_timeout: float = 300.0, task_name: str = ""):
    """在工作线程中运行阻塞式 LLM 调用（带超时保护）。"""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args), timeout=llm_timeout
        )
    except asyncio.TimeoutError:
        raise Exception(
            f"LLM 调用超时（{llm_timeout}s），任务: {task_name or 'unknown'}，"
            "请检查 API 连接或尝试缩短内容"
        )


# 本地上传：允许的类型与大小上限（MB），可用环境变量 UPLOAD_MAX_MB 调整
UPLOAD_ALLOWED_EXT = frozenset({".txt", ".mp3", ".mp4", ".m4a", ".wav", ".webm", ".mkv", ".ogg", ".flac"})
UPLOAD_MAX_MB = int(os.getenv("UPLOAD_MAX_MB", "200"))


def _sanitize_title_for_filename(title: str) -> str:
    """将视频标题清洗为安全的文件名片段。"""
    if not title:
        return "untitled"
    safe = re.sub(r"[^\w\-\s]", "", title)
    safe = re.sub(r"\s+", "_", safe).strip("._-")
    return safe[:80] or "untitled"


def _txt_to_raw_transcript_markdown(body: str) -> str:
    """将纯文本包装为与 Whisper 输出结构一致的 Markdown。"""
    text = body.strip() if body.strip() else "(empty)"
    return "\n".join([
        "# Video Transcription",
        "",
        "**Detected Language:**",
        "**Language Probability:** —",
        "",
        "## Transcription Content",
        "",
        text,
    ])


async def _run_post_extract_pipeline(
    task_id: str,
    raw_script: str,
    video_title: str,
    source_ref: str,
    summary_language: str,
    request_summarizer: Summarizer,
    dedup_url: Optional[str] = None,
    api_key: str = "",
    model_base_url: str = "",
    model_id: str = "",
    use_two_step: bool = True,  # 是否使用双步摘要
) -> None:
    """取得 raw_script 后的共用管线：归档、优化、翻译、摘要、广播。"""
    short_id = task_id.replace("-", "")[:6]
    safe_title = _sanitize_title_for_filename(video_title)

    # ── 阶段：保存原始转录 ─────────────────────────────────────
    try:
        raw_md_filename = f"raw_{safe_title}_{short_id}.md"
        raw_md_path = TEMP_DIR / raw_md_filename
        with open(raw_md_path, "w", encoding="utf-8") as f:
            f.write((raw_script or "") + f"\n\nsource: {source_ref}\n")
        tasks[task_id].update({"raw_script_file": raw_md_filename})
        save_tasks(tasks)
    except Exception as e:
        logger.error(f"保存原始转录Markdown失败: {e}")

    # ── 阶段：阅读内容 ─────────────────────────────────────────
    await _broadcast_stage(task_id, "阅读内容", 50)

    # 摘要不再等待完整 Transcript 优化。长访谈中，Transcript 优化可能会分成很多块；
    # 摘要只需要轻清理后的原始内容，并直接按 summary_language 输出。
    summary_source = request_summarizer._remove_timestamps_and_meta(raw_script)

    detected_language = transcriber.get_detected_language(raw_script)
    detected_language = (detected_language or "").strip()
    if not detected_language:
        detected_language = translator.infer_language_code(raw_script)
    detected_language = translator.normalize_lang_code(detected_language) or detected_language

    logger.info(f"检测到的语言: {detected_language}, 摘要语言: {summary_language}")
    logger.info(
        f"跳过全文翻译: detected_language={detected_language}, summary_language={summary_language}"
    )
    logger.info("并行启动: Transcript 优化 + 摘要生成；摘要输入使用轻清理 raw transcript")

    # 从 summarizer 获取 LLM 超时配置
    llm_timeout = getattr(request_summarizer, '_llm_timeout', 300.0)

    optimize_task = asyncio.create_task(
        _llm_call(request_summarizer.optimize_transcript, raw_script,
                  llm_timeout=llm_timeout, task_name="optimize_transcript")
    )

    # ── 阶段：生成摘要prompt + 生成摘要 ────────────────────────
    summary_prompt_content = ""

    if use_two_step:
        summary_task = asyncio.create_task(
            _llm_call(
                request_summarizer.summary_two_step,
                summary_source, summary_language, video_title,
                llm_timeout=llm_timeout, task_name="summary_two_step",
            )
        )
        await _broadcast_stage(task_id, "阅读内容", 100)
        await _broadcast_stage(task_id, "生成摘要prompt", 30)

        two_step_result = await summary_task
        summary = two_step_result["summary"]
        summary_prompt_content = two_step_result.get("prompt", "")
    else:
        summary_task = asyncio.create_task(
            _llm_call(
                request_summarizer.summarize,
                summary_source, summary_language, video_title,
                llm_timeout=llm_timeout, task_name="summarize",
            )
        )
        await _broadcast_stage(task_id, "阅读内容", 100)
        await _broadcast_stage(task_id, "生成摘要prompt", 100)
        await _broadcast_stage(task_id, "生成摘要", 50)

        summary = await summary_task
        summary_prompt_content = "(单步固定prompt模式)"

    summary_with_source = summary + f"\n\nsource: {source_ref}\n"

    summary_filename = f"summary_{safe_title}_{short_id}.md"
    summary_path = TEMP_DIR / summary_filename
    async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
        await f.write(summary_with_source)

    # 保存摘要prompt文件
    prompt_filename = f"summary-prompt_{safe_title}_{short_id}.md"
    prompt_path = TEMP_DIR / prompt_filename
    async with aiofiles.open(prompt_path, "w", encoding="utf-8") as f:
        await f.write(f"# 摘要Prompt\n\n{summary_prompt_content}\n")

    tasks[task_id].update({
        "message": "摘要已生成，Transcript 正在后台优化...",
        "summary": summary_with_source,
        "summary_ready": True,
        "transcript_ready": False,
        "summary_prompt_file": prompt_filename,
        "summary_path": str(summary_path),
        "video_title": video_title,
        "short_id": short_id,
        "safe_title": safe_title,
        "detected_language": detected_language,
        "summary_language": summary_language,
    })
    await _broadcast_stage(task_id, "生成摘要", 100)
    await _broadcast_stage(task_id, "优化转录", 20)
    save_tasks(tasks)  # 摘要已产出，做一次持久化检查点
    await broadcast_task_update(task_id, tasks[task_id])

    if not optimize_task.done():
        logger.info("摘要已完成，等待后台 Transcript 优化完成")
    try:
        script = await optimize_task
    except Exception as opt_err:
        logger.warning(f"Transcript 优化失败，使用原始文本: {opt_err}")
        script = raw_script
    script_with_title = f"# {video_title}\n\n{script}\n\nsource: {source_ref}\n"

    await _broadcast_stage(task_id, "优化转录", 100)

    # ── 保存文件 ────────────────────────────────────────────
    script_filename = f"transcript_{safe_title}_{short_id}.md"
    script_path = TEMP_DIR / script_filename
    async with aiofiles.open(script_path, "w", encoding="utf-8") as f:
        await f.write(script_with_title)

    task_result = {
        "status": "completed",
        "progress": 100,
        "message": "处理完成！",
        "video_title": video_title,
        "script": script_with_title,
        "summary": summary_with_source,
        "summary_ready": True,
        "transcript_ready": True,
        "summary_prompt_file": prompt_filename,
        "script_path": str(script_path),
        "summary_path": str(summary_path),
        "short_id": short_id,
        "safe_title": safe_title,
        "detected_language": detected_language,
        "summary_language": summary_language,
    }

    tasks[task_id].update(task_result)
    save_tasks(tasks)
    logger.info(f"任务完成，准备广播最终状态: {task_id}")
    await broadcast_task_update(task_id, tasks[task_id])
    logger.info(f"最终状态已广播: {task_id}")

    _finish_task(task_id, dedup_url)


@app.get("/")
async def read_root():
    """返回前端页面"""
    return FileResponse(str(PROJECT_ROOT / "static" / "index.html"))

@app.post("/api/models")
async def list_models(
    base_url: str = Form(default=""),
    api_key:  str = Form(default=""),
):
    """Proxy: fetch model list from any OpenAI-compatible API."""
    effective_key = api_key or os.getenv("OPENAI_API_KEY", "")
    effective_url = base_url.rstrip("/") or os.getenv("OPENAI_BASE_URL") or None

    if not effective_key:
        raise HTTPException(status_code=400, detail="API key is required")

    try:
        client = openai.OpenAI(api_key=effective_key, base_url=effective_url)
        resp   = await asyncio.to_thread(client.models.list)
        models = [{"id": m.id, "name": getattr(m, "name", m.id)} for m in resp.data]
        # Sort by id for readability
        models.sort(key=lambda x: x["id"])
        return {"data": models}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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

    video_title = _sanitize_title_for_filename(Path(safe_name).stem) or "upload"
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


@app.post("/api/process-video")
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

async def process_video_task(
    task_id: str,
    url: str,
    summary_language: str,
    api_key: str = "",
    model_base_url: str = "",
    model_id: str = "",
):
    """异步处理视频任务"""
    try:
        # 初始化阶段
        _init_task_stages(task_id, "url_summary")

        # ── 识别来源 ────────────────────────────────────────────
        await _broadcast_stage(task_id, "识别来源", 50)

        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id or None)
            logger.info(f"使用前端API Key, base_url={effective_url}, model={model_id or 'default'}")
        else:
            request_summarizer = summarizer

        # ── 查找字幕 ────────────────────────────────────────────
        await _broadcast_stage(task_id, "查找字幕", 50)
        subtitle_text, sub_title, sub_lang = await video_processor.fetch_subtitles(url, TEMP_DIR)

        if subtitle_text:
            # ── 快速路径：有字幕 ─────────────────────────────────
            video_title = sub_title
            raw_script = subtitle_text
            transcriber.last_detected_language = sub_lang

            tasks[task_id].update({"mode": "subtitle", "message": f"字幕获取成功（{sub_lang}）"})
            _skip_task_stages(task_id, ["下载音频", "准备音频", "转录"])
            await _broadcast_stage(task_id, "读取字幕", 100)
        else:
            # ── 慢速路径：下载音频 → Whisper ────────────────────
            tasks[task_id].update({"mode": "whisper"})
            _skip_task_stages(task_id, ["读取字幕"])

            await _broadcast_stage(task_id, "下载音频", 30)
            audio_path, video_title = await video_processor.download_and_convert(
                url, TEMP_DIR, prefetched_title=sub_title or None
            )
            await _broadcast_stage(task_id, "下载音频", 100)

            await _broadcast_stage(task_id, "准备音频", 100)

            await _broadcast_stage(task_id, "转录", 50)
            raw_script = await transcriber.transcribe(audio_path)
            await _broadcast_stage(task_id, "转录", 100)

        # 共用管线：优化 → 翻译 → 双步摘要
        await _run_post_extract_pipeline(
            task_id=task_id,
            raw_script=raw_script,
            video_title=video_title,
            source_ref=url,
            summary_language=summary_language,
            request_summarizer=request_summarizer,
            dedup_url=url,
            use_two_step=True,
        )

    except Exception as e:
        logger.error(f"任务 {task_id} 处理失败: {str(e)}")
        _finish_task(task_id, url)
        tasks[task_id].update({
            "status": "error",
            "error": str(e),
            "message": f"处理失败: {str(e)}"
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])

@app.post("/api/process-upload")
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


async def process_upload_task(
    task_id: str,
    saved_path: Path,
    original_name: str,
    video_title: str,
    ext_lower: str,
    summary_language: str,
    api_key: str = "",
    model_base_url: str = "",
    model_id: str = "",
):
    source_ref = f"upload:{original_name}"
    try:
        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id or None)
            logger.info(f"上传任务使用前端API Key, base_url={effective_url}, model={model_id or 'default'}")
        else:
            request_summarizer = summarizer

        if ext_lower == ".txt":
            _init_task_stages(task_id, "local_text")
            await _broadcast_stage(task_id, "读取文件", 100)

            body = saved_path.read_text(encoding="utf-8", errors="replace")
            if not body.strip():
                raise Exception("文本文件为空")
            transcriber.last_detected_language = None
            raw_script = _txt_to_raw_transcript_markdown(body)
        else:
            _init_task_stages(task_id, "local_audio")
            await _broadcast_stage(task_id, "读取文件", 100)

            await _broadcast_stage(task_id, "准备音频", 50)
            audio_path = await video_processor.normalize_local_media_to_m4a(saved_path, TEMP_DIR)
            await _broadcast_stage(task_id, "准备音频", 100)

            await _broadcast_stage(task_id, "转录", 50)
            raw_script = await transcriber.transcribe(audio_path)
            await _broadcast_stage(task_id, "转录", 100)

        await _run_post_extract_pipeline(
            task_id=task_id,
            raw_script=raw_script,
            video_title=video_title,
            source_ref=source_ref,
            summary_language=summary_language,
            request_summarizer=request_summarizer,
            dedup_url=None,
            use_two_step=True,
        )

    except Exception as e:
        logger.error(f"任务 {task_id} 处理失败: {str(e)}")
        _finish_task(task_id)
        tasks[task_id].update({
            "status": "error",
            "error": str(e),
            "message": f"处理失败: {str(e)}",
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])


@app.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str):
    """
    获取任务状态
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    _refresh_task_view_state(task_id)
    return tasks[task_id]

@app.get("/api/task-stream/{task_id}")
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

@app.get("/api/download/{filename}")
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


@app.delete("/api/task/{task_id}")
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


# ═══════════════════════════════════════════════════════════════
# 仅下载视频 API
# ═══════════════════════════════════════════════════════════════

@app.post("/api/download-video/formats")
async def get_video_formats(url: str = Form(...)):
    """获取视频的可用格式列表（含视频、音频、字幕）"""
    try:
        result = await video_processor.get_video_formats(url)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/download-audio")
async def start_download_audio(
    url: str = Form(...),
    format_id: str = Form(default="bestaudio/best"),
    filename: str = Form(default=""),
    audio_format: str = Form(default="m4a"),
):
    """开始下载音频（仅音频，不转录）"""
    try:
        if not url.strip():
            raise HTTPException(status_code=400, detail="请提供视频URL")

        task_id = str(uuid.uuid4())
        tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "准备下载音频...",
            "url": url,
            "type": "download_audio",
        }
        _init_task_stages(task_id, "download_only")
        save_tasks(tasks)

        task = asyncio.create_task(
            _run_download_audio_task(task_id, url, format_id, filename, audio_format)
        )
        active_tasks[task_id] = task

        return {"task_id": task_id, "message": "音频下载任务已创建"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建音频下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/download-subtitles")
async def start_download_subtitles(
    url: str = Form(...),
    lang: str = Form(default="en"),
    filename: str = Form(default=""),
):
    """开始下载字幕文件"""
    try:
        if not url.strip():
            raise HTTPException(status_code=400, detail="请提供视频URL")

        task_id = str(uuid.uuid4())
        tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "准备下载字幕...",
            "url": url,
            "type": "download_subtitles",
        }
        _init_task_stages(task_id, "download_only")
        save_tasks(tasks)

        task = asyncio.create_task(
            _run_download_subtitles_task(task_id, url, lang, filename)
        )
        active_tasks[task_id] = task

        return {"task_id": task_id, "message": "字幕下载任务已创建"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建字幕下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/download-video")
async def start_download_video(
    url: str = Form(...),
    format_id: str = Form(default="best"),
    filename: str = Form(default=""),
):
    """开始下载视频（仅下载，不转录）"""
    try:
        if not url.strip():
            raise HTTPException(status_code=400, detail="请提供视频URL")

        task_id = str(uuid.uuid4())

        tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "准备下载...",
            "url": url,
            "type": "download",
        }
        _init_task_stages(task_id, "download_only")
        save_tasks(tasks)

        task = asyncio.create_task(
            _run_download_video_task(task_id, url, format_id, filename)
        )
        active_tasks[task_id] = task

        return {"task_id": task_id, "message": "下载任务已创建"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _run_download_task(task_id: str, url: str, do_download):
    """通用下载任务执行器：识别标题 → 下载 → 广播完成/失败。

    do_download(video_title) 为协程，返回 (output_path, extra_fields, success_message)。
    视频/音频/字幕下载共用此骨架，仅下载这一步不同。
    """
    try:
        await _broadcast_stage(task_id, "识别资源", 50)
        video_title = await video_processor.get_video_title(url)
        await _broadcast_stage(task_id, "识别资源", 100)

        await _broadcast_stage(task_id, "下载", 10)
        output_path, extra_fields, success_message = await do_download(video_title)
        await _broadcast_stage(task_id, "下载", 100)

        tasks[task_id].update({
            "status": "completed",
            "progress": 100,
            "message": success_message,
            "video_title": video_title,
            "output_path": str(output_path),
            "filename": Path(output_path).name,
            **extra_fields,
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])

    except Exception as e:
        logger.error(f"下载任务 {task_id} 失败: {e}")
        tasks[task_id].update({
            "status": "error",
            "error": str(e),
            "message": f"下载失败: {str(e)}",
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
    finally:
        _finish_task(task_id)


async def _run_download_video_task(task_id: str, url: str, format_id: str, filename: str):
    """执行视频下载任务"""
    async def _dl(video_title):
        path = await video_processor.download_video_only(
            url, TEMP_DIR, format_id, filename or video_title
        )
        return path, {}, "下载完成！"
    await _run_download_task(task_id, url, _dl)


async def _run_download_audio_task(
    task_id: str, url: str, format_id: str, filename: str, audio_format: str
):
    """执行音频下载任务"""
    async def _dl(video_title):
        path = await video_processor.download_audio_only(
            url, TEMP_DIR, format_id, filename or video_title, audio_format
        )
        return path, {}, "音频下载完成！"
    await _run_download_task(task_id, url, _dl)


async def _run_download_subtitles_task(task_id: str, url: str, lang: str, filename: str):
    """执行字幕下载任务"""
    async def _dl(video_title):
        path, chosen_lang = await video_processor.download_subtitles_file(
            url, TEMP_DIR, lang, filename or video_title
        )
        return path, {"subtitle_lang": chosen_lang}, f"字幕下载完成！（{chosen_lang}）"
    await _run_download_task(task_id, url, _dl)


@app.get("/api/download-video/file/{filename}")
async def download_video_file(filename: str):
    """下载已保存的视频文件"""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="无效文件名")

    file_path = TEMP_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(file_path, filename=filename)


# ═══════════════════════════════════════════════════════════════
# RSS 订阅 API
# ═══════════════════════════════════════════════════════════════

@app.post("/api/rss/parse")
async def parse_rss_feed(feed_url: str = Form(...)):
    """抓取并解析 RSS/Atom。订阅数据由前端保存，不写入服务器。"""
    try:
        feed_info = await rss_reader.fetch_feed(feed_url)
        return {"feed": feed_info}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/rss/subscribe")
async def subscribe_rss_feed(feed_url: str = Form(...)):
    """添加RSS订阅（兼容旧接口：服务器 JSON 持久化）"""
    try:
        feed_info = await rss_reader.add_feed(feed_url)
        return {"feed": feed_info}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/rss/feeds")
async def list_rss_feeds():
    """列出所有RSS订阅"""
    try:
        feeds = rss_reader.list_feeds()
        return {"feeds": feeds}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rss/entries/{feed_id}")
async def list_rss_entries(feed_id: str):
    """获取订阅的条目列表"""
    try:
        entries = await rss_reader.get_entries(feed_id)
        return {"entries": entries}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/rss/create-task")
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

            tasks[task_id] = {
                "status": "processing",
                "progress": 0,
                "message": "准备下载...",
                "url": entry.get("enclosure_url"),
                "type": "download",
                "rss_entry": entry_title,
            }
            _init_task_stages(task_id, "download_only")
            save_tasks(tasks)

            task = asyncio.create_task(
                _run_download_video_task(
                    task_id, entry.get("enclosure_url"), "best", entry_title
                )
            )
            active_tasks[task_id] = task

        elif action == "summarize":
            tasks[task_id] = {
                "status": "processing",
                "progress": 0,
                "message": "开始处理RSS条目...",
                "url": entry_url,
                "type": "summary",
                "rss_entry": entry_title,
            }
            save_tasks(tasks)

            task = asyncio.create_task(
                _run_rss_summarize_task(
                    task_id, entry, summary_language, api_key, model_base_url, model_id
                )
            )
            active_tasks[task_id] = task

        else:
            raise HTTPException(status_code=400, detail=f"未知操作: {action}")

        return {"task_id": task_id, "message": f"任务已创建"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/rss/feed/{feed_id}")
async def delete_rss_feed(feed_id: str):
    """删除RSS订阅"""
    try:
        rss_reader.remove_feed(feed_id)
        return {"message": "订阅已删除"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/rss/refresh/{feed_id}")
async def refresh_rss_feed(feed_id: str):
    """刷新RSS订阅（增量拉取新条目）"""
    try:
        result = await rss_reader.refresh_feed(feed_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _run_rss_summarize_task(
    task_id: str,
    entry: dict,
    summary_language: str,
    api_key: str = "",
    model_base_url: str = "",
    model_id: str = "",
):
    """处理RSS条目的摘要任务"""
    entry_title = entry.get("title", "RSS条目")
    entry_link = entry.get("link", "")
    enclosure_url = entry.get("enclosure_url", "")
    entry_content = entry.get("content", "") or entry.get("summary", "")

    try:
        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id or None)
        else:
            request_summarizer = summarizer

        if enclosure_url:
            _init_task_stages(task_id, "url_summary")
            await _broadcast_stage(task_id, "识别来源", 50)

            # 先尝试字幕快速通道（与 URL 流程一致）
            subtitle_text, sub_title, sub_lang = await video_processor.fetch_subtitles(enclosure_url, TEMP_DIR)

            if subtitle_text:
                raw_script = subtitle_text
                transcriber.last_detected_language = sub_lang
                tasks[task_id].update({"mode": "subtitle", "message": f"字幕获取成功（{sub_lang}）"})
                _skip_task_stages(task_id, ["下载音频", "准备音频", "转录"])
                await _broadcast_stage(task_id, "查找字幕", 100)
                await _broadcast_stage(task_id, "读取字幕", 100)
            else:
                tasks[task_id].update({"mode": "whisper"})
                _skip_task_stages(task_id, ["读取字幕"])
                await _broadcast_stage(task_id, "查找字幕", 100)

                audio_path, title = await video_processor.download_and_convert(
                    enclosure_url, TEMP_DIR, prefetched_title=sub_title or entry_title,
                )
                await _broadcast_stage(task_id, "下载音频", 100)
                await _broadcast_stage(task_id, "准备音频", 100)

                await _broadcast_stage(task_id, "转录", 50)
                raw_script = await transcriber.transcribe(audio_path)
                await _broadcast_stage(task_id, "转录", 100)

            await _run_post_extract_pipeline(
                task_id=task_id,
                raw_script=raw_script,
                video_title=entry_title,
                source_ref=entry_link or enclosure_url,
                summary_language=summary_language,
                request_summarizer=request_summarizer,
                use_two_step=True,
            )
        elif entry_content.strip():
            _init_task_stages(task_id, "local_text")
            await _broadcast_stage(task_id, "读取文件", 100)

            raw_script = _txt_to_raw_transcript_markdown(entry_content)
            transcriber.last_detected_language = None

            await _run_post_extract_pipeline(
                task_id=task_id,
                raw_script=raw_script,
                video_title=entry_title,
                source_ref=entry_link or "RSS feed",
                summary_language=summary_language,
                request_summarizer=request_summarizer,
                use_two_step=True,
            )
        else:
            raise Exception("RSS条目没有可处理的内容")

    except Exception as e:
        logger.error(f"RSS摘要任务 {task_id} 失败: {e}")
        _finish_task(task_id)
        tasks[task_id].update({
            "status": "error",
            "error": str(e),
            "message": f"处理失败: {str(e)}",
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])


@app.get("/api/tasks/active")
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


@app.post("/api/retry/{task_id}")
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
        import re as _re
        raw_script = _re.sub(r'\n\nsource:.*$', '', raw_script, flags=_re.DOTALL)

        video_title = old_task.get("video_title", "Retry")
        source_ref = old_task.get("url", "retry")

        # 构造 Summarizer（优先用前端传入的 API 配置）
        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id or None)
        else:
            request_summarizer = summarizer

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
                await _run_post_extract_pipeline(
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
