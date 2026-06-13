"""编排/服务层：转录后处理管线与各类后台任务执行器。

本模块只负责"做事"（取得内容 → 优化/摘要 → 归档 → 广播），
不关心 HTTP 细节。HTTP 路由在 routers/ 下，依赖单例在 services.py。
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

import aiofiles

from cancellation import CancelledByUser
from db import get_task as _db_get_task, update_task as _db_update_task
from error_messages import humanize_error
from exceptions import LLMError, SourceError
from platforms import resolve_adapter
from rss_reader import fetch_article_text
from sources import extract_media_source
from summarizer import Summarizer
from services import (
    summarizer,
    transcriber,
    translator,
    video_processor,
)
from whisper_models import get_transcriber
from task_store import (
    TEMP_DIR,
    broadcast_stage as _broadcast_stage,
    broadcast_task_update,
    finish_task as _finish_task,
    init_task_stages as _init_task_stages,
    skip_task_stages as _skip_task_stages,
    update_task as _update_task,
)

logger = logging.getLogger(__name__)


async def _llm_call(fn, *args, llm_timeout: float = 300.0, task_name: str = ""):
    """在工作线程中运行阻塞式 LLM 调用（带超时保护）。"""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args), timeout=llm_timeout
        )
    except asyncio.TimeoutError:
        raise LLMError(
            f"LLM 调用超时（{llm_timeout}s），任务: {task_name or 'unknown'}，"
            "请检查 API 连接或尝试缩短内容"
        )


_AUDIO_ONLY_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus', '.aac', '.wma', '.weba'}
_AUDIO_MIME_PREFIXES = ('audio/',)


def _is_audio_only(url: str, enclosure_type: str = "") -> bool:
    if enclosure_type:
        return enclosure_type.startswith(_AUDIO_MIME_PREFIXES)
    from urllib.parse import urlparse
    path = urlparse(url).path.lower()
    for ext in _AUDIO_ONLY_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def _extract_callbacks(task_id: str, task_transcriber=None) -> dict:
    def _set_mode(mode: str, message):
        # fire-and-forget update
        asyncio.create_task(_update_task(task_id, mode=mode, message=message or ""))

    return {
        "video_processor": video_processor,
        "transcriber": task_transcriber or transcriber,
        "temp_dir": TEMP_DIR,
        "broadcast_stage": lambda stage, pct=0: _broadcast_stage(task_id, stage, pct),
        "skip_stages": lambda names: _skip_task_stages(task_id, names),
        "set_mode": _set_mode,
        "is_audio_only": _is_audio_only,
    }


def sanitize_title_for_filename(title: str) -> str:
    if not title:
        return "untitled"
    safe = re.sub(r"[^\w\-\s]", "", title)
    safe = re.sub(r"\s+", "_", safe).strip("._-")
    return safe[:80] or "untitled"


def txt_to_raw_transcript_markdown(body: str) -> str:
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


async def run_post_extract_pipeline(
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
    use_two_step: bool = True,
    detected_language: Optional[str] = None,
) -> None:
    short_id = task_id.replace("-", "")[:6]
    safe_title = sanitize_title_for_filename(video_title)

    # ── 保存原始转录 ─────────────────────────────────────
    try:
        raw_md_filename = f"raw_{safe_title}_{short_id}.md"
        raw_md_path = TEMP_DIR / raw_md_filename
        async with aiofiles.open(raw_md_path, "w", encoding="utf-8") as f:
            await f.write((raw_script or "") + f"\n\nsource: {source_ref}\n")
        await _update_task(task_id, raw_script_file=raw_md_filename)
    except Exception as e:
        logger.error(f"保存原始转录Markdown失败: {e}")

    # ── 阅读内容 ─────────────────────────────────────────
    await _broadcast_stage(task_id, "阅读内容", 50)

    summary_source = request_summarizer._remove_timestamps_and_meta(raw_script)

    detected_language = (detected_language or "").strip()
    if not detected_language:
        detected_language = (transcriber.get_detected_language(raw_script) or "").strip()
    if not detected_language:
        detected_language = translator.infer_language_code(raw_script)
    detected_language = translator.normalize_lang_code(detected_language) or detected_language

    logger.info(f"检测到的语言: {detected_language}, 摘要语言: {summary_language}")
    logger.info("并行启动: Transcript 优化 + 摘要生成")

    llm_timeout = getattr(request_summarizer, '_llm_timeout', 300.0)

    optimize_task = asyncio.create_task(
        _llm_call(request_summarizer.optimize_transcript, raw_script,
                  llm_timeout=llm_timeout, task_name="optimize_transcript")
    )

    # ── 生成摘要prompt + 生成摘要 ────────────────────────
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

    if not (summary or "").strip():
        logger.warning("摘要为空，使用备用摘要")
        summary = request_summarizer._generate_fallback_summary(
            summary_source, summary_language, video_title
        )

    summary_with_source = summary + f"\n\nsource: {source_ref}\n"

    summary_filename = f"summary_{safe_title}_{short_id}.md"
    summary_path = TEMP_DIR / summary_filename
    async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
        await f.write(summary_with_source)

    prompt_filename = f"summary-prompt_{safe_title}_{short_id}.md"
    prompt_path = TEMP_DIR / prompt_filename
    async with aiofiles.open(prompt_path, "w", encoding="utf-8") as f:
        await f.write(f"# 摘要Prompt\n\n{summary_prompt_content}\n")

    await _update_task(task_id,
        message="摘要已生成，Transcript 正在后台优化...",
        summary=summary_with_source,
        summary_ready=True,
        transcript_ready=False,
        summary_prompt_file=prompt_filename,
        summary_path=str(summary_path),
        video_title=video_title,
        short_id=short_id,
        safe_title=safe_title,
        detected_language=detected_language,
        summary_language=summary_language,
    )
    await _broadcast_stage(task_id, "生成摘要", 100)
    await _broadcast_stage(task_id, "优化转录", 20)

    # 广播当前状态（摘要已就绪）
    task_data = await _db_get_task(task_id)
    if task_data:
        await broadcast_task_update(task_id, task_data)

    if not optimize_task.done():
        logger.info("摘要已完成，等待后台 Transcript 优化完成")
    try:
        script = await optimize_task
    except Exception as opt_err:
        logger.warning(f"Transcript 优化失败，使用原始文本: {opt_err}")
        script = raw_script
    if not (script or "").strip():
        logger.warning("Transcript 优化结果为空，使用原始文本")
        script = raw_script
    script_with_title = f"# {video_title}\n\n{script}\n\nsource: {source_ref}\n"

    await _broadcast_stage(task_id, "优化转录", 100)

    # ── 保存文件 ────────────────────────────────────────────
    script_filename = f"transcript_{safe_title}_{short_id}.md"
    script_path = TEMP_DIR / script_filename
    async with aiofiles.open(script_path, "w", encoding="utf-8") as f:
        await f.write(script_with_title)

    await _update_task(task_id,
        status="completed",
        progress=100,
        message="处理完成！",
        video_title=video_title,
        script=script_with_title,
        summary=summary_with_source,
        summary_ready=True,
        transcript_ready=True,
        summary_prompt_file=prompt_filename,
        script_path=str(script_path),
        summary_path=str(summary_path),
        short_id=short_id,
        safe_title=safe_title,
        detected_language=detected_language,
        summary_language=summary_language,
    )

    task_data = await _db_get_task(task_id)
    if task_data:
        await broadcast_task_update(task_id, task_data)

    _finish_task(task_id, dedup_url)


async def regenerate_summary(
    task_id: str,
    request_summarizer: Summarizer,
    summary_language: str,
    use_two_step: bool = True,
) -> None:
    try:
        old_task = await _db_get_task(task_id)
        if not old_task:
            raise SourceError("任务不存在")
        video_title = old_task.get("video_title", "")
        source_ref = old_task.get("url", "retry")
        short_id = old_task.get("short_id", task_id.replace("-", "")[:6])
        safe_title = old_task.get("safe_title", sanitize_title_for_filename(video_title))

        script_path = old_task.get("script_path")
        raw_script_file = old_task.get("raw_script_file")
        if script_path and Path(script_path).exists():
            transcript_text = await asyncio.to_thread(Path(script_path).read_text, encoding="utf-8")
        elif raw_script_file and (TEMP_DIR / raw_script_file).exists():
            transcript_text = await asyncio.to_thread((TEMP_DIR / raw_script_file).read_text, encoding="utf-8")
        else:
            transcript_text = old_task.get("script") or ""

        transcript_text = re.sub(r"\n\nsource:.*$", "", transcript_text, flags=re.DOTALL)
        if not transcript_text.strip():
            raise SourceError("没有可用的转录文本，无法重新生成摘要")

        llm_timeout = getattr(request_summarizer, "_llm_timeout", 300.0)
        summary_source = request_summarizer._remove_timestamps_and_meta(transcript_text)

        await _init_task_stages(task_id, "retry")
        await _broadcast_stage(task_id, "阅读内容", 50)
        await _broadcast_stage(task_id, "阅读内容", 100)
        await _broadcast_stage(task_id, "生成摘要prompt", 30)

        if use_two_step:
            two_step_result = await _llm_call(
                request_summarizer.summary_two_step,
                summary_source, summary_language, video_title,
                llm_timeout=llm_timeout, task_name="summary_two_step",
            )
            summary = two_step_result["summary"]
            summary_prompt_content = two_step_result.get("prompt", "")
        else:
            summary = await _llm_call(
                request_summarizer.summarize,
                summary_source, summary_language, video_title,
                llm_timeout=llm_timeout, task_name="summarize",
            )
            summary_prompt_content = "(单步固定prompt模式)"

        if not (summary or "").strip():
            logger.warning("重新生成摘要为空，使用备用摘要")
            summary = request_summarizer._generate_fallback_summary(
                summary_source, summary_language, video_title
            )

        summary_with_source = summary + f"\n\nsource: {source_ref}\n"

        summary_filename = f"summary_{safe_title}_{short_id}.md"
        summary_path = TEMP_DIR / summary_filename
        async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
            await f.write(summary_with_source)

        prompt_filename = f"summary-prompt_{safe_title}_{short_id}.md"
        prompt_path = TEMP_DIR / prompt_filename
        async with aiofiles.open(prompt_path, "w", encoding="utf-8") as f:
            await f.write(f"# 摘要Prompt\n\n{summary_prompt_content}\n")

        await _update_task(task_id,
            status="completed",
            progress=100,
            message="摘要已重新生成！",
            summary=summary_with_source,
            summary_ready=True,
            summary_path=str(summary_path),
            summary_prompt_file=prompt_filename,
            summary_language=summary_language,
        )
        await _broadcast_stage(task_id, "生成摘要", 100)
        await _skip_task_stages(task_id, ["优化转录"])
        await _broadcast_stage(task_id, "优化转录", 100)

        task_data = await _db_get_task(task_id)
        if task_data:
            await broadcast_task_update(task_id, task_data)

    except Exception as e:
        logger.error(f"重新生成摘要失败 {task_id}: {e}", exc_info=True)
        if await _update_task(task_id, status="error", error=str(e), message=f"重新生成摘要失败: {str(e)}"):
            task_data = await _db_get_task(task_id)
            if task_data:
                await broadcast_task_update(task_id, task_data)
    finally:
        _finish_task(task_id)


async def process_video_task(
    task_id: str,
    url: str,
    summary_language: str,
    api_key: str = "",
    model_base_url: str = "",
    model_id: str = "",
    whisper_model: str = "",
):
    try:
        task_transcriber = get_transcriber(whisper_model) if whisper_model else get_transcriber()
        await _init_task_stages(task_id, "url_summary")
        await _broadcast_stage(task_id, "识别来源", 50)

        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id)
            logger.info(f"使用前端模型配置, base_url={effective_url}, model={model_id or '未指定'}")
        else:
            request_summarizer = summarizer

        result = await extract_media_source(
            task_id, url,
            fetch_title_when_audio_only=True,
            **_extract_callbacks(task_id, task_transcriber),
        )

        await run_post_extract_pipeline(
            task_id=task_id,
            raw_script=result.raw_script,
            video_title=result.extracted_title,
            source_ref=url,
            summary_language=summary_language,
            request_summarizer=request_summarizer,
            dedup_url=url,
            use_two_step=True,
            detected_language=result.detected_language,
        )

    except CancelledByUser:
        raise  # 让队列层按"已取消"处理，而非误标为 error
    except Exception as e:
        logger.error(f"任务 {task_id} 处理失败: {str(e)}", exc_info=True)
        _finish_task(task_id, url)
        if await _update_task(task_id, status="error", error=str(e), message=humanize_error(e)):
            task_data = await _db_get_task(task_id)
            if task_data:
                await broadcast_task_update(task_id, task_data)


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
    whisper_model: str = "",
):
    source_ref = f"upload:{original_name}"
    task_transcriber = get_transcriber(whisper_model) if whisper_model else get_transcriber()
    try:
        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id)
            logger.info(f"上传任务使用前端模型配置, base_url={effective_url}, model={model_id or '未指定'}")
        else:
            request_summarizer = summarizer

        if ext_lower in (".txt", ".md"):
            await _init_task_stages(task_id, "local_text")
            await _broadcast_stage(task_id, "读取文件", 100)
            body = await asyncio.to_thread(saved_path.read_text, encoding="utf-8", errors="replace")
            if not body.strip():
                raise SourceError("文本文件为空")
            raw_script = txt_to_raw_transcript_markdown(body)
        else:
            await _init_task_stages(task_id, "local_audio")
            await _broadcast_stage(task_id, "读取文件", 100)
            await _broadcast_stage(task_id, "准备音频", 50)
            audio_path = await video_processor.normalize_local_media_to_m4a(saved_path, TEMP_DIR)
            await _broadcast_stage(task_id, "准备音频", 100)
            await _broadcast_stage(task_id, "转录", 50)
            raw_script = await task_transcriber.transcribe(audio_path)
            await _broadcast_stage(task_id, "转录", 100)
            # 归一化后的中间音频转录完即可删除，避免 TEMP_DIR 堆积。
            try:
                Path(audio_path).unlink(missing_ok=True)
            except Exception as _e:
                logger.warning(f"清理上传归一化音频失败（不影响结果）: {_e}")

        # 内容已提取，上传的原始文件不再需要。
        try:
            saved_path.unlink(missing_ok=True)
        except Exception as _e:
            logger.warning(f"清理上传原始文件失败（不影响结果）: {_e}")

        await run_post_extract_pipeline(
            task_id=task_id,
            raw_script=raw_script,
            video_title=video_title,
            source_ref=source_ref,
            summary_language=summary_language,
            request_summarizer=request_summarizer,
            dedup_url=None,
            use_two_step=True,
        )

    except CancelledByUser:
        raise  # 让队列层按"已取消"处理，而非误标为 error
    except Exception as e:
        logger.error(f"任务 {task_id} 处理失败: {str(e)}", exc_info=True)
        _finish_task(task_id)
        if await _update_task(task_id, status="error", error=str(e), message=humanize_error(e)):
            task_data = await _db_get_task(task_id)
            if task_data:
                await broadcast_task_update(task_id, task_data)


async def run_download_task(task_id: str, url: str, do_download):
    try:
        await _broadcast_stage(task_id, "识别资源", 50)
        video_title = await video_processor.get_video_title(url)
        await _broadcast_stage(task_id, "识别资源", 100)

        await _broadcast_stage(task_id, "下载", 10)
        output_path, extra_fields, success_message = await do_download(video_title)
        await _broadcast_stage(task_id, "下载", 100)

        await _update_task(task_id,
            status="completed",
            progress=100,
            message=success_message,
            video_title=video_title,
            output_path=str(output_path),
            filename=Path(output_path).name,
            **extra_fields,
        )

        task_data = await _db_get_task(task_id)
        if task_data:
            await broadcast_task_update(task_id, task_data)

    except CancelledByUser:
        raise  # 让队列层按"已取消"处理，而非误标为 error
    except Exception as e:
        logger.error(f"下载任务 {task_id} 失败: {e}", exc_info=True)
        if await _update_task(task_id, status="error", error=str(e), message=humanize_error(e)):
            task_data = await _db_get_task(task_id)
            if task_data:
                await broadcast_task_update(task_id, task_data)
    finally:
        _finish_task(task_id)


async def run_download_video_task(task_id: str, url: str, format_id: str, filename: str):
    async def _dl(video_title):
        path = await video_processor.download_video_only(url, TEMP_DIR, format_id, filename or video_title)
        return path, {}, "下载完成！"
    await run_download_task(task_id, url, _dl)


async def run_download_audio_task(task_id: str, url: str, format_id: str, filename: str, audio_format: str):
    async def _dl(video_title):
        path = await video_processor.download_audio_only(url, TEMP_DIR, format_id, filename or video_title, audio_format)
        return path, {}, "音频下载完成！"
    await run_download_task(task_id, url, _dl)


async def run_download_subtitles_task(task_id: str, url: str, lang: str, filename: str):
    async def _dl(video_title):
        path, chosen_lang = await video_processor.download_subtitles_file(url, TEMP_DIR, lang, filename or video_title)
        return path, {"subtitle_lang": chosen_lang}, f"字幕下载完成！（{chosen_lang}）"
    await run_download_task(task_id, url, _dl)


async def run_rss_summarize_task(
    task_id: str,
    entry: dict,
    summary_language: str,
    api_key: str = "",
    model_base_url: str = "",
    model_id: str = "",
):
    entry_title = entry.get("title", "RSS条目")
    entry_link = entry.get("link", "")
    enclosure_url = entry.get("enclosure_url", "")
    enclosure_type = entry.get("enclosure_type", "")
    entry_content = entry.get("content", "") or entry.get("summary", "")

    # 没有 enclosure 但 link 指向已知视频平台（如 YouTube watch URL）时，
    # 把 entry.link 当媒体源，走与「粘贴视频 URL」相同的转录管线，而非当文章抓正文。
    media_url = enclosure_url
    media_type = enclosure_type
    if not media_url and entry_link and resolve_adapter(entry_link).name != "generic":
        media_url = entry_link
        media_type = ""  # 视频 watch URL 无 MIME，交由下游探测

    try:
        if api_key:
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(api_key=api_key, base_url=effective_url, model=model_id)
        else:
            request_summarizer = summarizer

        if media_url:
            await _init_task_stages(task_id, "url_summary")
            await _broadcast_stage(task_id, "识别来源", 50)
            result = await extract_media_source(
                task_id, media_url,
                enclosure_type=media_type,
                prefetched_title=entry_title,
                fetch_title_when_audio_only=False,
                **_extract_callbacks(task_id),
            )
            await run_post_extract_pipeline(
                task_id=task_id,
                raw_script=result.raw_script,
                video_title=entry_title,
                source_ref=entry_link or enclosure_url,
                summary_language=summary_language,
                request_summarizer=request_summarizer,
                use_two_step=True,
                detected_language=result.detected_language,
            )
        else:
            article_text = entry_content.strip()
            if not article_text and entry_link:
                article_text = await fetch_article_text(entry_link)
            if not article_text:
                raise SourceError("RSS条目没有可处理的内容")

            await _init_task_stages(task_id, "local_text")
            await _broadcast_stage(task_id, "读取文件", 100)
            raw_script = txt_to_raw_transcript_markdown(article_text)
            await run_post_extract_pipeline(
                task_id=task_id,
                raw_script=raw_script,
                video_title=entry_title,
                source_ref=entry_link or "RSS feed",
                summary_language=summary_language,
                request_summarizer=request_summarizer,
                use_two_step=True,
            )

    except CancelledByUser:
        raise  # 让队列层按"已取消"处理，而非误标为 error
    except Exception as e:
        logger.error(f"RSS摘要任务 {task_id} 失败: {e}", exc_info=True)
        _finish_task(task_id)
        if await _update_task(task_id, status="error", error=str(e), message=humanize_error(e)):
            task_data = await _db_get_task(task_id)
            if task_data:
                await broadcast_task_update(task_id, task_data)
