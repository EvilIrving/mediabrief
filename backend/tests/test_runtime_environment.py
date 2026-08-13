from __future__ import annotations

from media_contracts import (
    ExtractionFailure,
    ExtractionFailureKind,
    ExtractionStage,
    RecoveryAction,
)
from media_recovery_actions import MediaRecoveryActions
from runtime_environment import collect_runtime_environment, runtime_observation_summary


class _FakeVideoProcessor:
    def recovery_profile_names(self, _url):
        return ("metadata", "subtitles", "audio")

    def browser_session_available(self):
        return False


def test_runtime_observation_includes_whisper_source(monkeypatch):
    snapshot = {
        "ffmpeg": {"available": True},
        "ffprobe": {"available": True},
        "deno": {"available": True},
        "mlx": {"available": True},
        "yt_dlp": {"current_version": "2026.07.04", "status": "ready"},
        "whisper": {
            "status": "retrying",
            "ready": False,
            "endpoint": "https://hf-mirror.com",
            "tried_endpoints": ["official", "https://hf-mirror.com"],
            "error": "Connection timed out",
        },
    }
    summary = runtime_observation_summary(snapshot)
    assert "whisper_endpoint=https://hf-mirror.com" in summary
    assert "whisper_tried=official,https://hf-mirror.com" in summary
    assert "whisper_error=Connection timed out" in summary
    assert "deno=True" in summary
    assert "mlx=True" in summary


def test_collect_runtime_environment_has_required_components():
    snapshot = collect_runtime_environment()
    for key in ("ffmpeg", "ffprobe", "deno", "mlx", "yt_dlp", "whisper"):
        assert key in snapshot
    assert "ready" in snapshot["whisper"]
    assert "endpoint" in snapshot["whisper"]
    assert "tried_endpoints" in snapshot["whisper"]


async def test_inspect_runtime_exposes_environment_to_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "media_recovery_actions.runtime_observation_summary",
        lambda: (
            "ffmpeg=True; deno=True; mlx=True; whisper=retrying; "
            "whisper_endpoint=https://hf-mirror.com; "
            "whisper_tried=official,https://hf-mirror.com"
        ),
    )
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=test",
        failure=ExtractionFailure(
            platform="youtube",
            stage=ExtractionStage.MEDIA_DOWNLOAD,
            kind=ExtractionFailureKind.MEDIA_DOWNLOAD_FAILED,
            sanitized_summary="download failed",
            deno_available=True,
            ejs_available=True,
        ),
        video_processor=_FakeVideoProcessor(),
        temp_dir=tmp_path,
    )
    observation = await actions.execute(RecoveryAction.INSPECT_RUNTIME, {})
    assert observation.code == "runtime_inspected"
    assert "whisper_endpoint=https://hf-mirror.com" in observation.sanitized_summary
    assert "whisper_tried=official,https://hf-mirror.com" in observation.sanitized_summary
