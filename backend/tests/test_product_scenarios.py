"""Task 6 产品场景验证。

这些测试把已有的来源编排、受限恢复、音频策略和质量复核连起来，验证最终
产品语义；站点响应、模型和媒体解码全部使用本地 fake，不访问公网。
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

import pipeline
import transcriber as transcriber_module
from candidate_parser import (
    CandidateParserResult,
    CandidateResource,
    CandidateResultKind,
)
from media_contracts import (
    AudioAnalysisStatus,
    AudioProfile,
    AudioQualityGrade,
    ExtractionFailure,
    ExtractionFailureKind,
    ExtractionStage,
    FinalTranscriptSelection,
    ObservationStatus,
    RecoveryAction,
    RecoveryObservation,
    StrategyProfile,
    SubtitleFetchResult,
    SubtitleFetchStatus,
    TranscriptionOutcome,
    classify_extraction_failure,
)
from media_recovery import (
    MediaRecoveryCoordinator,
    RecoveryDecision,
    RecoveryResult,
    RecoveryRunStatus,
    UserActionCode,
)
from media_recovery_actions import MediaRecoveryActions
from sources import extract_media_source
from transcript_quality import evaluate_transcript
from transcription_strategy import select_transcription_strategy
from transcriber import Transcriber


class _SourceRecorder:
    def __init__(self):
        self.mode = None
        self.skipped: list[str] = []

    async def broadcast(self, *_args, **_kwargs):
        return None

    async def skip(self, stages):
        self.skipped.extend(stages)

    def set_mode(self, mode, _message):
        self.mode = mode


class _SourceVideoProcessor:
    def __init__(self, temp_dir: Path, subtitle_result: SubtitleFetchResult):
        self.temp_dir = temp_dir
        self.subtitle_result = subtitle_result
        self.download_calls = 0

    async def fetch_subtitles(self, _url, _temp_dir):
        return self.subtitle_result

    async def download_and_convert(self, _url, _temp_dir, **_kwargs):
        self.download_calls += 1
        path = self.temp_dir / f"source-{self.download_calls}.m4a"
        path.write_bytes(b"local fake audio")
        return str(path), "下载标题"


class _AdaptiveTranscriber:
    model_size = "base"

    def __init__(self):
        self.strategies = []

    async def transcribe_with_quality(
        self,
        _audio_path,
        *,
        audio_profile,
        strategy,
        progress_callback=None,
    ):
        self.strategies.append(strategy)
        end = min(audio_profile.duration_seconds or 10.0, 10.0)
        segments = [{"start": 0.0, "end": end, "text": "本地转录结果"}]
        report = evaluate_transcript(segments, audio_profile, speech_ranges=[(0.0, end)])
        return TranscriptionOutcome(
            transcript="**[00:00 - 00:10]**\n\n本地转录结果",
            strategy=strategy,
            quality_report=report,
        )


def _complete_profile(
    *,
    low_volume: bool = False,
    silence_ratio: float = 0.2,
) -> AudioProfile:
    duration = 120.0
    speech_ratio = 1.0 - silence_ratio
    return AudioProfile(
        analysis_status=AudioAnalysisStatus.COMPLETE,
        container="m4a",
        codec="aac",
        duration_seconds=duration,
        sample_rate_hz=48_000,
        channels=2,
        bitrate_bps=128_000,
        rms_amplitude=0.003 if low_volume else 0.08,
        peak_amplitude=0.03 if low_volume else 0.5,
        clipping_ratio=0.0,
        low_volume=low_volume,
        speech_duration_seconds=duration * speech_ratio,
        speech_ratio=speech_ratio,
        silence_ratio=silence_ratio,
        longest_silence_seconds=10.0,
        quality_grade=AudioQualityGrade.POOR if low_volume else AudioQualityGrade.GOOD,
        reason_codes=("low_volume",) if low_volume else ("metrics_within_range",),
    )


async def _extract(
    tmp_path: Path,
    video_processor,
    transcriber,
    *,
    analyze_audio=None,
    recover_media=None,
):
    recorder = _SourceRecorder()
    result = await extract_media_source(
        "scenario-task",
        "https://www.youtube.com/watch?v=public",
        video_processor=video_processor,
        transcriber=transcriber,
        temp_dir=tmp_path,
        broadcast_stage=recorder.broadcast,
        skip_stages=recorder.skip,
        set_mode=recorder.set_mode,
        is_audio_only=lambda _url, _kind: False,
        analyze_audio=analyze_audio,
        recover_media=recover_media,
    )
    return result, recorder


async def test_normal_subtitle_fast_path_never_starts_recovery_or_audio_work(tmp_path):
    video = _SourceVideoProcessor(
        tmp_path,
        SubtitleFetchResult(
            status=SubtitleFetchStatus.FOUND,
            text="公开字幕正文",
            title="公开样本",
            language="zh",
            duration_seconds=90,
        ),
    )
    transcriber = _AdaptiveTranscriber()
    recovery_calls = []
    analysis_calls = []

    async def _recover(*args):
        recovery_calls.append(args)
        raise AssertionError("正常字幕路径不得启动恢复")

    async def _analyze(path):
        analysis_calls.append(path)
        raise AssertionError("字幕快速路径不得分析音频")

    result, recorder = await _extract(
        tmp_path,
        video,
        transcriber,
        analyze_audio=_analyze,
        recover_media=_recover,
    )

    assert result.mode == "subtitle"
    assert result.raw_script == "公开字幕正文"
    assert result.audio_profile is None
    assert video.download_calls == 0
    assert transcriber.strategies == []
    assert recovery_calls == []
    assert analysis_calls == []
    assert {"download_audio", "prepare_audio", "transcribe"} <= set(recorder.skipped)


async def test_no_subtitle_audio_path_produces_profiles_and_distinct_explainable_strategies(tmp_path):
    profiles = (_complete_profile(), _complete_profile(low_volume=True))
    selected = []

    for index, profile in enumerate(profiles):
        video = _SourceVideoProcessor(
            tmp_path,
            SubtitleFetchResult(status=SubtitleFetchStatus.NO_SUBTITLES),
        )
        transcriber = _AdaptiveTranscriber()

        async def _analyze(_path, value=profile):
            return value

        result, _recorder = await _extract(
            tmp_path,
            video,
            transcriber,
            analyze_audio=_analyze,
        )
        selected.append(result.transcription_strategy)

        assert result.mode == "whisper"
        assert result.audio_profile is profile
        assert result.quality_report is not None
        assert result.transcription_strategy is transcriber.strategies[0]
        assert result.transcription_strategy.reason_codes
        assert video.download_calls == 1, index

    assert [item.profile for item in selected] == [
        StrategyProfile.CLEAN_SPEECH,
        StrategyProfile.LOW_VOLUME_OR_NOISY,
    ]
    assert selected[0].reason_codes == ("clean_audio_metrics",)
    assert "low_volume" in selected[1].reason_codes


class _DecisionModel:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    async def decide(self, _messages, _available_actions, *, max_output_chars):
        assert max_output_chars > 0
        return self.decisions.pop(0)


class _RecoveryVideoProcessor:
    def __init__(self, temp_dir: Path, *, browser_session: bool = False):
        self.temp_dir = temp_dir
        self.browser_session = browser_session
        self.used_profiles = []

    def recovery_profile_names(self, source_url):
        if "youtube" in source_url:
            return (
                "youtube_android_anonymous",
                "youtube_web_ejs",
                "youtube_browser_session",
            )
        return ("bilibili_anonymous", "bilibili_browser_session")

    def browser_session_available(self):
        return self.browser_session

    async def download_and_convert(self, _url, _temp_dir, *, recovery_profile=None):
        self.used_profiles.append(recovery_profile)
        output = self.temp_dir / "recovered.m4a"
        output.write_bytes(b"host verified local media")
        return str(output), "恢复标题"


def _failure(kind, *, platform="youtube", ejs=False, summary="媒体获取失败"):
    return ExtractionFailure(
        platform=platform,
        stage=ExtractionStage.MEDIA_DOWNLOAD,
        kind=kind,
        sanitized_summary=summary,
        cookie_available=False,
        deno_available=True,
        ejs_available=ejs,
    )


async def test_youtube_challenge_has_explicit_host_verified_recovery(tmp_path, monkeypatch):
    processor = _RecoveryVideoProcessor(tmp_path)
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=challenge",
        failure=_failure(ExtractionFailureKind.CHALLENGE_REQUIRED, ejs=True),
        video_processor=processor,
        temp_dir=tmp_path,
    )
    monkeypatch.setattr("media_recovery_actions.probe_duration", lambda _path: 30.0)
    model = _DecisionModel([
        RecoveryDecision("action", "request_youtube_challenge_capability", {}),
        RecoveryDecision("action", "run_ytdlp", {"profile": "youtube_android_anonymous"}),
        RecoveryDecision("completed", message="宿主产物已验证"),
    ])

    result = await MediaRecoveryCoordinator(model, actions).run(actions._failure)

    assert result.status is RecoveryRunStatus.RECOVERED
    assert result.code == "artifact_verified"
    assert processor.used_profiles == ["youtube_android_anonymous"]
    assert [item.code for item in result.observations] == [
        "challenge_capability_available",
        "media_downloaded",
    ]


async def test_login_failure_requests_one_fixed_user_action_and_ends_run(tmp_path):
    failure = _failure(ExtractionFailureKind.AUTH_REQUIRED)
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=login",
        failure=failure,
        video_processor=_RecoveryVideoProcessor(tmp_path, browser_session=False),
        temp_dir=tmp_path,
    )
    model = _DecisionModel([
        RecoveryDecision("action", "use_browser_session", {}),
        RecoveryDecision(
            "action",
            "ask_user",
            {"action_code": "login_then_retry", "message": "登录后重新入队继续"},
        ),
    ])

    result = await MediaRecoveryCoordinator(model, actions).run(failure)

    assert result.status is RecoveryRunStatus.ACTION_REQUIRED
    assert result.user_action is UserActionCode.LOGIN_THEN_RETRY
    assert result.continuation is not None
    assert not hasattr(result.continuation, "source_url")
    assert [item.code for item in result.observations] == [
        "browser_session_unavailable",
        "user_action_requested",
    ]


async def test_rate_limit_has_explicit_safe_stop(tmp_path):
    failure = _failure(ExtractionFailureKind.RATE_LIMITED, summary="HTTP 429 rate limited")
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=limited",
        failure=failure,
        video_processor=_RecoveryVideoProcessor(tmp_path),
        temp_dir=tmp_path,
    )
    model = _DecisionModel([
        RecoveryDecision("action", "inspect_failure", {}),
        RecoveryDecision("failed", message="站点仍在限流，停止本次恢复"),
    ])

    result = await MediaRecoveryCoordinator(model, actions).run(failure)

    assert result.status is RecoveryRunStatus.FAILED
    assert result.code == "model_stopped"
    assert result.observations[0].code == "failure_inspected"
    assert actions.verified_result(result.observations) is None


class _CandidateRuntime:
    available = True

    def __init__(self):
        self.payloads = []

    async def verify_boundary(self):
        return True

    async def run(self, _source, payload):
        self.payloads.append(payload)
        assert "media_url" in payload["body"]
        return CandidateParserResult(
            kind=CandidateResultKind.CANDIDATES,
            candidates=(
                CandidateResource(
                    url="https://upos-sz-mirrorcos.bilivideo.com/audio/scenario.m4a",
                    resource_type="media",
                ),
            ),
            diagnostic="新版 playurl 结构已解析",
        )


class _ResponseHeaders:
    @staticmethod
    def get_content_type():
        return "application/json"


class _LocalResponse:
    status = 200
    headers = _ResponseHeaders()

    def __init__(self, body):
        self.body = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self.body.read(size)


class _LocalOpener:
    def open(self, request, timeout=0):
        assert timeout > 0
        if "bilivideo.com" in request.full_url:
            return _LocalResponse(b"local fake bilibili media")
        return _LocalResponse(
            b'{"data":{"dash":{"audio":[{"baseUrl":"changed"}]}},'
            b'"media_url":"https://upos-sz-mirrorcos.bilivideo.com/audio/scenario.m4a"}'
        )


async def test_bilibili_structure_change_completes_candidate_chain_without_network(tmp_path, monkeypatch):
    failure = _failure(
        ExtractionFailureKind.MEDIA_DOWNLOAD_FAILED,
        platform="bilibili",
        summary="playurl JSON structure changed",
    )
    actions = MediaRecoveryActions(
        source_url="https://www.bilibili.com/video/BV1scenario",
        failure=failure,
        video_processor=_RecoveryVideoProcessor(tmp_path),
        temp_dir=tmp_path,
    )
    runtime = _CandidateRuntime()
    actions._candidate_runtime = runtime
    monkeypatch.setattr(
        "media_recovery_actions.urllib.request.build_opener",
        lambda *_args: _LocalOpener(),
    )
    monkeypatch.setattr("media_recovery_actions.probe_duration", lambda _path: 42.0)

    response = await actions.execute(RecoveryAction.HTTP_REQUEST, {
        "method": "GET",
        "path": "https://api.bilibili.com/x/player/playurl?cid=1",
    })
    parsed = await actions.execute(RecoveryAction.RUN_CANDIDATE_PARSER, {
        "response_id": "response_1",
        "source": "const result = parseChangedPlayurl(input);",
    })
    downloaded = await actions.execute(RecoveryAction.DOWNLOAD_CANDIDATE, {
        "candidate_id": "candidate_2",
    })
    validated = await actions.execute(RecoveryAction.VALIDATE_MEDIA, {})
    observations = (response, parsed, downloaded, validated)

    assert [item.code for item in observations] == [
        "http_response",
        "candidate_resources",
        "candidate_downloaded",
        "media_valid",
    ]
    result = actions.verified_result(observations)
    assert result is not None
    assert result.status is RecoveryRunStatus.RECOVERED
    assert len(runtime.payloads) == 1


@pytest.mark.parametrize(
    ("raw_error", "expected_kind"),
    [
        ("DRM protected encrypted stream", ExtractionFailureKind.DRM_PROTECTED),
        ("This video is members-only", ExtractionFailureKind.PERMISSION_DENIED),
        ("This video is private", ExtractionFailureKind.PERMISSION_DENIED),
    ],
)
async def test_drm_membership_and_private_sources_cannot_be_declared_successful(
    tmp_path,
    raw_error,
    expected_kind,
):
    kind = classify_extraction_failure(raw_error, ExtractionStage.MEDIA_DOWNLOAD)
    assert kind is expected_kind
    failure = _failure(kind, summary=raw_error)
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=restricted",
        failure=failure,
        video_processor=_RecoveryVideoProcessor(tmp_path),
        temp_dir=tmp_path,
    )
    actions._http_bodies["response_1"] = b"{}"

    observation = await actions.execute(RecoveryAction.RUN_CANDIDATE_PARSER, {
        "response_id": "response_1",
        "source": "console.log('{}')",
    })

    assert observation.status is ObservationStatus.FAILURE
    assert observation.code == "access_control_not_parseable"
    assert actions.verified_result((observation,)) is None
    with pytest.raises(ValueError, match="host-verified artifact"):
        RecoveryResult(
            status=RecoveryRunStatus.RECOVERED,
            code="model_claimed_success",
            message="模型声称成功",
        )


async def test_repeated_hallucination_triggers_exactly_one_local_retry(tmp_path, monkeypatch):
    audio = tmp_path / "repeated-hallucination.wav"
    audio.touch()
    profile = _complete_profile(silence_ratio=1 / 3)
    strategy = select_transcription_strategy(profile, model_id="base")
    assert strategy.max_segment_retries == 1
    transcriber = Transcriber(model_size="base", model_path="local")
    retry_decodes = []

    async def _initial(_path, **kwargs):
        segments = [
            {"start": 10, "end": 11, "text": "谢谢观看"},
            {"start": 12, "end": 13, "text": "谢谢观看"},
            {"start": 14, "end": 15, "text": "谢谢观看"},
            {"start": 16, "end": 17, "text": "谢谢观看"},
        ]
        kwargs["_segments_callback"]("zh", segments)
        kwargs["_speech_ranges_callback"]([(10, 18)])
        return transcriber._assemble_markdown("zh", segments)

    def _decode(*args):
        retry_decodes.append(args)
        return np.full(16_000, 0.1, dtype=np.float32)

    async def _run(_fn, *_args):
        return {
            "language": "zh",
            "segments": [{"start": 0, "end": 8, "text": "这是实际语句"}],
        }

    monkeypatch.setattr(transcriber, "transcribe", _initial)
    monkeypatch.setattr(transcriber_module, "decode_audio_chunk", _decode)
    monkeypatch.setattr(transcriber_module, "_run_on_mlx_thread", _run)

    outcome = await transcriber.transcribe_with_quality(
        str(audio),
        audio_profile=profile,
        strategy=strategy,
    )

    assert len(retry_decodes) == 1
    assert len(outcome.quality_report.retry_records) == 1
    assert outcome.quality_report.retry_records[0].selected is FinalTranscriptSelection.RETRY
    assert "这是实际语句" in outcome.transcript


async def test_task_recovery_output_sanitizes_dynamic_progress_and_result_text(monkeypatch, tmp_path):
    raw = (
        "Cookie: session=top-secret; API Key=sk-1234567890 "
        "https://example.com/private/video?id=hidden-token\x00"
    )
    updates = []

    async def _update_task(task_id, **fields):
        updates.append((task_id, fields))
        return True

    async def _recover(*, source_url, failure, temp_dir, set_user_message):
        assert source_url.endswith("public")
        assert failure.kind is ExtractionFailureKind.RATE_LIMITED
        assert temp_dir == pipeline.TEMP_DIR
        await set_user_message(raw)
        return RecoveryResult(
            status=RecoveryRunStatus.FAILED,
            code="safe_stop",
            message=raw,
            observations=(
                RecoveryObservation(
                    action=RecoveryAction.INSPECT_FAILURE,
                    status=ObservationStatus.FAILURE,
                    code="safe_stop",
                    sanitized_summary=raw,
                ),
            ),
        )

    monkeypatch.setattr(pipeline, "_update_task", _update_task)
    monkeypatch.setattr(pipeline.media_recovery, "recover", _recover)
    recover = pipeline._extract_callbacks("task-sensitive")["recover_media"]

    await recover(
        "https://www.youtube.com/watch?v=public",
        _failure(ExtractionFailureKind.RATE_LIMITED),
    )

    task_output = repr(updates)
    assert "top-secret" not in task_output
    assert "sk-1234567890" not in task_output
    assert "private/video" not in task_output
    assert "hidden-token" not in task_output
    assert "\x00" not in task_output
    assert "[REDACTED" in task_output or "[redacted]" in task_output
