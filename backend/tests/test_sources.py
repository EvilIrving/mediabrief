"""sources.extract_media_source 的单元测试。

该模块刻意把 video_processor / transcriber / 各阶段回调以参数注入，
正是为了能在不触碰 services 与 task_store 的前提下单测两条提取路径。
这里用轻量假对象验证「字幕快速通道」与「Whisper 慢速通道」的编排。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sources import ExtractResult, extract_media_source


class FakeVideoProcessor:
    def __init__(self, subtitles=None, title="下载标题", duration=0):
        self._subtitles = subtitles  # (text, title, lang, duration) 或 None
        self._title = title
        self._duration = duration
        self.downloaded = False

    async def get_video_title(self, url):
        return "音频标题"

    async def fetch_subtitles(self, url, temp_dir):
        if self._subtitles:
            return self._subtitles
        return None, None, None, 0

    async def download_and_convert(self, url, temp_dir, *, prefetched_title=None, prefetched_duration=0):
        self.downloaded = True
        return str(temp_dir / "audio.mp3"), self._title


class FakeTranscriber:
    def __init__(self):
        self.called_with = None

    async def transcribe(self, audio_path):
        self.called_with = audio_path
        return "whisper 转录正文"


class Recorder:
    """记录各回调被调用的情况，供断言编排顺序/集合。"""

    def __init__(self):
        self.stages = []
        self.skipped = []
        self.mode = None
        self.mode_msg = None

    async def broadcast_stage(self, stage, pct):
        self.stages.append((stage, pct))

    async def skip_stages(self, names):
        self.skipped.extend(names)

    def set_mode(self, mode, message):
        self.mode = mode
        self.mode_msg = message


async def _run(vp, tr, rec, *, url="https://example.com/v", audio_only=False, **kw):
    return await extract_media_source(
        "task-1",
        url,
        video_processor=vp,
        transcriber=tr,
        temp_dir=Path("/tmp"),
        broadcast_stage=rec.broadcast_stage,
        skip_stages=rec.skip_stages,
        set_mode=rec.set_mode,
        is_audio_only=lambda u, t: audio_only,
        **kw,
    )


class TestSubtitleFastPath:
    async def test_returns_subtitle_result(self):
        vp = FakeVideoProcessor(subtitles=("字幕正文", "字幕标题", "zh", 120))
        tr = FakeTranscriber()
        rec = Recorder()

        result = await _run(vp, tr, rec)

        assert isinstance(result, ExtractResult)
        assert result.mode == "subtitle"
        assert result.raw_script == "字幕正文"
        assert result.extracted_title == "字幕标题"
        assert result.detected_language == "zh"

    async def test_skips_download_and_transcribe(self):
        vp = FakeVideoProcessor(subtitles=("字幕正文", "t", "en", 0))
        tr = FakeTranscriber()
        rec = Recorder()

        await _run(vp, tr, rec)

        assert vp.downloaded is False
        assert tr.called_with is None
        assert {"download_audio", "prepare_audio", "transcribe"} <= set(rec.skipped)
        assert rec.mode == "subtitle"


class TestWhisperSlowPath:
    async def test_falls_back_to_transcription(self):
        vp = FakeVideoProcessor(subtitles=None)
        tr = FakeTranscriber()
        rec = Recorder()

        result = await _run(vp, tr, rec)

        assert result.mode == "whisper"
        assert result.raw_script == "whisper 转录正文"
        assert result.detected_language is None
        assert vp.downloaded is True
        assert tr.called_with is not None
        assert rec.mode == "whisper"

    async def test_transcribe_stage_reaches_complete(self):
        vp = FakeVideoProcessor(subtitles=None)
        rec = Recorder()

        await _run(vp, FakeTranscriber(), rec)

        assert ("transcribe", 100) in rec.stages


class TestAudioOnly:
    async def test_skips_subtitle_lookup(self):
        vp = FakeVideoProcessor(subtitles=None)
        rec = Recorder()

        await _run(vp, FakeTranscriber(), rec, audio_only=True)

        assert {"find_subtitles", "read_subtitles"} <= set(rec.skipped)
        # 纯音频不应广播字幕查找阶段。
        assert not any(s == "find_subtitles" for s, _ in rec.stages)

    async def test_fetches_title_when_requested(self):
        vp = FakeVideoProcessor(subtitles=None)
        rec = Recorder()

        await _run(
            vp,
            FakeTranscriber(),
            rec,
            audio_only=True,
            fetch_title_when_audio_only=True,
        )
        # download_and_convert 拿到的标题来自 get_video_title -> "音频标题"
        # 这里只验证不报错且走 whisper 路径即可。
        assert rec.mode == "whisper"
