import os
import re
import sys
import types
import asyncio
import threading
import logging
import concurrent.futures
from typing import Optional, Callable, Awaitable

import cancellation
from cancellation import CancelledByUser
from exceptions import TranscriptionError
from media_contracts import (
    AudioAnalysisStatus,
    AudioProfile,
    ChunkBoundaryProfile,
    DecodeProfile,
    FinalTranscriptSelection,
    LanguageMode,
    StrategyProfile,
    TranscriptQualityReport,
    TranscriptionOutcome,
    TranscriptionStrategy,
    VadProfile,
)
from video_processor import decode_audio_chunk, probe_duration
from silero_vad import VadOptions, get_speech_timestamps, to_clip_timestamps

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
NO_SPEECH_THRESHOLD = 0.75
LOGPROB_THRESHOLD = -0.6
COMPRESSION_RATIO_THRESHOLD = 2.4
SILENCE_RMS_THRESHOLD = 0.0003
SILENCE_PEAK_THRESHOLD = 0.003
REPEATED_TEXT_MIN_RUN = 4
KNOWN_HALLUCINATION_MIN_RUN = 3
REPEATED_TEXT_MAX_CHARS = 24
REPEATED_TEXT_MIN_STEP = 1.0
REPEATED_TEXT_MAX_STEP = 4.0
REPEATED_TEXT_MAX_STEP_SPREAD = 0.8
_REPEATED_TEXT_NORMALIZE_RE = re.compile(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()【】\[\]{}<>《》…~\-—_]+")
_KNOWN_HALLUCINATION_TEXTS = {
    "我可以做的",
    "我可以用水煮的",
    "我会继续来到",
}

# MLX 的 Metal command encoder 是「线程亲和」的：GPU stream 在首次访问它的线程上创建并
# 绑定 encoder，换一条线程再 eval 同一 stream 就抛 C++ 异常
# "There is no Stream(gpu, N) in current thread" —— 该异常逃出 C++ 边界直接 abort()
# 整个进程，Python 的 try/except 根本拦不住。asyncio.to_thread 用的是事件循环的共享线程池，
# 相邻两次调用可能落在不同 worker 线程上（_load_model 在 A、下一个 _transcribe_chunk 在 B），
# 于是必崩。所有 MLX 调用必须钉死在同一条线程：单 worker 执行器既保证线程亲和，又顺带把
# 并发任务的 GPU 访问串行化（避免两个转录抢同一 stream）。
_MLX_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="mlx-whisper"
)


def _ensure_mlx_whisper_import_shims() -> None:
    """mlx_whisper.transcribe 在 import 时就会加载 timing → scipy.signal。

    我们关闭了 word_timestamps，不需要完整 scipy；发行包也刻意排除它。
    这里只补一个 medfilt 桩，避免打包后 ModelHolder 都加载不了。
    """
    if "scipy.signal" in sys.modules:
        return
    import numpy as np

    scipy = sys.modules.get("scipy") or types.ModuleType("scipy")
    if not getattr(scipy, "__version__", None):
        scipy.__version__ = "1.0.0-stub"
    signal = sys.modules.get("scipy.signal") or types.ModuleType("scipy.signal")

    def medfilt(volume, kernel_size=None):
        array = np.asarray(volume)
        if kernel_size is None:
            return array
        if np.isscalar(kernel_size):
            sizes = (int(kernel_size),) * array.ndim
        else:
            sizes = tuple(int(item) for item in kernel_size)
        result = array.astype(np.float32, copy=False)
        for axis, size in enumerate(sizes):
            if size <= 1:
                continue
            pad = size // 2
            padded = np.pad(result, [(pad, pad) if i == axis else (0, 0) for i in range(result.ndim)], mode="edge")
            windows = np.lib.stride_tricks.sliding_window_view(padded, size, axis=axis)
            result = np.median(windows, axis=-1)
        return result.astype(array.dtype, copy=False)

    signal.medfilt = medfilt
    scipy.signal = signal
    sys.modules["scipy"] = scipy
    sys.modules["scipy.signal"] = signal


async def _run_on_mlx_thread(fn, *args):
    """在专用单线程执行器上执行 MLX 调用（线程亲和，原因见上方注释）。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_MLX_EXECUTOR, fn, *args)


def run_on_mlx_thread_sync(fn, *args):
    """同步地在专用 MLX 线程上执行（供非 async 的后台预热线程调用）。

    必须与 transcribe() 共用同一执行器：预热若在自建线程上加载模型（首次触碰 GPU
    即在该线程绑定 Metal command encoder），随后转录换到 _MLX_EXECUTOR 线程访问同一
    stream 就会抛 "There is no Stream(gpu, N) in current thread" → abort 整个进程。
    注意：勿在 _MLX_EXECUTOR 线程内部调用此函数（单 worker，会自等死锁）。
    """
    return _MLX_EXECUTOR.submit(fn, *args).result()

# 定长分块解码的块长（秒）。mlx-whisper 一次性执行（非惰性生成器），取消只能在
# 块边界生效；切成 10 分钟的块，兼顾「取消响应延迟」与「分块开销/上下文割裂」，
# 并把解码内存约束在单块大小（长音频友好）。每块内部再做 Silero VAD。
CHUNK_SECONDS = 600

_HOST_CHUNK_SECONDS = {
    StrategyProfile.DEFAULT: 600.0,
    StrategyProfile.CLEAN_SPEECH: 600.0,
    StrategyProfile.LONG_FORM: 300.0,
    StrategyProfile.SILENCE_HEAVY: 300.0,
    StrategyProfile.LOW_VOLUME_OR_NOISY: 300.0,
    StrategyProfile.SAFE_FALLBACK: 600.0,
}


def _vad_options(profile: VadProfile) -> Optional[VadOptions]:
    if profile is VadProfile.CURRENT_DEFAULT:
        return None
    if profile is VadProfile.STANDARD:
        return VadOptions()
    if profile is VadProfile.SILENCE_HEAVY:
        return VadOptions(
            threshold=0.55,
            min_silence_duration_ms=350,
            speech_pad_ms=500,
        )
    raise ValueError("unsupported VAD profile")


def _normalize_volume(audio_array):
    """低音量 profile 的有界峰值归一化，不改写源文件。"""
    if audio_array.size == 0:
        return audio_array
    rms = float((audio_array ** 2).mean() ** 0.5)
    peak = float(abs(audio_array).max())
    if rms <= 0 or peak <= 0:
        return audio_array
    gain = min(8.0, 0.06 / rms, 0.98 / peak)
    if gain <= 1.0:
        return audio_array
    return (audio_array * gain).clip(-1.0, 1.0)


def _deduplicate_overlap(segments: list[dict]) -> list[dict]:
    """只删除分块 overlap 里时间交叉且文字相同的副本。"""
    selected: list[dict] = []
    for segment in sorted(segments, key=lambda item: (item["start"], item["end"])):
        normalized = _normalize_repeated_text(segment.get("text") or "")
        duplicate = False
        for previous in reversed(selected[-6:]):
            if previous["end"] + 0.5 < segment["start"]:
                break
            if (
                normalized
                and normalized == _normalize_repeated_text(previous.get("text") or "")
                and segment["start"] < previous["end"] + 0.5
                and segment["end"] > previous["start"] - 0.5
            ):
                duplicate = True
                break
        if not duplicate:
            selected.append(segment)
    return selected


def parse_detected_language(transcript_text: Optional[str]) -> Optional[str]:
    """从转录 Markdown 的 ``**Detected Language:**`` 行解析语言代码。

    纯函数，不依赖任何共享状态，可安全地在并发任务中调用。
    解析不出有效语言代码时返回 None。
    """
    if not transcript_text or "**Detected Language:**" not in transcript_text:
        return None
    for line in transcript_text.split("\n"):
        if "**Detected Language:**" in line:
            raw = line.split(":", 1)[-1].strip()
            lang = re.sub(r"\*+", "", raw).strip()
            if lang and len(lang) >= 2 and not lang.startswith("-"):
                return lang
            return None
    return None


def _normalize_repeated_text(text: str) -> str:
    return _REPEATED_TEXT_NORMALIZE_RE.sub("", text or "").lower()


_KNOWN_HALLUCINATION_NORMALIZED = {
    _normalize_repeated_text(text) for text in _KNOWN_HALLUCINATION_TEXTS
}


def _is_effectively_silent(audio_array) -> bool:
    if audio_array.size == 0:
        return True
    rms = float((audio_array ** 2).mean() ** 0.5)
    peak = float(abs(audio_array).max())
    return rms < SILENCE_RMS_THRESHOLD and peak < SILENCE_PEAK_THRESHOLD


def _has_fixed_step(starts: list[float]) -> bool:
    deltas = [b - a for a, b in zip(starts, starts[1:])]
    if not deltas:
        return False
    if min(deltas) < REPEATED_TEXT_MIN_STEP or max(deltas) > REPEATED_TEXT_MAX_STEP:
        return False
    return max(deltas) - min(deltas) <= REPEATED_TEXT_MAX_STEP_SPREAD


def _is_fixed_step_repeat(run: list[dict]) -> bool:
    """识别静音/水声幻觉常见的固定间隔短句循环。"""
    if len(run) < REPEATED_TEXT_MIN_RUN:
        return False
    normalized = _normalize_repeated_text(run[0].get("text") or "")
    if not normalized or len(normalized) > REPEATED_TEXT_MAX_CHARS:
        return False
    starts = [float(seg.get("start") or 0.0) for seg in run]
    return _has_fixed_step(starts)


def _is_known_hallucination_run(run: list[dict]) -> bool:
    if len(run) < KNOWN_HALLUCINATION_MIN_RUN:
        return False
    normalized = [_normalize_repeated_text(seg.get("text") or "") for seg in run]
    if any(text not in _KNOWN_HALLUCINATION_NORMALIZED for text in normalized):
        return False
    starts = [float(seg.get("start") or 0.0) for seg in run]
    return _has_fixed_step(starts)


def filter_repeated_hallucinations(segments: list[dict]) -> list[dict]:
    """删除连续重复短句且时间步进稳定的幻觉片段。"""
    filtered: list[dict] = []
    dropped = 0
    i = 0
    while i < len(segments):
        current_norm = _normalize_repeated_text(segments[i].get("text") or "")
        run = [segments[i]]
        j = i + 1
        while j < len(segments):
            next_norm = _normalize_repeated_text(segments[j].get("text") or "")
            same_text = next_norm == current_norm
            both_known = (
                current_norm in _KNOWN_HALLUCINATION_NORMALIZED
                and next_norm in _KNOWN_HALLUCINATION_NORMALIZED
            )
            if not same_text and not both_known:
                break
            run.append(segments[j])
            j += 1
        if _is_fixed_step_repeat(run) or _is_known_hallucination_run(run):
            dropped += len(run)
        else:
            filtered.extend(run)
        i = j
    if dropped:
        logger.info("重复幻觉过滤删除 %d 个片段", dropped)
    return filtered


class Transcriber:
    """音频转录器，使用 mlx-whisper（Apple MLX）在 Apple Silicon 上跑 GPU + 统一内存。

    底层引擎从 faster-whisper(CTranslate2，仅 CPU) 换成 mlx-whisper：同样的
    large-v3-turbo 权重，但吃 Metal GPU，长音频提速约 8–10×。接口（async
    ``transcribe`` + ``get_detected_language``）保持不变，满足 ASRBackend Protocol，
    上层管线零改动。
    """

    def __init__(self, model_size: str = "base", model_path: Optional[str] = None):
        """
        初始化转录器

        Args:
            model_size: Whisper 模型大小 (base, small, medium, large-v3-turbo, large-v3)
            model_path: mlx_whisper 的 path_or_hf_repo——本地模型目录
                        （含 config.json + weights.*）或 mlx-community 的 HF 仓库名。
                        传仓库名时 mlx 会在首次转录时自动联网拉取（dev 兜底）。
                        None 时回退到 ``mlx-community/whisper-<size>``。
        """
        self.model_size = model_size
        self.model_path = model_path or f"mlx-community/whisper-{model_size}"
        self._load_lock = threading.Lock()

    def _load_model(self):
        """触发 mlx 模型加载进显存（预热用）。

        mlx_whisper 在 transcribe 内部通过 ModelHolder 懒加载并缓存单个模型；
        这里直接预热同一缓存，使首个真实任务无需等待权重加载。
        """
        import mlx.core as mx
        _ensure_mlx_whisper_import_shims()
        from mlx_whisper.transcribe import ModelHolder

        with self._load_lock:
            logger.info("正在加载 mlx-whisper 模型: %s (%s)", self.model_size, self.model_path)
            # dtype 与 transcribe 默认 (fp16=True) 一致，避免预热与实跑加载两份权重。
            ModelHolder.get_model(self.model_path, mx.float16)
            logger.info("mlx-whisper 模型加载完成（Metal GPU）")

    def _transcribe_chunk(
        self,
        audio_array,
        language: Optional[str],
        clip_timestamps=None,
        decode_profile: DecodeProfile = DecodeProfile.CURRENT_DEFAULT,
    ) -> dict:
        """转录单个内存波形块（同步，供 asyncio.to_thread 调用）。

        clip_timestamps 非空时（来自 Silero VAD），mlx 只转录这些区间并跳过静音，
        输出时间戳即该块内的原始时间轴。
        """
        _ensure_mlx_whisper_import_shims()
        import mlx_whisper

        # 参数只能从宿主闭集 profile 映射，不接受任意 kwargs。
        thresholds = {
            DecodeProfile.CURRENT_DEFAULT: (
                NO_SPEECH_THRESHOLD,
                COMPRESSION_RATIO_THRESHOLD,
                LOGPROB_THRESHOLD,
            ),
            DecodeProfile.CLEAN: (0.75, 2.4, -0.6),
            DecodeProfile.ROBUST: (0.65, 2.2, -0.8),
        }
        no_speech, compression, logprob = thresholds[decode_profile]
        return mlx_whisper.transcribe(
            audio_array,
            path_or_hf_repo=self.model_path,
            language=language,
            # 抗幻觉阈值（移植自 openai-whisper，与原 faster-whisper 配置对齐）：
            no_speech_threshold=no_speech,
            compression_ratio_threshold=compression,
            logprob_threshold=logprob,
            # 避免错误累积导致的连环重复（长音频尤其重要）。
            condition_on_previous_text=False,
            word_timestamps=False,
            verbose=None,
            # "0" 是 mlx 默认值（整段）；传 VAD 区间则只转语音。
            clip_timestamps=clip_timestamps if clip_timestamps else "0",
        )

    async def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
        strategy: Optional[TranscriptionStrategy] = None,
        _segments_callback: Optional[Callable[[Optional[str], list[dict]], None]] = None,
        _speech_ranges_callback: Optional[Callable[[list[tuple[float, float]]], None]] = None,
    ) -> str:
        """
        转录音频文件（定长分块 + 块间取消 + 原时间轴回映）。

        Args:
            audio_path: 音频文件路径
            language: 指定语言（可选，不指定则自动检测，取首块结果）

        Returns:
            转录文本（Markdown 格式，与原 faster-whisper 输出结构一致）
        """
        try:
            if not os.path.exists(audio_path):
                raise TranscriptionError(f"音频文件不存在: {audio_path}")

            strategy = strategy or TranscriptionStrategy.current_default(self.model_size)
            self._validate_strategy(strategy)
            effective_language = (
                strategy.language if strategy.language_mode is LanguageMode.EXPLICIT else language
            )
            chunk_seconds = _HOST_CHUNK_SECONDS[strategy.profile]

            # 预热/加载模型：钉在专用 MLX 线程上（与后续转录同线程），避免首次加载阻塞事件循环。
            await _run_on_mlx_thread(self._load_model)

            logger.info("开始转录音频: %s", audio_path)
            cancel_token = cancellation.current()

            total_seconds = await asyncio.to_thread(probe_duration, audio_path)
            # 时长未知（探测失败）时退化为整段单块，至少保证能转录。
            if total_seconds and total_seconds > 0:
                step_seconds = chunk_seconds - strategy.overlap_seconds
                offsets = [i * step_seconds for i in range(int(total_seconds // step_seconds) + 1)]
                # 末块若恰好整除会得到一个零长块，剔除。
                offsets = [o for o in offsets if o < total_seconds] or [0.0]
            else:
                offsets = [0.0]

            detected_language: Optional[str] = None
            segments: list[dict] = []
            speech_ranges: list[tuple[float, float]] = []

            def _check_cancel():
                if cancel_token is not None and cancel_token.is_cancelled():
                    raise CancelledByUser()

            def _collect(result, chunk_offset):
                """收集 mlx 段落：时间戳已是块内原始时间轴，叠加该块偏移即可。"""
                nonlocal detected_language
                if detected_language is None:
                    detected_language = result.get("language")
                    logger.info("检测到的语言: %s", detected_language)
                for seg in result.get("segments", []):
                    text = (seg.get("text") or "").strip()
                    if not text:
                        continue
                    segments.append({
                        "start": (seg.get("start") or 0.0) + chunk_offset,
                        "end": (seg.get("end") or 0.0) + chunk_offset,
                        "text": text,
                    })

            for idx, start in enumerate(offsets):
                # 块边界检查取消：置位时停止启动后续块，避免取消 asyncio 任务后
                # 串行队列继续启下一项、两个转录并行抢 GPU（Codex 修正）。
                _check_cancel()

                dur = chunk_seconds if (total_seconds and start + chunk_seconds < total_seconds) else None
                # 整段回退（offsets==[0.0] 且时长未知）：dur=None 解码到末尾。
                if not total_seconds:
                    dur = None

                audio_array = await asyncio.to_thread(decode_audio_chunk, audio_path, start, dur)
                if strategy.normalize_volume:
                    audio_array = _normalize_volume(audio_array)

                # ── Silero 前置 VAD：切出语音段，转成 clip_timestamps 喂给 mlx ──
                # mlx 据此只转语音、跳过静音（抑制幻觉/重复 + 提速），输出即原始时间轴。
                # VAD 是质量增强而非硬依赖：失败时回退到整块直转，保证仍能出结果。
                skip_mlx = audio_array.size == 0
                clip = None
                if not skip_mlx:
                    if _is_effectively_silent(audio_array):
                        logger.info("块 %d（offset=%.0fs）低能量静音，跳过", idx, start)
                        skip_mlx = True
                    else:
                        try:
                            speech = await asyncio.to_thread(
                                get_speech_timestamps,
                                audio_array,
                                _vad_options(strategy.vad_profile),
                            )
                            if not speech:
                                logger.info("块 %d（offset=%.0fs）无语音，跳过", idx, start)
                                skip_mlx = True
                            else:
                                clip = to_clip_timestamps(speech, SAMPLE_RATE)
                                speech_ranges.extend(
                                    (
                                        start + item["start"] / SAMPLE_RATE,
                                        start + item["end"] / SAMPLE_RATE,
                                    )
                                    for item in speech
                                )
                                speech_seconds = sum((s["end"] - s["start"]) / SAMPLE_RATE for s in speech)
                                decoded_seconds = len(audio_array) / SAMPLE_RATE
                                speech_ratio = speech_seconds / decoded_seconds if decoded_seconds else 0.0
                                logger.info(
                                    "块 %d（offset=%.0fs）VAD 命中 %d 段语音，共 %.1fs，占比 %.1f%%",
                                    idx,
                                    start,
                                    len(speech),
                                    speech_seconds,
                                    speech_ratio * 100,
                                )
                        except CancelledByUser:
                            raise
                        except Exception as e:  # onnxruntime/模型缺失等
                            logger.warning("VAD 失败，回退整块转录: %s", e)
                            clip = None

                # MLX 转录必须与 _load_model 落在同一条线程上（见 _MLX_EXECUTOR 注释）。
                if not skip_mlx:
                    result = await _run_on_mlx_thread(
                        self._transcribe_chunk,
                        audio_array,
                        effective_language,
                        clip,
                        strategy.decode_profile,
                    )
                    _collect(result, start)

                # 分块进度上报：每块处理完后报告（含静音跳过/解码失败块，确保进度持续推进）。
                if progress_callback and total_seconds and total_seconds > 0:
                    is_last = idx == len(offsets) - 1
                    covered = total_seconds if is_last else min(start + (dur or chunk_seconds), total_seconds)
                    pct = min(99, max(0, round(covered / total_seconds * 100)))
                    await progress_callback(float(pct))

            segments = _deduplicate_overlap(segments)
            if _segments_callback is not None:
                _segments_callback(detected_language, [dict(item) for item in segments])
            if _speech_ranges_callback is not None:
                _speech_ranges_callback(list(speech_ranges))
            segments = filter_repeated_hallucinations(segments)
            logger.info("转录完成，共 %d 段", len(segments))
            return self._assemble_markdown(detected_language, segments)

        except CancelledByUser:
            logger.info("转录被用户取消")
            raise
        except TranscriptionError:
            raise
        except Exception as e:
            logger.error("转录失败: %s", str(e))
            raise TranscriptionError(f"转录失败: {str(e)}")

    def _validate_strategy(self, strategy: TranscriptionStrategy) -> None:
        if not isinstance(strategy, TranscriptionStrategy):
            raise ValueError("strategy must be a validated TranscriptionStrategy")
        if strategy.model_id != self.model_size:
            raise ValueError("strategy model_id does not match the installed transcriber")
        if strategy.chunk_seconds != _HOST_CHUNK_SECONDS[strategy.profile]:
            raise ValueError("strategy chunk size is not host-approved for this profile")

    async def transcribe_with_quality(
        self,
        audio_path: str,
        *,
        audio_profile: AudioProfile,
        strategy: TranscriptionStrategy,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> TranscriptionOutcome:
        """用已验证策略转录、复核，并最多对一个可疑区间重试一次。"""
        self._validate_strategy(strategy)
        raw_segments: list[dict] = []
        speech_ranges: list[tuple[float, float]] = []

        def _capture_segments(_language, segments):
            raw_segments.extend(segments)

        def _capture_speech_ranges(ranges):
            speech_ranges.extend(ranges)

        transcript = await self.transcribe(
            audio_path,
            progress_callback=progress_callback,
            strategy=strategy,
            _segments_callback=_capture_segments,
            _speech_ranges_callback=_capture_speech_ranges,
        )
        from transcript_quality import (
            evaluate_transcript,
            parse_markdown_segments,
            select_retry_candidate,
        )

        segments = parse_markdown_segments(transcript)
        try:
            report = evaluate_transcript(
                raw_segments or segments,
                audio_profile,
                speech_ranges=speech_ranges or None,
            )
        except ValueError as exc:
            # 质量复核不能推翻已经得到的转录，例如 VAD 末窗比 ffprobe 时长多几毫秒。
            logger.warning("转录质量复核失败，保留原转录: %s", exc)
            report = evaluate_transcript(raw_segments or segments, audio_profile)
        if not report.suspicious_ranges or strategy.max_segment_retries == 0:
            return TranscriptionOutcome(transcript, strategy, report)

        suspicious = report.suspicious_ranges[0]
        retry_waveform = await asyncio.to_thread(
            decode_audio_chunk,
            audio_path,
            suspicious.start_seconds,
            suspicious.end_seconds - suspicious.start_seconds,
        )
        token = cancellation.current()
        if token is not None:
            token.check()
        retry_result = await _run_on_mlx_thread(
            self._transcribe_chunk,
            retry_waveform,
            strategy.language if strategy.language_mode is LanguageMode.EXPLICIT else None,
            None,
            DecodeProfile.ROBUST,
        )
        retry_segments = []
        for segment in retry_result.get("segments", []):
            text = (segment.get("text") or "").strip()
            if text:
                retry_segments.append({
                    "start": float(segment.get("start") or 0) + suspicious.start_seconds,
                    "end": float(segment.get("end") or 0) + suspicious.start_seconds,
                    "text": text,
                })
        selection = select_retry_candidate(
            raw_segments or segments,
            retry_segments,
            audio_profile,
            suspicious,
            speech_ranges=speech_ranges or None,
        )
        selected_segments = selection.selected_segments
        selected_transcript = self._assemble_markdown(
            parse_detected_language(transcript),
            [
                {"start": item.start_seconds, "end": item.end_seconds, "text": item.text}
                for item in selected_segments
            ],
        )
        final_report = TranscriptQualityReport(
            evaluation_status=selection.report.evaluation_status,
            audio_duration_seconds=selection.report.audio_duration_seconds,
            speech_duration_seconds=selection.report.speech_duration_seconds,
            segment_count=selection.report.segment_count,
            coverage_ratio=selection.report.coverage_ratio,
            findings=selection.report.findings,
            suspicious_ranges=selection.report.suspicious_ranges,
            unavailable_metrics=selection.report.unavailable_metrics,
            retry_records=(selection.record,),
            final_selection=selection.record.selected,
        )
        return TranscriptionOutcome(selected_transcript, strategy, final_report)

    def _assemble_markdown(self, detected_language: Optional[str], segments: list[dict]) -> str:
        """组装与原 faster-whisper 输出一致的 Markdown，确保下游解析不变。

        mlx 不返回语言概率，故 ``**Language Probability:**`` 写占位 ``—``，不伪造数值。
        """
        lines = [
            "# Video Transcription",
            "",
            f"**Detected Language:** {detected_language or 'unknown'}",
            "**Language Probability:** —",
            "",
            "## Transcription Content",
            "",
        ]
        for seg in segments:
            start_time = self._format_time(seg["start"])
            end_time = self._format_time(seg["end"])
            lines.append(f"**[{start_time} - {end_time}]**")
            lines.append("")
            lines.append(seg["text"])
            lines.append("")
        return "\n".join(lines)

    def _format_time(self, seconds: float) -> str:
        """
        将秒数转换为时分秒格式

        Args:
            seconds: 秒数

        Returns:
            格式化的时间字符串
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    def get_supported_languages(self) -> list:
        """
        获取支持的语言列表
        """
        return [
            "zh", "en", "ja", "ko", "es", "fr", "de", "it", "pt", "ru",
            "ar", "hi", "th", "vi", "tr", "pl", "nl", "sv", "da", "no"
        ]

    def get_detected_language(self, transcript_text: Optional[str] = None) -> Optional[str]:
        """从转录文本中解析检测到的语言（无共享状态，委托给纯函数）。"""
        return parse_detected_language(transcript_text)
