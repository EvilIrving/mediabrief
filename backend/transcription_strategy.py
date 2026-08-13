"""从确定性 AudioProfile 选择宿主白名单内的 Whisper 策略。

这里没有参数搜索：每个 profile 都映射到一组固定、可校验的配置；
分析不完整或音频完整性异常时精确退回现有 10 分钟分块路径。
"""
from __future__ import annotations

from typing import Optional

from media_contracts import (
    AudioAnalysisStatus,
    AudioProfile,
    AudioQualityGrade,
    ChunkBoundaryProfile,
    DecodeProfile,
    HeuristicLevel,
    LanguageMode,
    StrategyProfile,
    TranscriptionStrategy,
    VadProfile,
)


LONG_FORM_MIN_SECONDS = 60.0 * 60.0
SILENCE_HEAVY_RATIO = 0.65
LONG_SILENCE_MIN_SECONDS = 30.0
LONG_SILENCE_DURATION_RATIO = 0.25
SIGNIFICANT_CLIPPING_RATIO = 0.01
HIGH_NOISE_MIN_CONFIDENCE = 0.45
CLEAN_SPEECH_MIN_RATIO = 0.30
CLEAN_SPEECH_MAX_CLIPPING_RATIO = 0.001


def _language_fields(language: Optional[str]) -> tuple[LanguageMode, Optional[str]]:
    if language is None:
        return LanguageMode.AUTO, None
    if not isinstance(language, str):
        raise TypeError("language must be a string or None")
    explicit = language.strip()
    if not explicit:
        return LanguageMode.AUTO, None
    return LanguageMode.EXPLICIT, explicit


def _build_strategy(
    profile: StrategyProfile,
    *,
    model_id: str,
    language: Optional[str],
    reason_codes: tuple[str, ...],
) -> TranscriptionStrategy:
    """把 profile 映射为固定配置；调用方不能注入底层 Whisper 参数。"""
    language_mode, explicit_language = _language_fields(language)

    if profile is StrategyProfile.DEFAULT:
        values = dict(
            normalize_volume=False,
            chunk_seconds=600.0,
            overlap_seconds=0.0,
            boundary_profile=ChunkBoundaryProfile.CURRENT_DEFAULT,
            vad_profile=VadProfile.CURRENT_DEFAULT,
            decode_profile=DecodeProfile.CURRENT_DEFAULT,
            max_segment_retries=0,
            retry_profile=None,
        )
    elif profile is StrategyProfile.CLEAN_SPEECH:
        values = dict(
            normalize_volume=False,
            chunk_seconds=600.0,
            overlap_seconds=0.0,
            boundary_profile=ChunkBoundaryProfile.CURRENT_DEFAULT,
            vad_profile=VadProfile.STANDARD,
            decode_profile=DecodeProfile.CLEAN,
            max_segment_retries=1,
            retry_profile=StrategyProfile.SAFE_FALLBACK,
        )
    elif profile is StrategyProfile.LONG_FORM:
        values = dict(
            normalize_volume=False,
            chunk_seconds=300.0,
            overlap_seconds=10.0,
            boundary_profile=ChunkBoundaryProfile.PADDED,
            vad_profile=VadProfile.STANDARD,
            decode_profile=DecodeProfile.ROBUST,
            max_segment_retries=1,
            retry_profile=StrategyProfile.SAFE_FALLBACK,
        )
    elif profile is StrategyProfile.SILENCE_HEAVY:
        values = dict(
            normalize_volume=False,
            chunk_seconds=300.0,
            overlap_seconds=5.0,
            boundary_profile=ChunkBoundaryProfile.PADDED,
            vad_profile=VadProfile.SILENCE_HEAVY,
            decode_profile=DecodeProfile.ROBUST,
            max_segment_retries=1,
            retry_profile=StrategyProfile.SAFE_FALLBACK,
        )
    elif profile is StrategyProfile.LOW_VOLUME_OR_NOISY:
        values = dict(
            normalize_volume=True,
            chunk_seconds=300.0,
            overlap_seconds=10.0,
            boundary_profile=ChunkBoundaryProfile.PADDED,
            vad_profile=VadProfile.STANDARD,
            decode_profile=DecodeProfile.ROBUST,
            max_segment_retries=1,
            retry_profile=StrategyProfile.SAFE_FALLBACK,
        )
    elif profile is StrategyProfile.SAFE_FALLBACK:
        # 安全兜底必须保持 Task 3 之前的行为基线。
        values = dict(
            normalize_volume=False,
            chunk_seconds=600.0,
            overlap_seconds=0.0,
            boundary_profile=ChunkBoundaryProfile.CURRENT_DEFAULT,
            vad_profile=VadProfile.CURRENT_DEFAULT,
            decode_profile=DecodeProfile.CURRENT_DEFAULT,
            max_segment_retries=0,
            retry_profile=None,
        )
    else:  # pragma: no cover - StrategyProfile 是闭集，此处防止未来新增值静默降级。
        raise ValueError(f"unsupported strategy profile: {profile}")

    return TranscriptionStrategy(
        profile=profile,
        model_id=model_id,
        language_mode=language_mode,
        language=explicit_language,
        reason_codes=reason_codes,
        **values,
    )


def _fallback_reasons(audio_profile: AudioProfile) -> tuple[str, ...]:
    reasons: list[str] = []
    if audio_profile.analysis_status is AudioAnalysisStatus.NOT_ANALYZED:
        reasons.append("audio_not_analyzed")
    elif audio_profile.analysis_status is AudioAnalysisStatus.PARTIAL:
        reasons.append("audio_analysis_partial")
    elif audio_profile.analysis_status is AudioAnalysisStatus.FAILED:
        reasons.append("audio_analysis_failed")
    if audio_profile.quality_grade is AudioQualityGrade.UNUSABLE:
        reasons.append("audio_unusable")
    reasons.extend(f"integrity_{flag.value}" for flag in audio_profile.integrity_flags)
    return tuple(dict.fromkeys(reasons)) or ("safe_fallback",)


def select_transcription_strategy(
    audio_profile: AudioProfile,
    *,
    model_id: str,
    language: Optional[str] = None,
) -> TranscriptionStrategy:
    """确定性选择一个宿主白名单策略。

    优先级体现风险：分析/完整性异常 → 低音量或高噪声 → 大量静音 →
    长音频 → 干净语音 → 当前默认。复合场景因此也只会得到一个稳定结果。
    """
    if not isinstance(audio_profile, AudioProfile):
        raise TypeError("audio_profile must be an AudioProfile")

    if (
        audio_profile.analysis_status is not AudioAnalysisStatus.COMPLETE
        or audio_profile.quality_grade is AudioQualityGrade.UNUSABLE
        or audio_profile.integrity_flags
    ):
        return _build_strategy(
            StrategyProfile.SAFE_FALLBACK,
            model_id=model_id,
            language=language,
            reason_codes=_fallback_reasons(audio_profile),
        )

    robust_reasons: list[str] = []
    if audio_profile.low_volume is True:
        robust_reasons.append("low_volume")
    if (
        audio_profile.noise_level is HeuristicLevel.HIGH
        and (audio_profile.noise_confidence or 0.0) >= HIGH_NOISE_MIN_CONFIDENCE
    ):
        robust_reasons.append("high_noise")
    if (audio_profile.clipping_ratio or 0.0) >= SIGNIFICANT_CLIPPING_RATIO:
        robust_reasons.append("significant_clipping")
    if audio_profile.quality_grade is AudioQualityGrade.POOR:
        robust_reasons.append("poor_audio_quality")
    if robust_reasons:
        return _build_strategy(
            StrategyProfile.LOW_VOLUME_OR_NOISY,
            model_id=model_id,
            language=language,
            reason_codes=tuple(dict.fromkeys(robust_reasons)),
        )

    silence_reasons: list[str] = []
    if (audio_profile.silence_ratio or 0.0) >= SILENCE_HEAVY_RATIO:
        silence_reasons.append("silence_ratio_high")
    duration = audio_profile.duration_seconds or 0.0
    long_silence_threshold = max(
        LONG_SILENCE_MIN_SECONDS,
        duration * LONG_SILENCE_DURATION_RATIO,
    )
    if (audio_profile.longest_silence_seconds or 0.0) >= long_silence_threshold:
        silence_reasons.append("long_silence")
    if silence_reasons:
        return _build_strategy(
            StrategyProfile.SILENCE_HEAVY,
            model_id=model_id,
            language=language,
            reason_codes=tuple(silence_reasons),
        )

    if duration >= LONG_FORM_MIN_SECONDS:
        return _build_strategy(
            StrategyProfile.LONG_FORM,
            model_id=model_id,
            language=language,
            reason_codes=("long_duration",),
        )

    is_clean = (
        audio_profile.quality_grade is AudioQualityGrade.GOOD
        and audio_profile.low_volume is False
        and (audio_profile.clipping_ratio or 0.0) <= CLEAN_SPEECH_MAX_CLIPPING_RATIO
        and (audio_profile.speech_ratio or 0.0) >= CLEAN_SPEECH_MIN_RATIO
        and audio_profile.noise_level is not HeuristicLevel.HIGH
    )
    if is_clean:
        return _build_strategy(
            StrategyProfile.CLEAN_SPEECH,
            model_id=model_id,
            language=language,
            reason_codes=("clean_audio_metrics",),
        )

    return _build_strategy(
        StrategyProfile.DEFAULT,
        model_id=model_id,
        language=language,
        reason_codes=("current_default", "no_special_audio_condition"),
    )


__all__ = ["select_transcription_strategy"]
