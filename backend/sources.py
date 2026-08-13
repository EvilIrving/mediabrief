"""来源提取层：把"从一个媒体 URL 取得原始转录文本"的分支逻辑收敛到一处。

此前 ``process_video_task``（普通 URL）和 ``run_rss_summarize_task``（RSS enclosure）
各自复制了同一套 "音频探测 → 查找字幕 → 字幕快速通道 / 下载音频走 Whisper" 的流程。
任何分支改动都得改两处，且容易不一致。

这里抽出 ``extract_media_source``：输入一个媒体 URL，输出统一的 ``ExtractResult``。
新增输入类型（如某播客 API、整张播放列表）时，只需复用本函数或新增一个并列的
提取器，而无需再复制 40 行编排代码。HTTP/任务编排细节仍留在 ``pipeline.py``。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cancellation import CancelledByUser
from exceptions import MediaExtractionError, MediaRecoveryActionRequired
from media_contracts import (
    AudioAnalysisStatus,
    AudioProfile,
    ExtractionAction,
    ExtractionFailure,
    SubtitleFetchResult,
    SubtitleFetchStatus,
    TranscriptQualityReport,
    TranscriptionOutcome,
    TranscriptionStrategy,
    sanitize_diagnostic,
    sanitize_source_reference,
)
from transcription_strategy import select_transcription_strategy
from transcript_quality import evaluate_transcript, parse_markdown_segments

logger = logging.getLogger(__name__)


@dataclass
class ExtractResult:
    """媒体来源提取结果，供 ``run_post_extract_pipeline`` 直接消费。"""

    raw_script: str
    # 提取过程得到的标题（字幕标题或 Whisper 下载标题）；调用方可选择是否采用。
    extracted_title: Optional[str]
    # 已知的源语言（字幕路径有 sub_lang；Whisper 路径为 None，由下游从转录解析）。
    detected_language: Optional[str]
    # "subtitle" 或 "whisper"，用于前端展示与进度。
    mode: str
    # 字幕边界的明确状态；纯音频源为 skipped。
    subtitle_status: SubtitleFetchStatus
    # 字幕路径故障后即使音频回退成功，业务层仍能取得脱敏失败现场。
    extraction_failure: Optional[ExtractionFailure] = None
    # 只有 Whisper 路径有音频体检；字幕快速路径为 None。
    audio_profile: Optional[AudioProfile] = None
    transcription_strategy: Optional[TranscriptionStrategy] = None
    quality_report: Optional[TranscriptQualityReport] = None


async def transcribe_audio_with_profile(
    transcriber,
    audio_path: str,
    audio_profile: AudioProfile,
    *,
    progress_callback=None,
    language: Optional[str] = None,
) -> TranscriptionOutcome:
    """策略选择与质量复核的统一宿主入口。"""
    model_id = str(getattr(transcriber, "model_size", "base") or "base")
    try:
        strategy = select_transcription_strategy(
            audio_profile,
            model_id=model_id,
            language=language,
        )
    except CancelledByUser:
        raise
    except Exception as exc:
        logger.warning("转录策略选择失败，使用当前默认路径: %s", sanitize_diagnostic(exc))
        strategy = TranscriptionStrategy.current_default(model_id)

    quality_transcribe = getattr(transcriber, "transcribe_with_quality", None)
    if callable(quality_transcribe):
        outcome = await quality_transcribe(
            audio_path,
            audio_profile=audio_profile,
            strategy=strategy,
            progress_callback=progress_callback,
        )
        if not isinstance(outcome, TranscriptionOutcome):
            raise TypeError("transcribe_with_quality must return TranscriptionOutcome")
        return outcome

    # 受控的旧 ASR provider 兼容路径：保留默认转录，仍给出确定性报告。
    legacy_kwargs = {"progress_callback": progress_callback}
    if language is not None:
        legacy_kwargs["language"] = language
    transcript = await transcriber.transcribe(audio_path, **legacy_kwargs)
    report = evaluate_transcript(parse_markdown_segments(transcript), audio_profile)
    return TranscriptionOutcome(transcript, strategy, report)


async def extract_media_source(
    task_id: str,
    url: str,
    *,
    video_processor,
    transcriber,
    temp_dir: Path,
    broadcast_stage,
    skip_stages,
    set_mode,
    enclosure_type: str = "",
    prefetched_title: Optional[str] = None,
    fetch_title_when_audio_only: bool = False,
    is_audio_only,
    analyze_audio=None,
    recover_media=None,
) -> ExtractResult:
    """统一的"字幕快速通道 / Whisper 慢速通道"提取流程。

    依赖（video_processor / transcriber / 各阶段回调）以参数注入，使本模块不直接
    耦合 services 与 task_store，便于单测与替换。各回调语义：
    - ``broadcast_stage(stage, pct)``  广播阶段进度（协程）
    - ``skip_stages([...])``           标记跳过的阶段
    - ``set_mode(mode, message)``      记录 subtitle/whisper 模式与提示文案
    """
    subtitle_text = None
    sub_title = prefetched_title
    sub_lang = None
    sub_duration = 0
    subtitle_status = SubtitleFetchStatus.SKIPPED
    extraction_failure = None

    if is_audio_only(url, enclosure_type):
        # 纯音频：跳过字幕探测
        logger.info("检测到音频源，跳过字幕查找: %s", sanitize_source_reference(url))
        await skip_stages(["find_subtitles", "read_subtitles"])
        if fetch_title_when_audio_only:
            sub_title = await video_processor.get_video_title(url)
    else:
        await broadcast_stage("find_subtitles", 50)
        subtitle_result: SubtitleFetchResult = await video_processor.fetch_subtitles(url, temp_dir)
        subtitle_status = subtitle_result.status
        subtitle_text = subtitle_result.text
        sub_title = subtitle_result.title
        sub_lang = subtitle_result.language
        sub_duration = subtitle_result.duration_seconds
        extraction_failure = subtitle_result.failure

    if subtitle_text:
        # ── 快速路径：有字幕 ─────────────────────────────────
        set_mode("subtitle", f"字幕获取成功（{sub_lang}）")
        await skip_stages(["download_audio", "prepare_audio", "transcribe"])
        if not is_audio_only(url, enclosure_type):
            await broadcast_stage("find_subtitles", 100)
        await broadcast_stage("read_subtitles", 100)
        return ExtractResult(
            raw_script=subtitle_text,
            extracted_title=sub_title,
            detected_language=sub_lang,
            mode="subtitle",
            subtitle_status=subtitle_status,
            audio_profile=None,
        )

    # ── 慢速路径：下载音频 → Whisper ────────────────────────
    set_mode("whisper", None)
    await skip_stages(["read_subtitles"])
    if not is_audio_only(url, enclosure_type):
        await broadcast_stage("find_subtitles", 100)

    await broadcast_stage("download_audio", 30)
    previous_actions: tuple[ExtractionAction, ...] = ()
    if extraction_failure is not None:
        previous_actions = extraction_failure.attempted_actions
    elif subtitle_status is SubtitleFetchStatus.NO_SUBTITLES:
        previous_actions = (ExtractionAction.INSPECT_METADATA,)
    elif subtitle_status is SubtitleFetchStatus.SKIPPED and fetch_title_when_audio_only:
        previous_actions = (ExtractionAction.INSPECT_METADATA,)
    try:
        audio_path, video_title = await video_processor.download_and_convert(
            url,
            temp_dir,
            prefetched_title=sub_title or None,
            prefetched_duration=sub_duration or 0,
            previous_actions=previous_actions,
        )
    except MediaExtractionError as exc:
        original_error = exc
        if extraction_failure is not None:
            original_error = MediaExtractionError(
                exc.failure,
                previous_failures=(*exc.previous_failures, extraction_failure),
            )
        if recover_media is None:
            raise original_error from None

        # 只有现有字幕+音频路径都失败后才进入恢复 Loop；模型不可用/判断失败时
        # 原样抛回已有结构化错误，不能用恢复层的次生错误覆盖真实现场。
        from media_recovery import RecoveryRunStatus

        recovery = await recover_media(url, exc.failure)
        if recovery.status is RecoveryRunStatus.CANCELLED:
            raise CancelledByUser()
        if recovery.status is RecoveryRunStatus.ACTION_REQUIRED:
            raise MediaRecoveryActionRequired(recovery) from None
        if recovery.status is not RecoveryRunStatus.RECOVERED:
            raise original_error from None
        if recovery.subtitle_text:
            await skip_stages(["download_audio", "prepare_audio", "transcribe"])
            return ExtractResult(
                raw_script=recovery.subtitle_text,
                extracted_title=recovery.title or sub_title,
                detected_language=recovery.language,
                mode="subtitle",
                subtitle_status=SubtitleFetchStatus.FOUND,
                extraction_failure=extraction_failure,
                audio_profile=None,
            )
        audio_path = recovery.media_path
        video_title = recovery.title or sub_title or "unknown"
        if not audio_path:
            raise original_error from None
    await broadcast_stage("download_audio", 100)
    await broadcast_stage("prepare_audio", 50)

    try:
        audio_profile = await analyze_audio(audio_path) if analyze_audio else AudioProfile()
        if not isinstance(audio_profile, AudioProfile):
            raise TypeError("audio analyzer must return AudioProfile")
    except CancelledByUser:
        raise
    except Exception as exc:
        # 音频分析是策略输入，不是转录硬依赖；失败必须保留原默认路径。
        logger.warning("音频分析失败，将继续默认转录: %s", sanitize_diagnostic(exc))
        audio_profile = AudioProfile(
            analysis_status=AudioAnalysisStatus.FAILED,
            analysis_error=sanitize_diagnostic(exc),
        )
    await broadcast_stage("prepare_audio", 100)

    await broadcast_stage("transcribe", 50)
    async def _report_transcribe_progress(pct: float):
        await broadcast_stage("transcribe", message=f"{pct}%")
    transcription = await transcribe_audio_with_profile(
        transcriber,
        audio_path,
        audio_profile,
        progress_callback=_report_transcribe_progress,
    )
    raw_script = transcription.transcript
    await broadcast_stage("transcribe", 100)

    # 转录已完成，下载的中间音频不再需要，立即删除以免 TEMP_DIR 无限膨胀。
    try:
        Path(audio_path).unlink(missing_ok=True)
    except Exception as e:
        logger.warning("清理中间音频失败（不影响结果）: %s", sanitize_diagnostic(e))

    return ExtractResult(
        raw_script=raw_script,
        extracted_title=video_title,
        detected_language=None,
        mode="whisper",
        subtitle_status=subtitle_status,
        extraction_failure=extraction_failure,
        audio_profile=audio_profile,
        transcription_strategy=transcription.strategy,
        quality_report=transcription.quality_report,
    )
