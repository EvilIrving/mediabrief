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

from rss_reader import fetch_article_text
from summarizer import Summarizer
from services import (
    summarizer,
    transcriber,
    translator,
    video_processor,
)
from task_store import (
    TEMP_DIR,
    broadcast_stage as _broadcast_stage,
    broadcast_task_update,
    finish_task as _finish_task,
    init_task_stages as _init_task_stages,
    save_tasks,
    skip_task_stages as _skip_task_stages,
    tasks,
)

logger = logging.getLogger(__name__)


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


def sanitize_title_for_filename(title: str) -> str:
    """将视频标题清洗为安全的文件名片段。"""
    if not title:
        return "untitled"
    safe = re.sub(r"[^\w\-\s]", "", title)
    safe = re.sub(r"\s+", "_", safe).strip("._-")
    return safe[:80] or "untitled"


def txt_to_raw_transcript_markdown(body: str) -> str:
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
    use_two_step: bool = True,  # 是否使用双步摘要
) -> None:
    """取得 raw_script 后的共用管线：归档、优化、翻译、摘要、广播。"""
    short_id = task_id.replace("-", "")[:6]
    safe_title = sanitize_title_for_filename(video_title)

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

    # 兜底：摘要器各路径已做空输出回退，这里再防一道，避免写出空摘要文件
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
    # 空优化结果（模型返回空 / 全部分块塌缩）兜底为原始文本，避免写出空转录
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


async def regenerate_summary(
    task_id: str,
    request_summarizer: Summarizer,
    summary_language: str,
    use_two_step: bool = True,
) -> None:
    """仅重新生成摘要（不重跑转录/优化），原地覆盖原任务的 summary 字段。

    从已有任务的优化转录（script_path）或原始转录（raw_script_file）中
    读取文本作为摘要输入，重新调用 LLM 摘要，然后将结果写回同一个 task_id。"""
    old_task = tasks.get(task_id, {})
    video_title = old_task.get("video_title", "")
    source_ref = old_task.get("url", "retry")
    short_id = old_task.get("short_id", task_id.replace("-", "")[:6])
    safe_title = old_task.get("safe_title", sanitize_title_for_filename(video_title))

    # 摘要输入：优先用已有优化转录，否则用原始转录
    script_path = old_task.get("script_path")
    raw_script_file = old_task.get("raw_script_file")
    if script_path and Path(script_path).exists():
        transcript_text = Path(script_path).read_text(encoding="utf-8")
    elif raw_script_file and (TEMP_DIR / raw_script_file).exists():
        transcript_text = (TEMP_DIR / raw_script_file).read_text(encoding="utf-8")
    else:
        transcript_text = old_task.get("script") or ""
    # 移除末尾 source 行
    transcript_text = re.sub(r"\n\nsource:.*$", "", transcript_text, flags=re.DOTALL)

    if not transcript_text.strip():
        raise Exception("没有可用的转录文本，无法重新生成摘要")

    llm_timeout = getattr(request_summarizer, "_llm_timeout", 300.0)
    summary_source = request_summarizer._remove_timestamps_and_meta(transcript_text)

    _init_task_stages(task_id, "retry")
    await _broadcast_stage(task_id, "阅读内容", 50)
    await _broadcast_stage(task_id, "阅读内容", 100)
    await _broadcast_stage(task_id, "生成摘要prompt", 30)

    # 运行摘要（双步或单步），不运行 transcript 优化
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

    # 空摘要兜底
    if not (summary or "").strip():
        logger.warning("重新生成摘要为空，使用备用摘要")
        summary = request_summarizer._generate_fallback_summary(
            summary_source, summary_language, video_title
        )

    summary_with_source = summary + f"\n\nsource: {source_ref}\n"

    # ── 覆盖摘要文件 ──────────────────────────────────────────
    summary_filename = f"summary_{safe_title}_{short_id}.md"
    summary_path = TEMP_DIR / summary_filename
    async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
        await f.write(summary_with_source)

    prompt_filename = f"summary-prompt_{safe_title}_{short_id}.md"
    prompt_path = TEMP_DIR / prompt_filename
    async with aiofiles.open(prompt_path, "w", encoding="utf-8") as f:
        await f.write(f"# 摘要Prompt\n\n{summary_prompt_content}\n")

    # ── 原地更新任务 ──────────────────────────────────────────
    tasks[task_id].update({
        "status": "completed",
        "progress": 100,
        "message": "摘要已重新生成！",
        "summary": summary_with_source,
        "summary_ready": True,
        "summary_path": str(summary_path),
        "summary_prompt_file": prompt_filename,
        "summary_language": summary_language,
    })
    await _broadcast_stage(task_id, "生成摘要", 100)
    # 跳过优化转录阶段（不需要重跑）
    _skip_task_stages(task_id, ["优化转录"])
    await _broadcast_stage(task_id, "优化转录", 100)
    save_tasks(tasks)
    await broadcast_task_update(task_id, tasks[task_id])

    _finish_task(task_id)


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
        await run_post_extract_pipeline(
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
            raw_script = txt_to_raw_transcript_markdown(body)
        else:
            _init_task_stages(task_id, "local_audio")
            await _broadcast_stage(task_id, "读取文件", 100)

            await _broadcast_stage(task_id, "准备音频", 50)
            audio_path = await video_processor.normalize_local_media_to_m4a(saved_path, TEMP_DIR)
            await _broadcast_stage(task_id, "准备音频", 100)

            await _broadcast_stage(task_id, "转录", 50)
            raw_script = await transcriber.transcribe(audio_path)
            await _broadcast_stage(task_id, "转录", 100)

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


async def run_download_task(task_id: str, url: str, do_download):
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


async def run_download_video_task(task_id: str, url: str, format_id: str, filename: str):
    """执行视频下载任务"""
    async def _dl(video_title):
        path = await video_processor.download_video_only(
            url, TEMP_DIR, format_id, filename or video_title
        )
        return path, {}, "下载完成！"
    await run_download_task(task_id, url, _dl)


async def run_download_audio_task(
    task_id: str, url: str, format_id: str, filename: str, audio_format: str
):
    """执行音频下载任务"""
    async def _dl(video_title):
        path = await video_processor.download_audio_only(
            url, TEMP_DIR, format_id, filename or video_title, audio_format
        )
        return path, {}, "音频下载完成！"
    await run_download_task(task_id, url, _dl)


async def run_download_subtitles_task(task_id: str, url: str, lang: str, filename: str):
    """执行字幕下载任务"""
    async def _dl(video_title):
        path, chosen_lang = await video_processor.download_subtitles_file(
            url, TEMP_DIR, lang, filename or video_title
        )
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

            await run_post_extract_pipeline(
                task_id=task_id,
                raw_script=raw_script,
                video_title=entry_title,
                source_ref=entry_link or enclosure_url,
                summary_language=summary_language,
                request_summarizer=request_summarizer,
                use_two_step=True,
            )
        else:
            # feed 条目自带正文优先；否则（如 surma.dev 这类只给标题+链接的
            # feed）回到 link 指向的网页提取正文。
            article_text = entry_content.strip()
            if not article_text and entry_link:
                article_text = await fetch_article_text(entry_link)
            if not article_text:
                raise Exception("RSS条目没有可处理的内容")

            _init_task_stages(task_id, "local_text")
            await _broadcast_stage(task_id, "读取文件", 100)

            raw_script = txt_to_raw_transcript_markdown(article_text)
            transcriber.last_detected_language = None

            await run_post_extract_pipeline(
                task_id=task_id,
                raw_script=raw_script,
                video_title=entry_title,
                source_ref=entry_link or "RSS feed",
                summary_language=summary_language,
                request_summarizer=request_summarizer,
                use_two_step=True,
            )

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
