from dataclasses import replace

import pytest

from media_contracts import (
    AudioAnalysisStatus,
    AudioIntegrityFlag,
    AudioProfile,
    AudioQualityGrade,
    ChunkBoundaryProfile,
    DecodeProfile,
    HeuristicLevel,
    LanguageMode,
    StrategyProfile,
    VadProfile,
)
from transcription_strategy import select_transcription_strategy


def _complete_profile(
    *,
    duration_seconds: float = 900.0,
    silence_ratio: float = 0.30,
    longest_silence_seconds: float = 8.0,
    rms_amplitude: float = 0.12,
    clipping_ratio: float = 0.0,
    low_volume: bool = False,
    quality_grade: AudioQualityGrade = AudioQualityGrade.GOOD,
    noise_level: HeuristicLevel | None = None,
    noise_confidence: float | None = None,
) -> AudioProfile:
    speech_ratio = 1.0 - silence_ratio
    return AudioProfile(
        analysis_status=AudioAnalysisStatus.COMPLETE,
        container="mov,mp4,m4a",
        codec="aac",
        duration_seconds=duration_seconds,
        sample_rate_hz=48000,
        channels=2,
        bitrate_bps=128000,
        rms_amplitude=rms_amplitude,
        peak_amplitude=0.8,
        clipping_ratio=clipping_ratio,
        low_volume=low_volume,
        speech_duration_seconds=duration_seconds * speech_ratio,
        speech_ratio=speech_ratio,
        silence_ratio=silence_ratio,
        longest_silence_seconds=longest_silence_seconds,
        noise_level=noise_level,
        noise_confidence=noise_confidence,
        quality_grade=quality_grade,
        reason_codes=(
            ("metrics_within_range",)
            if quality_grade is AudioQualityGrade.GOOD
            else ("audio_quality_warning",)
        ),
    )


def test_clean_speech_uses_clean_whitelisted_profile_and_preserves_identity():
    profile = _complete_profile()

    strategy = select_transcription_strategy(
        profile,
        model_id="large-v3-turbo",
        language=" zh ",
    )

    assert strategy.profile is StrategyProfile.CLEAN_SPEECH
    assert strategy.model_id == "large-v3-turbo"
    assert strategy.language_mode is LanguageMode.EXPLICIT
    assert strategy.language == "zh"
    assert strategy.decode_profile is DecodeProfile.CLEAN
    assert strategy.reason_codes == ("clean_audio_metrics",)


def test_long_audio_selects_long_form_before_clean_speech():
    strategy = select_transcription_strategy(
        _complete_profile(duration_seconds=7200.0),
        model_id="base",
    )

    assert strategy.profile is StrategyProfile.LONG_FORM
    assert strategy.chunk_seconds == 300.0
    assert strategy.overlap_seconds == 10.0
    assert strategy.boundary_profile is ChunkBoundaryProfile.PADDED
    assert strategy.reason_codes == ("long_duration",)


@pytest.mark.parametrize(
    ("profile", "expected_reason"),
    [
        (_complete_profile(silence_ratio=0.75, longest_silence_seconds=8.0), "silence_ratio_high"),
        (_complete_profile(silence_ratio=0.40, longest_silence_seconds=240.0), "long_silence"),
    ],
)
def test_silence_metrics_select_silence_heavy(profile, expected_reason):
    strategy = select_transcription_strategy(profile, model_id="base")

    assert strategy.profile is StrategyProfile.SILENCE_HEAVY
    assert strategy.vad_profile is VadProfile.SILENCE_HEAVY
    assert expected_reason in strategy.reason_codes


@pytest.mark.parametrize(
    ("profile", "expected_reason"),
    [
        (
            _complete_profile(
                rms_amplitude=0.005,
                low_volume=True,
                quality_grade=AudioQualityGrade.FAIR,
            ),
            "low_volume",
        ),
        (
            _complete_profile(
                quality_grade=AudioQualityGrade.FAIR,
                noise_level=HeuristicLevel.HIGH,
                noise_confidence=0.60,
            ),
            "high_noise",
        ),
    ],
)
def test_low_volume_or_confident_high_noise_selects_robust_profile(profile, expected_reason):
    strategy = select_transcription_strategy(profile, model_id="base")

    assert strategy.profile is StrategyProfile.LOW_VOLUME_OR_NOISY
    assert strategy.normalize_volume is True
    assert strategy.decode_profile is DecodeProfile.ROBUST
    assert expected_reason in strategy.reason_codes


def test_ordinary_fair_audio_keeps_current_default_behavior():
    profile = _complete_profile(quality_grade=AudioQualityGrade.FAIR)

    strategy = select_transcription_strategy(profile, model_id="base")

    assert strategy.profile is StrategyProfile.DEFAULT
    assert strategy.chunk_seconds == 600.0
    assert strategy.overlap_seconds == 0.0
    assert strategy.boundary_profile is ChunkBoundaryProfile.CURRENT_DEFAULT
    assert strategy.vad_profile is VadProfile.CURRENT_DEFAULT
    assert strategy.decode_profile is DecodeProfile.CURRENT_DEFAULT
    assert strategy.max_segment_retries == 0
    assert strategy.retry_profile is None


@pytest.mark.parametrize(
    "profile",
    [
        AudioProfile(),
        AudioProfile(
            analysis_status=AudioAnalysisStatus.FAILED,
            integrity_flags=(AudioIntegrityFlag.CORRUPT,),
            quality_grade=AudioQualityGrade.UNUSABLE,
            reason_codes=("analysis_failed",),
            analysis_error="decode failed",
        ),
        replace(
            _complete_profile(quality_grade=AudioQualityGrade.FAIR),
            integrity_flags=(AudioIntegrityFlag.ABNORMALLY_SHORT,),
        ),
    ],
)
def test_unavailable_or_unreliable_analysis_uses_exact_safe_fallback(profile):
    strategy = select_transcription_strategy(profile, model_id="base")

    assert strategy.profile is StrategyProfile.SAFE_FALLBACK
    assert strategy.chunk_seconds == 600.0
    assert strategy.overlap_seconds == 0.0
    assert strategy.boundary_profile is ChunkBoundaryProfile.CURRENT_DEFAULT
    assert strategy.vad_profile is VadProfile.CURRENT_DEFAULT
    assert strategy.decode_profile is DecodeProfile.CURRENT_DEFAULT
    assert strategy.normalize_volume is False
    assert strategy.max_segment_retries == 0
    assert strategy.retry_profile is None


def test_selection_is_deterministic_and_auto_language_is_preserved():
    profile = _complete_profile(silence_ratio=0.70)

    first = select_transcription_strategy(profile, model_id="base")
    second = select_transcription_strategy(profile, model_id="base", language="  ")

    assert first == second
    assert first.language_mode is LanguageMode.AUTO
    assert first.language is None


def test_selector_rejects_untyped_profile_instead_of_accepting_parameter_dict():
    with pytest.raises(TypeError):
        select_transcription_strategy({"silence_ratio": 0.8}, model_id="base")
