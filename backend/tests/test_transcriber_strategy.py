from __future__ import annotations

import numpy as np
import pytest

import transcriber as module
from media_contracts import (
    AudioAnalysisStatus,
    AudioProfile,
    AudioQualityGrade,
    FinalTranscriptSelection,
)
from transcription_strategy import select_transcription_strategy
from transcriber import Transcriber, _ensure_mlx_whisper_import_shims


def _profile(**overrides):
    values = dict(
        analysis_status=AudioAnalysisStatus.COMPLETE,
        container="wav",
        codec="pcm_s16le",
        duration_seconds=60.0,
        sample_rate_hz=16000,
        channels=1,
        bitrate_bps=256000,
        rms_amplitude=0.08,
        peak_amplitude=0.4,
        clipping_ratio=0.0,
        low_volume=False,
        speech_duration_seconds=40.0,
        speech_ratio=2 / 3,
        silence_ratio=1 / 3,
        longest_silence_seconds=5.0,
        quality_grade=AudioQualityGrade.GOOD,
        reason_codes=("metrics_within_range",),
    )
    values.update(overrides)
    return AudioProfile(**values)


def test_scipy_shim_provides_version_and_medfilt(monkeypatch):
    monkeypatch.delitem(__import__("sys").modules, "scipy", raising=False)
    monkeypatch.delitem(__import__("sys").modules, "scipy.signal", raising=False)
    _ensure_mlx_whisper_import_shims()
    import scipy
    import scipy.signal

    assert scipy.__version__
    filtered = scipy.signal.medfilt(np.array([1.0, 8.0, 1.0]), kernel_size=3)
    assert filtered.shape == (3,)


@pytest.mark.asyncio
async def test_host_strategy_controls_chunking_overlap_and_decode_profile(tmp_path, monkeypatch):
    audio = tmp_path / "long.wav"
    audio.touch()
    transcriber = Transcriber(model_size="base", model_path="local")
    profile = _profile(
        duration_seconds=7200.0,
        speech_duration_seconds=5000.0,
        speech_ratio=5000 / 7200,
        silence_ratio=2200 / 7200,
    )
    strategy = select_transcription_strategy(profile, model_id="base")
    decoded: list[tuple[float, float | None]] = []
    decode_profiles = []

    monkeypatch.setattr(transcriber, "_load_model", lambda: None)
    monkeypatch.setattr(module, "probe_duration", lambda _path: 620.0)

    def _decode(_path, start, duration):
        decoded.append((start, duration))
        return np.full(16000, 0.1, dtype=np.float32)

    def _vad(samples, _options=None):
        return [{"start": 0, "end": len(samples)}]

    def _chunk(_samples, _language, _clip, decode_profile):
        decode_profiles.append(decode_profile)
        return {"language": "en", "segments": []}

    async def _run(fn, *args):
        return fn(*args)

    monkeypatch.setattr(module, "decode_audio_chunk", _decode)
    monkeypatch.setattr(module, "get_speech_timestamps", _vad)
    monkeypatch.setattr(module, "_run_on_mlx_thread", _run)
    monkeypatch.setattr(transcriber, "_transcribe_chunk", _chunk)

    await transcriber.transcribe(str(audio), strategy=strategy)

    assert decoded == [(0.0, 300.0), (290.0, 300.0), (580.0, None)]
    assert decode_profiles == [strategy.decode_profile] * 3


@pytest.mark.asyncio
async def test_quality_path_retries_only_one_suspicious_range(tmp_path, monkeypatch):
    audio = tmp_path / "repeat.wav"
    audio.touch()
    transcriber = Transcriber(model_size="base", model_path="local")
    profile = _profile(duration_seconds=30.0, speech_duration_seconds=20.0)
    strategy = select_transcription_strategy(profile, model_id="base")
    calls = []

    async def _initial(_path, **kwargs):
        raw = [
            {"start": 10, "end": 11, "text": "谢谢观看"},
            {"start": 12, "end": 13, "text": "谢谢观看"},
            {"start": 14, "end": 15, "text": "谢谢观看"},
            {"start": 16, "end": 17, "text": "谢谢观看"},
        ]
        kwargs["_segments_callback"]("zh", raw)
        kwargs["_speech_ranges_callback"]([(10, 18)])
        return transcriber._assemble_markdown("zh", raw)

    def _decode(*args):
        calls.append(args)
        return np.full(16000, 0.1, dtype=np.float32)

    async def _run(_fn, *_args):
        return {
            "language": "zh",
            "segments": [{"start": 0, "end": 8, "text": "这是实际语句"}],
        }

    monkeypatch.setattr(transcriber, "transcribe", _initial)
    monkeypatch.setattr(module, "decode_audio_chunk", _decode)
    monkeypatch.setattr(module, "_run_on_mlx_thread", _run)

    outcome = await transcriber.transcribe_with_quality(
        str(audio),
        audio_profile=profile,
        strategy=strategy,
    )

    assert len(calls) == 1
    assert "这是实际语句" in outcome.transcript
    assert outcome.quality_report.retry_records[0].selected is FinalTranscriptSelection.RETRY

