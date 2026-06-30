import os
import re
import asyncio
import threading
import logging
import concurrent.futures
from typing import Optional, Callable, Awaitable

import cancellation
from cancellation import CancelledByUser
from exceptions import TranscriptionError
from video_processor import decode_audio_chunk, probe_duration
from silero_vad import get_speech_timestamps, to_clip_timestamps

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
NO_SPEECH_THRESHOLD = 0.75
LOGPROB_THRESHOLD = -0.6
COMPRESSION_RATIO_THRESHOLD = 2.4
REPEATED_TEXT_MIN_RUN = 4
REPEATED_TEXT_MAX_CHARS = 24
REPEATED_TEXT_MIN_STEP = 1.0
REPEATED_TEXT_MAX_STEP = 4.0
REPEATED_TEXT_MAX_STEP_SPREAD = 0.8
_REPEATED_TEXT_NORMALIZE_RE = re.compile(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()【】\[\]{}<>《》…~\-—_]+")

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


def _is_fixed_step_repeat(run: list[dict]) -> bool:
    """识别静音/水声幻觉常见的固定间隔短句循环。"""
    if len(run) < REPEATED_TEXT_MIN_RUN:
        return False
    normalized = _normalize_repeated_text(run[0].get("text") or "")
    if not normalized or len(normalized) > REPEATED_TEXT_MAX_CHARS:
        return False
    starts = [float(seg.get("start") or 0.0) for seg in run]
    deltas = [b - a for a, b in zip(starts, starts[1:])]
    if not deltas:
        return False
    if min(deltas) < REPEATED_TEXT_MIN_STEP or max(deltas) > REPEATED_TEXT_MAX_STEP:
        return False
    return max(deltas) - min(deltas) <= REPEATED_TEXT_MAX_STEP_SPREAD


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
            if next_norm != current_norm:
                break
            run.append(segments[j])
            j += 1
        if _is_fixed_step_repeat(run):
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
        from mlx_whisper.transcribe import ModelHolder

        with self._load_lock:
            logger.info("正在加载 mlx-whisper 模型: %s (%s)", self.model_size, self.model_path)
            # dtype 与 transcribe 默认 (fp16=True) 一致，避免预热与实跑加载两份权重。
            ModelHolder.get_model(self.model_path, mx.float16)
            logger.info("mlx-whisper 模型加载完成（Metal GPU）")

    def _transcribe_chunk(self, audio_array, language: Optional[str], clip_timestamps=None) -> dict:
        """转录单个内存波形块（同步，供 asyncio.to_thread 调用）。

        clip_timestamps 非空时（来自 Silero VAD），mlx 只转录这些区间并跳过静音，
        输出时间戳即该块内的原始时间轴。
        """
        import mlx_whisper

        return mlx_whisper.transcribe(
            audio_array,
            path_or_hf_repo=self.model_path,
            language=language,
            # 抗幻觉阈值（移植自 openai-whisper，与原 faster-whisper 配置对齐）：
            no_speech_threshold=NO_SPEECH_THRESHOLD,
            compression_ratio_threshold=COMPRESSION_RATIO_THRESHOLD,
            logprob_threshold=LOGPROB_THRESHOLD,
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

            # 预热/加载模型：钉在专用 MLX 线程上（与后续转录同线程），避免首次加载阻塞事件循环。
            await _run_on_mlx_thread(self._load_model)

            logger.info("开始转录音频: %s", audio_path)
            cancel_token = cancellation.current()

            total_seconds = await asyncio.to_thread(probe_duration, audio_path)
            # 时长未知（探测失败）时退化为整段单块，至少保证能转录。
            if total_seconds and total_seconds > 0:
                offsets = [i * CHUNK_SECONDS for i in range(int(total_seconds // CHUNK_SECONDS) + 1)]
                # 末块若恰好整除会得到一个零长块，剔除。
                offsets = [o for o in offsets if o < total_seconds] or [0.0]
            else:
                offsets = [0.0]

            detected_language: Optional[str] = None
            segments: list[dict] = []

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

                dur = CHUNK_SECONDS if (total_seconds and start + CHUNK_SECONDS < total_seconds) else None
                # 整段回退（offsets==[0.0] 且时长未知）：dur=None 解码到末尾。
                if not total_seconds:
                    dur = None

                audio_array = await asyncio.to_thread(decode_audio_chunk, audio_path, start, dur)

                # ── Silero 前置 VAD：切出语音段，转成 clip_timestamps 喂给 mlx ──
                # mlx 据此只转语音、跳过静音（抑制幻觉/重复 + 提速），输出即原始时间轴。
                # VAD 是质量增强而非硬依赖：失败时回退到整块直转，保证仍能出结果。
                skip_mlx = audio_array.size == 0
                clip = None
                if not skip_mlx:
                    try:
                        speech = await asyncio.to_thread(get_speech_timestamps, audio_array)
                        if not speech:
                            logger.info("块 %d（offset=%.0fs）无语音，跳过", idx, start)
                            skip_mlx = True
                        else:
                            clip = to_clip_timestamps(speech, SAMPLE_RATE)
                            speech_seconds = sum((s["end"] - s["start"]) / SAMPLE_RATE for s in speech)
                            logger.info(
                                "块 %d（offset=%.0fs）VAD 命中 %d 段语音，共 %.1fs",
                                idx,
                                start,
                                len(speech),
                                speech_seconds,
                            )
                    except Exception as e:  # onnxruntime/模型缺失等
                        logger.warning("VAD 失败，回退整块转录: %s", e)
                        clip = None

                # MLX 转录必须与 _load_model 落在同一条线程上（见 _MLX_EXECUTOR 注释）。
                if not skip_mlx:
                    result = await _run_on_mlx_thread(self._transcribe_chunk, audio_array, language, clip)
                    _collect(result, start)

                # 分块进度上报：每块处理完后报告（含静音跳过/解码失败块，确保进度持续推进）。
                if progress_callback and total_seconds and total_seconds > 0:
                    is_last = idx == len(offsets) - 1
                    covered = total_seconds if is_last else min(start + (dur or CHUNK_SECONDS), total_seconds)
                    pct = min(99, max(0, round(covered / total_seconds * 100)))
                    await progress_callback(float(pct))

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
