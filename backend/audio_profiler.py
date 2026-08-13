"""轻量、确定性的音频体检。

FFprobe 负责源媒体事实，PCM 与 Silero VAD 负责音量、削波及语音/静音指标。
全时间轴按 30 秒分块扫描，既保证指标完整，也把峰值内存限制在单块大小。
分析能力是增强项：除明显的调用契约错误外，失败统一收敛为 ``AudioProfile``。
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np

import cancellation
from cancellation import CancelledByUser
from media_contracts import (
    AudioAnalysisStatus,
    AudioIntegrityFlag,
    AudioProfile,
    AudioQualityGrade,
    HeuristicLevel,
    sanitize_diagnostic,
)
from silero_vad import get_speech_timestamps
from video_processor import (
    FFPROBE_BIN,
    TRANSCRIBE_SAMPLE_RATE,
    _run_media_proc,
    decode_audio_chunk,
)


# 30 秒足以让 VAD 稳定工作，同时把长媒体的峰值内存限制在单块大小。
ANALYSIS_CHUNK_SECONDS = 30.0
PROBE_TIMEOUT_SECONDS = 60.0

LOW_VOLUME_RMS = 0.015
VERY_LOW_VOLUME_RMS = 0.003
SILENCE_PEAK = 0.001
CLIPPING_AMPLITUDE = 0.99
NOTICEABLE_CLIPPING_RATIO = 0.001
SEVERE_CLIPPING_RATIO = 0.05
ABNORMALLY_SHORT_SECONDS = 1.0

VadDetector = Callable[[np.ndarray], Iterable[dict]]


def _check_cancel() -> None:
    token = cancellation.current()
    if token is not None:
        token.check()


@dataclass(frozen=True)
class _MediaFacts:
    container: Optional[str]
    codec: Optional[str]
    duration_seconds: Optional[float]
    sample_rate_hz: Optional[int]
    channels: Optional[int]
    bitrate_bps: Optional[int]
    has_audio: bool


@dataclass
class _PcmTotals:
    sample_count: int = 0
    square_sum: float = 0.0
    peak: float = 0.0
    clipping_count: int = 0
    analyzed_seconds: float = 0.0
    speech_seconds: float = 0.0
    longest_silence_samples: int = 0
    trailing_silence_samples: int = 0
    speech_square_sum: float = 0.0
    speech_sample_count: int = 0
    nonspeech_square_sum: float = 0.0
    nonspeech_sample_count: int = 0


def _positive_float(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _positive_int(value: object) -> Optional[int]:
    number = _positive_float(value)
    return int(number) if number is not None else None


def _probe_audio(audio_path: str) -> _MediaFacts:
    """只读取首条音轨；输出字段与 ``AudioProfile`` 一一对应。"""
    output = _run_media_proc(
        [
            FFPROBE_BIN,
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries",
            "format=format_name,duration,bit_rate:stream=codec_name,duration,sample_rate,channels,bit_rate",
            "-of", "json",
            audio_path,
        ],
        timeout=PROBE_TIMEOUT_SECONDS,
        label="ffprobe 音频体检",
    )
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise ValueError("ffprobe did not return an object")

    streams = payload.get("streams")
    stream = streams[0] if isinstance(streams, list) and streams else None
    media_format = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    if not isinstance(stream, dict):
        return _MediaFacts(
            container=str(media_format.get("format_name") or "").strip() or None,
            codec=None,
            duration_seconds=_positive_float(media_format.get("duration")),
            sample_rate_hz=None,
            channels=None,
            bitrate_bps=_positive_int(media_format.get("bit_rate")),
            has_audio=False,
        )

    return _MediaFacts(
        container=str(media_format.get("format_name") or "").strip() or None,
        codec=str(stream.get("codec_name") or "").strip() or None,
        duration_seconds=(
            _positive_float(stream.get("duration"))
            or _positive_float(media_format.get("duration"))
        ),
        sample_rate_hz=_positive_int(stream.get("sample_rate")),
        channels=_positive_int(stream.get("channels")),
        bitrate_bps=(
            _positive_int(stream.get("bit_rate"))
            or _positive_int(media_format.get("bit_rate"))
        ),
        has_audio=True,
    )


def _analysis_windows(duration_seconds: Optional[float]) -> Iterable[tuple[float, float]]:
    """逐个产生连续窗口；完整扫过时间轴，但始终只保留一块 PCM。"""
    if duration_seconds is None:
        yield 0.0, ANALYSIS_CHUNK_SECONDS
        return

    start = 0.0
    while start < duration_seconds:
        remaining = duration_seconds - start
        yield start, min(ANALYSIS_CHUNK_SECONDS, remaining)
        start += ANALYSIS_CHUNK_SECONDS


def _normalize_speech_segments(
    raw_segments: Iterable[dict], sample_count: int
) -> tuple[tuple[int, int], ...]:
    intervals = []
    for segment in raw_segments:
        if not isinstance(segment, dict):
            raise ValueError("VAD segment must be an object")
        try:
            start = max(0, min(sample_count, int(segment["start"])))
            end = max(0, min(sample_count, int(segment["end"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("VAD segment requires integer start/end") from exc
        if end > start:
            intervals.append((start, end))

    intervals.sort()
    merged: list[list[int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def _accumulate_window(
    totals: _PcmTotals,
    waveform: np.ndarray,
    speech_segments: tuple[tuple[int, int], ...],
) -> None:
    samples = np.asarray(waveform, dtype=np.float32).reshape(-1)
    if not samples.size:
        return
    if not np.isfinite(samples).all():
        samples = np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)

    absolute = np.abs(samples)
    totals.sample_count += int(samples.size)
    totals.square_sum += float(np.dot(samples.astype(np.float64), samples.astype(np.float64)))
    totals.peak = max(totals.peak, float(np.max(absolute)))
    totals.clipping_count += int(np.count_nonzero(absolute >= CLIPPING_AMPLITUDE))
    totals.analyzed_seconds += samples.size / TRANSCRIBE_SAMPLE_RATE

    cursor = 0
    longest_gap = 0
    for start, end in speech_segments:
        gap = start - cursor
        if cursor == 0:
            gap += totals.trailing_silence_samples
        longest_gap = max(longest_gap, gap)
        speech = samples[start:end].astype(np.float64)
        totals.speech_square_sum += float(np.dot(speech, speech))
        totals.speech_sample_count += end - start
        if start > cursor:
            nonspeech = samples[cursor:start].astype(np.float64)
            totals.nonspeech_square_sum += float(np.dot(nonspeech, nonspeech))
            totals.nonspeech_sample_count += start - cursor
        cursor = end

    trailing_gap = samples.size - cursor
    if not speech_segments:
        trailing_gap += totals.trailing_silence_samples
    longest_gap = max(longest_gap, trailing_gap)
    if cursor < samples.size:
        nonspeech = samples[cursor:].astype(np.float64)
        totals.nonspeech_square_sum += float(np.dot(nonspeech, nonspeech))
        totals.nonspeech_sample_count += samples.size - cursor

    totals.speech_seconds += sum(end - start for start, end in speech_segments) / TRANSCRIBE_SAMPLE_RATE
    totals.longest_silence_samples = max(totals.longest_silence_samples, longest_gap)
    totals.trailing_silence_samples = trailing_gap


def _noise_heuristic(totals: _PcmTotals) -> tuple[Optional[HeuristicLevel], Optional[float]]:
    """仅用非语音/语音能量比给出保守噪声提示，不冒充声源分类。"""
    minimum = TRANSCRIBE_SAMPLE_RATE
    if totals.speech_sample_count < minimum or totals.nonspeech_sample_count < minimum:
        return None, None
    speech_rms = math.sqrt(totals.speech_square_sum / totals.speech_sample_count)
    nonspeech_rms = math.sqrt(totals.nonspeech_square_sum / totals.nonspeech_sample_count)
    if speech_rms <= SILENCE_PEAK:
        return None, None
    ratio = nonspeech_rms / speech_rms
    if ratio < 0.15:
        level = HeuristicLevel.LOW
    elif ratio < 0.45:
        level = HeuristicLevel.MEDIUM
    else:
        level = HeuristicLevel.HIGH
    # 单纯能量比无法可靠区分环境噪声、音乐和非语音事件，置信度刻意封顶。
    evidence_seconds = min(totals.speech_sample_count, totals.nonspeech_sample_count) / TRANSCRIBE_SAMPLE_RATE
    confidence = min(0.65, 0.35 + min(evidence_seconds / 60.0, 1.0) * 0.30)
    return level, confidence


def _quality(
    *,
    rms: float,
    clipping_ratio: float,
    silence_ratio: float,
    longest_silence: float,
    duration: float,
    flags: tuple[AudioIntegrityFlag, ...],
) -> tuple[AudioQualityGrade, tuple[str, ...], bool]:
    low_volume = rms < LOW_VOLUME_RMS
    reasons: list[str] = []

    if AudioIntegrityFlag.ALL_SILENCE in flags:
        return AudioQualityGrade.UNUSABLE, ("all_silence",), low_volume
    if AudioIntegrityFlag.ABNORMALLY_SHORT in flags:
        reasons.append("abnormally_short")
    if low_volume:
        reasons.append("low_volume")
    if clipping_ratio >= NOTICEABLE_CLIPPING_RATIO:
        reasons.append("clipping_detected")
    if silence_ratio >= 0.70:
        reasons.append("silence_heavy")
    if longest_silence >= max(10.0, duration * 0.20):
        reasons.append("long_silence")
    if clipping_ratio >= SEVERE_CLIPPING_RATIO or (low_volume and rms < VERY_LOW_VOLUME_RMS):
        grade = AudioQualityGrade.POOR
    elif reasons:
        grade = AudioQualityGrade.FAIR
    else:
        grade = AudioQualityGrade.GOOD
        reasons.insert(0, "metrics_within_range")
    return grade, tuple(dict.fromkeys(reasons)), low_volume


def _failed_profile(
    error: object,
    *,
    flag: AudioIntegrityFlag = AudioIntegrityFlag.CORRUPT,
    reason: str = "analysis_failed",
) -> AudioProfile:
    return AudioProfile(
        analysis_status=AudioAnalysisStatus.FAILED,
        integrity_flags=(flag,),
        quality_grade=AudioQualityGrade.UNUSABLE,
        reason_codes=(reason,),
        analysis_error=sanitize_diagnostic(error),
    )


def analyze_audio(
    audio_path: os.PathLike[str] | str,
    *,
    vad_detector: Optional[VadDetector] = None,
) -> AudioProfile:
    """分析一个本地媒体文件并返回可消费的 ``AudioProfile``。

    ``vad_detector`` 是测试/受控替换缝隙，默认使用项目现有 Silero VAD。路径类型、
    空路径和不存在的文件属于调用契约错误；媒体解析、解码或 VAD 故障不会向外抛。
    """
    try:
        path = os.fspath(audio_path)
    except TypeError as exc:
        raise TypeError("audio_path must be a path-like value") from exc
    if not isinstance(path, str) or not path.strip():
        raise ValueError("audio_path must be a non-empty path")
    if not Path(path).is_file():
        raise FileNotFoundError(path)

    try:
        _check_cancel()
        facts = _probe_audio(path)
    except CancelledByUser:
        raise
    except Exception as exc:
        return _failed_profile(exc)

    if not facts.has_audio:
        return AudioProfile(
            analysis_status=AudioAnalysisStatus.FAILED,
            container=facts.container,
            duration_seconds=facts.duration_seconds,
            bitrate_bps=facts.bitrate_bps,
            integrity_flags=(AudioIntegrityFlag.NO_AUDIO_TRACK,),
            quality_grade=AudioQualityGrade.UNUSABLE,
            reason_codes=("no_audio_track",),
            analysis_error="ffprobe found no audio track",
        )

    detector = vad_detector or get_speech_timestamps
    totals = _PcmTotals()
    vad_error: Optional[Exception] = None
    decode_errors: list[str] = []
    for start, requested_duration in _analysis_windows(facts.duration_seconds):
        _check_cancel()
        try:
            waveform = decode_audio_chunk(path, start, requested_duration)
        except CancelledByUser:
            raise
        except Exception as exc:
            decode_errors.append(sanitize_diagnostic(exc, max_length=200))
            continue
        _check_cancel()
        try:
            samples = np.asarray(waveform, dtype=np.float32).reshape(-1)
        except Exception as exc:
            decode_errors.append("invalid decoded PCM: " + sanitize_diagnostic(exc, max_length=160))
            continue
        if not samples.size:
            decode_errors.append(f"empty decoded window at {start:.1f}s")
            continue
        try:
            speech = _normalize_speech_segments(detector(samples), samples.size)
        except CancelledByUser:
            raise
        except Exception as exc:
            vad_error = exc
            # PCM 指标仍可信；语音相关指标则整体保持未知，避免混合部分窗口造假。
            speech = ()
        _check_cancel()
        try:
            _accumulate_window(totals, samples, speech)
        except CancelledByUser:
            raise
        except Exception as exc:
            decode_errors.append("PCM statistics: " + sanitize_diagnostic(exc, max_length=160))
        _check_cancel()

    if totals.sample_count == 0:
        return AudioProfile(
            analysis_status=AudioAnalysisStatus.FAILED,
            container=facts.container,
            codec=facts.codec,
            duration_seconds=facts.duration_seconds,
            sample_rate_hz=facts.sample_rate_hz,
            channels=facts.channels,
            bitrate_bps=facts.bitrate_bps,
            integrity_flags=(AudioIntegrityFlag.CORRUPT,),
            quality_grade=AudioQualityGrade.UNUSABLE,
            reason_codes=("decode_failed",),
            analysis_error="; ".join(decode_errors) or "audio decode produced no samples",
        )

    rms = math.sqrt(totals.square_sum / totals.sample_count)
    clipping_ratio = totals.clipping_count / totals.sample_count
    all_silence = totals.peak <= SILENCE_PEAK
    flags: list[AudioIntegrityFlag] = []
    if facts.duration_seconds is not None and facts.duration_seconds < ABNORMALLY_SHORT_SECONDS:
        flags.append(AudioIntegrityFlag.ABNORMALLY_SHORT)
    if all_silence:
        flags.append(AudioIntegrityFlag.ALL_SILENCE)

    coverage_tolerance = max(0.25, (facts.duration_seconds or 0.0) * 0.001)
    timeline_complete = bool(
        facts.duration_seconds is not None
        and totals.analyzed_seconds + coverage_tolerance >= facts.duration_seconds
    )
    speech_metrics_known = vad_error is None and not decode_errors and timeline_complete
    if speech_metrics_known:
        duration = facts.duration_seconds or totals.analyzed_seconds
        speech_duration = min(duration, totals.speech_seconds)
        speech_ratio = min(1.0, speech_duration / duration)
        silence_ratio = max(0.0, 1.0 - speech_ratio)
        longest_silence = min(
            duration,
            totals.longest_silence_samples / TRANSCRIBE_SAMPLE_RATE,
        )
    else:
        speech_ratio = silence_ratio = speech_duration = longest_silence = None

    deterministic_complete = all(
        value is not None
        for value in (
            facts.container,
            facts.codec,
            facts.duration_seconds,
            facts.sample_rate_hz,
            facts.channels,
            facts.bitrate_bps,
        )
    ) and speech_metrics_known

    analysis_errors = list(decode_errors)
    if vad_error is not None:
        analysis_errors.append("VAD: " + sanitize_diagnostic(vad_error, max_length=200))
    if not timeline_complete and not decode_errors:
        analysis_errors.append("decoded PCM did not cover the complete media timeline")
    if not deterministic_complete and not analysis_errors:
        analysis_errors.append("ffprobe omitted required metadata")

    if speech_metrics_known:
        grade, reasons, low_volume = _quality(
            rms=rms,
            clipping_ratio=clipping_ratio,
            silence_ratio=silence_ratio or 0.0,
            longest_silence=longest_silence or 0.0,
            duration=facts.duration_seconds or totals.analyzed_seconds,
            flags=tuple(flags),
        )
        noise_level, noise_confidence = _noise_heuristic(totals)
    else:
        grade = AudioQualityGrade.UNKNOWN
        reasons = ()
        low_volume = rms < LOW_VOLUME_RMS
        noise_level = noise_confidence = None

    return AudioProfile(
        analysis_status=(
            AudioAnalysisStatus.COMPLETE if deterministic_complete else AudioAnalysisStatus.PARTIAL
        ),
        container=facts.container,
        codec=facts.codec,
        duration_seconds=facts.duration_seconds,
        sample_rate_hz=facts.sample_rate_hz,
        channels=facts.channels,
        bitrate_bps=facts.bitrate_bps,
        rms_amplitude=min(1.0, rms),
        peak_amplitude=min(1.0, totals.peak),
        clipping_ratio=min(1.0, clipping_ratio),
        low_volume=low_volume,
        speech_duration_seconds=speech_duration,
        speech_ratio=speech_ratio,
        silence_ratio=silence_ratio,
        longest_silence_seconds=longest_silence,
        integrity_flags=tuple(flags),
        noise_level=noise_level,
        noise_confidence=noise_confidence,
        # 仅凭单声道能量和 VAD 不能可靠辨认音乐，因此诚实地保持未知。
        music_level=None,
        music_confidence=None,
        quality_grade=grade,
        reason_codes=reasons,
        analysis_error="; ".join(analysis_errors) or None,
    )


__all__ = ["analyze_audio"]
