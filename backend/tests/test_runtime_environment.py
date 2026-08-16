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


def test_media_action_specs_are_complete_model_instructions(tmp_path):
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

    specs = actions.action_specs()
    assert len(specs) == 13
    assert {spec["name"] for spec in specs} == {action.value for action in RecoveryAction}
    assert all(spec["description"].strip() for spec in specs)
    assert all(spec["capability"] in {"read", "mutate"} for spec in specs)
    assert all(isinstance(spec["timeout_sec"], int) and spec["timeout_sec"] > 0 for spec in specs)
    assert {spec["name"] for spec in specs if spec["capability"] == "read"} == {
        "inspect_failure",
        "inspect_runtime",
    }
    ask_user = next(spec for spec in specs if spec["name"] == "ask_user")
    assert "copy_sanitized_diagnostic" not in ask_user["arguments"]["action_code"]


def test_runtime_observation_includes_whisper_source(monkeypatch):
    snapshot = {
        "ffmpeg": {"available": True},
        "ffprobe": {"available": True},
        "deno": {"available": True},
        "mlx": {"available": True},
        "yt_dlp": {
            "current_version": "2026.07.04",
            "status": "ready",
            "pending_restart": True,
        },
        "whisper": {
            "status": "retrying",
            "ready": False,
            "endpoint": "https://hf-mirror.com",
            "tried_endpoints": ["official", "https://hf-mirror.com"],
            "error": "Connection timed out",
        },
    }
    summary = runtime_observation_summary(snapshot)
    assert "whisper_status=retrying" in summary
    assert "whisper_endpoint=hf-mirror.com" in summary
    assert "whisper_tried=official,hf-mirror.com" in summary
    assert "whisper_error=Connection timed out" in summary
    assert "yt_dlp_version=2026.07.04" in summary
    assert "yt_dlp_pending_restart=True" in summary
    assert "ffmpeg=True" in summary
    assert "ffprobe=True" in summary
    assert "deno=True" in summary
    assert "mlx=True" in summary


def test_runtime_observation_is_sanitized_and_bounded():
    snapshot = {
        "ffmpeg": {"available": False, "path": "/Users/alice/private/ffmpeg"},
        "ffprobe": {"available": False},
        "deno": {"available": False},
        "mlx": {"available": False},
        "yt_dlp": {"current_version": "2026.07.04", "status": "failed"},
        "whisper": {
            "status": "degraded",
            "ready": False,
            "endpoint": "https://mirror.example.com/private/path?token=secret-value",
            "tried_endpoints": [
                "official",
                "https://mirror.example.com/private/path?token=secret-value",
            ],
            "error": "Cookie: session-secret\nnetwork failed /Users/alice/private/model " + "network failed " * 200,
        },
    }

    summary = runtime_observation_summary(snapshot)

    assert "whisper_status=degraded" in summary
    assert "whisper_endpoint=mirror.example.com" in summary
    assert "whisper_tried=official,mirror.example.com" in summary
    assert "network failed" in summary
    assert "session-secret" not in summary
    assert "/Users/alice" not in summary
    assert "private/path" not in summary
    assert "secret-value" not in summary
    assert len(summary) <= 1_200


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
            "ffmpeg=True; deno=True; mlx=True; whisper_status=retrying; "
            "whisper_endpoint=hf-mirror.com; "
            "whisper_tried=official,hf-mirror.com"
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
    assert "whisper_endpoint=hf-mirror.com" in observation.sanitized_summary
    assert "whisper_tried=official,hf-mirror.com" in observation.sanitized_summary
