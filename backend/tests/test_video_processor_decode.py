from __future__ import annotations

import io
import wave

import numpy as np
import pytest

import video_processor as vp


def _wav_bytes(samples: np.ndarray, *, rate: int = vp.TRANSCRIBE_SAMPLE_RATE) -> bytes:
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def test_pcm_from_wav_bytes_roundtrips_mono_speech():
    expected = np.array([0.0, 0.25, -0.5, 0.75], dtype=np.float32)
    actual = vp._pcm_from_wav_bytes(_wav_bytes(expected))
    assert actual == pytest.approx(expected, abs=2 / 32768)


def test_media_stderr_summary_keeps_the_real_ffmpeg_error():
    stderr = """
ffmpeg version 7.1.1 Copyright (c) 2000-2025 the FFmpeg developers
built with Apple clang version 17.0.0 (clang-1700.4.4.1)
configuration: --enable-static --disable-shared --disable-everything
libavutil      59. 39.100 / 59. 39.100
[AVFormatContext @ 0x1] Requested output format 's16le' is not known.
Error opening output files: Invalid argument
"""
    summary = vp._media_stderr_summary(stderr)
    assert "s16le" in summary
    assert "Invalid argument" in summary
    assert "ffmpeg version" not in summary
    assert "configuration:" not in summary


def test_decode_audio_chunk_requests_wav_not_raw_s16le(monkeypatch, tmp_path):
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"fake")
    expected = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    captured: dict[str, list[str]] = {}

    def _fake_run(cmd, timeout=None, label="ffmpeg"):
        captured["cmd"] = cmd
        return _wav_bytes(expected)

    monkeypatch.setattr(vp, "_run_media_proc_bytes", _fake_run)
    actual = vp.decode_audio_chunk(str(audio), 1.5, 2.0)

    assert captured["cmd"][0] == vp.FFMPEG_BIN
    assert "-hide_banner" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("-f") + 1] == "wav"
    assert "s16le" not in captured["cmd"]
    assert actual == pytest.approx(expected, abs=2 / 32768)
