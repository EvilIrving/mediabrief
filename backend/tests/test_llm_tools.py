from media_contracts import (
    ExtractionFailure,
    ExtractionFailureKind,
    ExtractionStage,
    RecoveryAction,
)
from format_curator import tool_spec
from llm_tools import spec_to_function_tool
from media_recovery_actions import MediaRecoveryActions


class _FakeVideoProcessor:
    def recovery_profile_names(self, _url):
        return ("metadata", "subtitles", "audio")

    def browser_session_available(self):
        return False


def _assert_official_function(tool: dict):
    assert tool["type"] == "function"
    assert tool["name"]
    assert tool["description"]
    params = tool["parameters"]
    assert params["type"] == "object"
    assert isinstance(params.get("properties"), dict)
    assert params.get("additionalProperties") is False
    for key in params.get("required") or []:
        assert key in params["properties"]
    assert "function" not in tool
    assert "arguments" not in tool
    assert "capability" not in tool
    assert "timeout_sec" not in tool


def test_all_recovery_source_specs_are_official_functions(tmp_path):
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=test",
        failure=ExtractionFailure(
            platform="youtube",
            stage=ExtractionStage.MEDIA_DOWNLOAD,
            kind=ExtractionFailureKind.MEDIA_DOWNLOAD_FAILED,
            sanitized_summary="download failed",
        ),
        video_processor=_FakeVideoProcessor(),
        temp_dir=tmp_path,
    )
    specs = list(actions.action_specs())
    assert {spec["name"] for spec in specs} == {item.value for item in RecoveryAction}
    for spec in specs:
        assert spec["type"] == "function"
        assert spec["capability"] in {"read", "mutate"}
        assert spec["timeout_sec"] > 0
        _assert_official_function(spec_to_function_tool(spec))


def test_http_request_does_not_require_path_and_proposal_together(tmp_path):
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=test",
        failure=ExtractionFailure(
            platform="youtube",
            stage=ExtractionStage.MEDIA_DOWNLOAD,
            kind=ExtractionFailureKind.MEDIA_DOWNLOAD_FAILED,
            sanitized_summary="download failed",
        ),
        video_processor=_FakeVideoProcessor(),
        temp_dir=tmp_path,
    )
    spec = next(item for item in actions.action_specs() if item["name"] == "http_request")
    required = spec["parameters"].get("required") or []
    assert "path" not in required
    assert "proposal_id" not in required
    assert set(spec["parameters"]["properties"]) == {"method", "path", "proposal_id"}


def test_download_list_tool_is_official_function():
    spec = tool_spec()
    assert spec["type"] == "function"
    sent = spec_to_function_tool(spec)
    _assert_official_function(sent)
    assert sent["name"] == "present_download_list"
    assert set(sent["parameters"]["required"]) == {"video_formats", "audio_formats"}
