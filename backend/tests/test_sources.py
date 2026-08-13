"""sources.extract_media_source 的单元测试。

该模块刻意把 video_processor / transcriber / 各阶段回调以参数注入，
正是为了能在不触碰 services 与 task_store 的前提下单测两条提取路径。
这里用轻量假对象验证「字幕快速通道」与「Whisper 慢速通道」的编排。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cancellation import CancelledByUser
from exceptions import MediaExtractionError
from media_contracts import (
    AudioAnalysisStatus,
    AudioProfile,
    ExtractionAction,
    ExtractionFailure,
    ExtractionFailureKind,
    ExtractionStage,
    SubtitleFetchResult,
    SubtitleFetchStatus,
)
from sources import ExtractResult, extract_media_source
from media_recovery import RecoveryResult, RecoveryRunStatus


class FakeVideoProcessor:
    def __init__(self, subtitles=None, title="下载标题", duration=0):
        self._subtitles = subtitles  # (text, title, lang, duration) 或 None
        self._title = title
        self._duration = duration
        self.downloaded = False

    async def get_video_title(self, url):
        return "音频标题"

    async def fetch_subtitles(self, url, temp_dir):
        if isinstance(self._subtitles, Exception):
            raise self._subtitles
        if self._subtitles:
            text, title, language, duration = self._subtitles
            return SubtitleFetchResult(
                status=SubtitleFetchStatus.FOUND,
                text=text,
                title=title,
                language=language,
                duration_seconds=duration,
            )
        return SubtitleFetchResult(status=SubtitleFetchStatus.NO_SUBTITLES)

    async def download_and_convert(
        self,
        url,
        temp_dir,
        *,
        prefetched_title=None,
        prefetched_duration=0,
        previous_actions=(),
    ):
        self.downloaded = True
        self.previous_actions = previous_actions
        return str(temp_dir / "audio.mp3"), self._title


class FakeTranscriber:
    def __init__(self):
        self.called_with = None

    async def transcribe(self, audio_path, progress_callback=None):
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
        assert result.subtitle_status is SubtitleFetchStatus.FOUND
        assert result.extraction_failure is None

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
        assert result.subtitle_status is SubtitleFetchStatus.NO_SUBTITLES
        assert result.extraction_failure is None
        assert vp.previous_actions == (ExtractionAction.INSPECT_METADATA,)

    async def test_transcribe_stage_reaches_complete(self):
        vp = FakeVideoProcessor(subtitles=None)
        rec = Recorder()

        await _run(vp, FakeTranscriber(), rec)

        assert ("transcribe", 100) in rec.stages

    async def test_audio_profile_is_produced_before_whisper(self):
        vp = FakeVideoProcessor(subtitles=None)
        profile = AudioProfile(
            analysis_status=AudioAnalysisStatus.PARTIAL,
            duration_seconds=12,
            analysis_error="metadata incomplete",
        )
        analyzed_paths = []

        async def _analyze(audio_path):
            analyzed_paths.append(audio_path)
            return profile

        result = await _run(
            vp,
            FakeTranscriber(),
            Recorder(),
            analyze_audio=_analyze,
        )

        assert analyzed_paths == [str(Path("/tmp/audio.mp3"))]
        assert result.audio_profile is profile

    async def test_audio_analysis_failure_does_not_block_default_transcription(self):
        async def _fail(_audio_path):
            raise RuntimeError("profile unavailable")

        result = await _run(
            FakeVideoProcessor(subtitles=None),
            FakeTranscriber(),
            Recorder(),
            analyze_audio=_fail,
        )

        assert result.raw_script == "whisper 转录正文"
        assert result.audio_profile.analysis_status is AudioAnalysisStatus.FAILED


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


class TestSubtitleFailureBoundary:
    async def test_failure_still_uses_existing_audio_fallback_and_is_preserved(self):
        failure = ExtractionFailure(
            platform="youtube",
            stage=ExtractionStage.SUBTITLE_DOWNLOAD,
            kind=ExtractionFailureKind.SUBTITLE_DOWNLOAD_FAILED,
            sanitized_summary="subtitle request failed",
            attempted_actions=(
                ExtractionAction.INSPECT_METADATA,
                ExtractionAction.DOWNLOAD_SUBTITLE,
            ),
        )
        vp = FakeVideoProcessor()

        async def _failed_subtitles(url, temp_dir):
            return SubtitleFetchResult(
                status=SubtitleFetchStatus.FAILED,
                title="预取标题",
                duration_seconds=90,
                failure=failure,
            )

        vp.fetch_subtitles = _failed_subtitles
        result = await _run(vp, FakeTranscriber(), Recorder())

        assert result.mode == "whisper"
        assert result.subtitle_status is SubtitleFetchStatus.FAILED
        assert result.extraction_failure is failure
        assert vp.downloaded is True
        assert vp.previous_actions == failure.attempted_actions

    async def test_user_cancellation_never_falls_back_to_audio(self):
        vp = FakeVideoProcessor(subtitles=CancelledByUser())

        with pytest.raises(CancelledByUser):
            await _run(vp, FakeTranscriber(), Recorder())

        assert vp.downloaded is False


class TestRecoveryBoundary:
    async def test_normal_success_path_never_calls_recovery(self):
        calls = []

        async def _recover(*args):
            calls.append(args)
            raise AssertionError("normal path must not start recovery")

        result = await _run(
            FakeVideoProcessor(subtitles=None),
            FakeTranscriber(),
            Recorder(),
            recover_media=_recover,
        )

        assert result.mode == "whisper"
        assert calls == []

    async def test_unavailable_recovery_preserves_original_media_error(self):
        failure = ExtractionFailure(
            platform="youtube",
            stage=ExtractionStage.MEDIA_DOWNLOAD,
            kind=ExtractionFailureKind.MEDIA_DOWNLOAD_FAILED,
            sanitized_summary="original download failure",
        )
        vp = FakeVideoProcessor(subtitles=None)

        async def _failed_download(*args, **kwargs):
            raise MediaExtractionError(failure)

        async def _recover(url, received):
            assert received is failure
            return RecoveryResult(
                status=RecoveryRunStatus.UNAVAILABLE,
                code="model_unavailable",
                message="disabled",
            )

        vp.download_and_convert = _failed_download
        with pytest.raises(MediaExtractionError) as caught:
            await _run(vp, FakeTranscriber(), Recorder(), recover_media=_recover)

        assert caught.value.failure is failure
