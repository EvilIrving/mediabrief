from __future__ import annotations

import math

import numpy as np
import pytest

import audio_profiler as P
from cancellation import CancelledByUser
from media_contracts import (
    AudioAnalysisStatus,
    AudioIntegrityFlag,
    AudioQualityGrade,
)


SAMPLE_RATE = 16_000


def _facts(duration: float) -> P._MediaFacts:
    return P._MediaFacts(
        container="wav",
        codec="pcm_s16le",
        duration_seconds=duration,
        sample_rate_hz=SAMPLE_RATE,
        channels=1,
        bitrate_bps=256_000,
        has_audio=True,
    )


def _runs_above(threshold: float):
    def detect(waveform: np.ndarray):
        active = np.flatnonzero(np.abs(waveform) > threshold)
        if not active.size:
            return []
        splits = np.flatnonzero(np.diff(active) > 1) + 1
        groups = np.split(active, splits)
        return [{"start": int(group[0]), "end": int(group[-1] + 1)} for group in groups]

    return detect


def _install_wave(monkeypatch, waveform: np.ndarray):
    duration = waveform.size / SAMPLE_RATE
    monkeypatch.setattr(P, "_probe_audio", lambda _path: _facts(duration))

    def decode(_path, start, requested_duration):
        begin = round(start * SAMPLE_RATE)
        end = begin + round(requested_duration * SAMPLE_RATE)
        return waveform[begin:end]

    monkeypatch.setattr(P, "decode_audio_chunk", decode)


def test_normal_speech_waveform_has_traceable_good_profile(tmp_path, monkeypatch):
    path = tmp_path / "normal.wav"
    path.touch()
    seconds = 8
    time = np.arange(seconds * SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE
    waveform = 0.1 * np.sin(2 * np.pi * 220 * time)
    _install_wave(monkeypatch, waveform)

    profile = P.analyze_audio(
        path,
        vad_detector=lambda samples: [{"start": 0, "end": samples.size}],
    )

    assert profile.analysis_status is AudioAnalysisStatus.COMPLETE
    assert profile.quality_grade is AudioQualityGrade.GOOD
    assert profile.reason_codes == ("metrics_within_range",)
    assert profile.rms_amplitude == pytest.approx(0.1 / math.sqrt(2), rel=1e-3)
    assert profile.peak_amplitude == pytest.approx(0.1, rel=1e-3)
    assert profile.speech_ratio == pytest.approx(1.0)
    assert profile.silence_ratio == pytest.approx(0.0)


def test_all_silence_is_explicitly_unusable(tmp_path, monkeypatch):
    path = tmp_path / "silence.wav"
    path.touch()
    waveform = np.zeros(8 * SAMPLE_RATE, dtype=np.float32)
    _install_wave(monkeypatch, waveform)

    profile = P.analyze_audio(path, vad_detector=lambda _samples: [])

    assert profile.analysis_status is AudioAnalysisStatus.COMPLETE
    assert AudioIntegrityFlag.ALL_SILENCE in profile.integrity_flags
    assert profile.quality_grade is AudioQualityGrade.UNUSABLE
    assert profile.reason_codes == ("all_silence",)
    assert profile.speech_ratio == 0.0
    assert profile.silence_ratio == 1.0
    assert profile.longest_silence_seconds == pytest.approx(8.0)


def test_low_volume_is_reported_from_rms(tmp_path, monkeypatch):
    path = tmp_path / "quiet.wav"
    path.touch()
    time = np.arange(10 * SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE
    waveform = 0.005 * np.sin(2 * np.pi * 180 * time)
    _install_wave(monkeypatch, waveform)

    profile = P.analyze_audio(
        path,
        vad_detector=lambda samples: [{"start": 0, "end": samples.size}],
    )

    assert profile.analysis_status is AudioAnalysisStatus.COMPLETE
    assert profile.low_volume is True
    assert profile.rms_amplitude == pytest.approx(0.005 / math.sqrt(2), rel=1e-3)
    assert profile.quality_grade is AudioQualityGrade.FAIR
    assert "low_volume" in profile.reason_codes


def test_clipped_waveform_reports_ratio_and_poor_grade(tmp_path, monkeypatch):
    path = tmp_path / "clipped.wav"
    path.touch()
    waveform = np.ones(6 * SAMPLE_RATE, dtype=np.float32)
    waveform[1::2] = -1.0
    _install_wave(monkeypatch, waveform)

    profile = P.analyze_audio(
        path,
        vad_detector=lambda samples: [{"start": 0, "end": samples.size}],
    )

    assert profile.analysis_status is AudioAnalysisStatus.COMPLETE
    assert profile.peak_amplitude == 1.0
    assert profile.clipping_ratio == 1.0
    assert profile.quality_grade is AudioQualityGrade.POOR
    assert "clipping_detected" in profile.reason_codes


def test_long_silence_spanning_chunks_uses_original_timeline(tmp_path, monkeypatch):
    path = tmp_path / "long-silence.wav"
    path.touch()
    # 10s speech + 50s silence + 15s speech: the silence crosses both 30s boundaries.
    waveform = np.zeros(75 * SAMPLE_RATE, dtype=np.float32)
    waveform[: 10 * SAMPLE_RATE] = 0.1
    waveform[60 * SAMPLE_RATE :] = -0.1
    _install_wave(monkeypatch, waveform)
    decoded_starts: list[float] = []
    original_decode = P.decode_audio_chunk

    def decode(*args):
        decoded_starts.append(args[1])
        return original_decode(*args)

    monkeypatch.setattr(P, "decode_audio_chunk", decode)

    profile = P.analyze_audio(path, vad_detector=_runs_above(0.01))

    assert decoded_starts == [0.0, 30.0, 60.0]
    assert profile.analysis_status is AudioAnalysisStatus.COMPLETE
    assert profile.speech_duration_seconds == pytest.approx(25.0)
    assert profile.speech_ratio == pytest.approx(1 / 3)
    assert profile.silence_ratio == pytest.approx(2 / 3)
    assert profile.longest_silence_seconds == pytest.approx(50.0)
    assert "long_silence" in profile.reason_codes


def test_vad_failure_returns_partial_profile_with_pcm_facts(tmp_path, monkeypatch):
    path = tmp_path / "vad-failure.wav"
    path.touch()
    waveform = np.full(5 * SAMPLE_RATE, 0.1, dtype=np.float32)
    _install_wave(monkeypatch, waveform)

    def fail_vad(_samples):
        raise RuntimeError("model unavailable")

    profile = P.analyze_audio(path, vad_detector=fail_vad)

    assert profile.analysis_status is AudioAnalysisStatus.PARTIAL
    assert profile.rms_amplitude == pytest.approx(0.1)
    assert profile.speech_ratio is None
    assert profile.quality_grade is AudioQualityGrade.UNKNOWN
    assert "model unavailable" in (profile.analysis_error or "")


def test_user_cancellation_is_never_converted_to_failed_profile(tmp_path, monkeypatch):
    path = tmp_path / "cancel.wav"
    path.touch()
    monkeypatch.setattr(P, "_probe_audio", lambda _path: _facts(5.0))

    def cancelled(*_args):
        raise CancelledByUser()

    monkeypatch.setattr(P, "decode_audio_chunk", cancelled)

    with pytest.raises(CancelledByUser):
        P.analyze_audio(path, vad_detector=lambda _samples: [])
