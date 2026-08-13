from __future__ import annotations

import logging

import pytest

from cancellation import CancelledByUser
from media_contracts import (
    ExtractionFailureKind,
    ExtractionStage,
    SubtitleFetchStatus,
)
from video_processor import VideoProcessor, _YDLPLogger


def _processor(monkeypatch) -> VideoProcessor:
    processor = VideoProcessor.__new__(VideoProcessor)
    processor._cookies_opts = {}
    monkeypatch.setattr(processor, "_get_extract_opts", lambda url: {})
    monkeypatch.setattr(processor, "_get_download_opts", lambda url, extra=None: dict(extra or {}))
    return processor


async def test_confirmed_no_subtitles_is_not_a_failure(monkeypatch, tmp_path):
    processor = _processor(monkeypatch)

    async def _metadata(url, opts, timeout, attempted_actions=None):
        return {
            "title": "No captions",
            "duration": 12,
            "subtitles": {"live_chat": [{}]},
            "automatic_captions": {},
        }, opts

    monkeypatch.setattr(processor, "_extract_info_with_cookie_fallback", _metadata)
    result = await processor.fetch_subtitles("https://example.com/watch?v=private", tmp_path)

    assert result.status is SubtitleFetchStatus.NO_SUBTITLES
    assert result.failure is None
    assert result.title == "No captions"
    assert result.duration_seconds == 12


async def test_metadata_failure_is_classified_and_redacted(monkeypatch, tmp_path, caplog):
    processor = _processor(monkeypatch)

    async def _metadata(url, opts, timeout, attempted_actions=None):
        raise RuntimeError(
            "HTTP Error 429 https://example.com/watch?id=private api_key=top-secret"
        )

    monkeypatch.setattr(processor, "_extract_info_with_cookie_fallback", _metadata)
    caplog.set_level(logging.WARNING)
    result = await processor.fetch_subtitles("https://example.com/watch?id=private", tmp_path)

    assert result.status is SubtitleFetchStatus.FAILED
    assert result.failure.stage is ExtractionStage.METADATA
    assert result.failure.kind is ExtractionFailureKind.RATE_LIMITED
    assert "top-secret" not in result.failure.sanitized_summary
    assert "top-secret" not in caplog.text
    assert "?id=private" not in caplog.text


async def test_subtitle_download_failure_is_not_reported_as_absent(monkeypatch, tmp_path):
    processor = _processor(monkeypatch)

    async def _metadata(url, opts, timeout, attempted_actions=None):
        return {
            "title": "Has captions",
            "duration": 20,
            "subtitles": {"en": [{}]},
        }, opts

    async def _download(url, opts, timeout, label, attempted_actions=None):
        raise RuntimeError("subtitle CDN unavailable")

    monkeypatch.setattr(processor, "_extract_info_with_cookie_fallback", _metadata)
    monkeypatch.setattr(processor, "_download_with_cookie_fallback", _download)
    result = await processor.fetch_subtitles("https://example.com/watch", tmp_path)

    assert result.status is SubtitleFetchStatus.FAILED
    assert result.failure.stage is ExtractionStage.SUBTITLE_DOWNLOAD
    assert result.failure.kind is ExtractionFailureKind.SUBTITLE_DOWNLOAD_FAILED
    assert result.title == "Has captions"


async def test_empty_downloaded_subtitle_is_parse_failure(monkeypatch, tmp_path):
    processor = _processor(monkeypatch)

    async def _metadata(url, opts, timeout, attempted_actions=None):
        return {
            "title": "Broken captions",
            "duration": 30,
            "automatic_captions": {"en": [{}]},
        }, opts

    async def _download(url, opts, timeout, label, attempted_actions=None):
        out_dir = tmp_path / next(path.name for path in tmp_path.iterdir() if path.name.startswith("subs_"))
        (out_dir / "sub.en.vtt").write_text("WEBVTT\n\nnot a cue", encoding="utf-8")

    monkeypatch.setattr(processor, "_extract_info_with_cookie_fallback", _metadata)
    monkeypatch.setattr(processor, "_download_with_cookie_fallback", _download)
    result = await processor.fetch_subtitles("https://example.com/watch", tmp_path)

    assert result.status is SubtitleFetchStatus.FAILED
    assert result.failure.stage is ExtractionStage.SUBTITLE_PARSE
    assert result.failure.kind is ExtractionFailureKind.SUBTITLE_PARSE_FAILED


async def test_valid_subtitle_path_is_unchanged(monkeypatch, tmp_path):
    processor = _processor(monkeypatch)

    async def _metadata(url, opts, timeout, attempted_actions=None):
        return {
            "title": "Captioned",
            "duration": 45,
            "subtitles": {"en": [{}]},
        }, opts

    async def _download(url, opts, timeout, label, attempted_actions=None):
        out_dir = tmp_path / next(path.name for path in tmp_path.iterdir() if path.name.startswith("subs_"))
        (out_dir / "sub.en.vtt").write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello world\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(processor, "_extract_info_with_cookie_fallback", _metadata)
    monkeypatch.setattr(processor, "_download_with_cookie_fallback", _download)
    result = await processor.fetch_subtitles("https://example.com/watch", tmp_path)

    assert result.status is SubtitleFetchStatus.FOUND
    assert result.title == "Captioned"
    assert result.language == "en"
    assert "Hello world" in result.text


async def test_user_cancellation_is_never_converted_to_fallback(monkeypatch, tmp_path):
    processor = _processor(monkeypatch)

    async def _metadata(url, opts, timeout, attempted_actions=None):
        raise CancelledByUser()

    monkeypatch.setattr(processor, "_extract_info_with_cookie_fallback", _metadata)
    with pytest.raises(CancelledByUser):
        await processor.fetch_subtitles("https://example.com/watch", tmp_path)


def test_ytdlp_logger_redacts_before_writing(caplog):
    caplog.set_level(logging.WARNING)
    _YDLPLogger().warning(
        "failed https://example.com/watch?sig=url-secret Cookie: SID=cookie-secret"
    )
    assert "url-secret" not in caplog.text
    assert "cookie-secret" not in caplog.text
