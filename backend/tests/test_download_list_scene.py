from download_list_scene import run_download_list_scene
from format_curator import TOOL_ID, execute
from media_recovery import RecoveryDecision, RecoveryDecisionKind


class _FakeModel:
    def __init__(self, decision: RecoveryDecision):
        self.decision = decision
        self.seen_actions = None
        self.seen_messages = None

    async def decide(self, messages, available_actions, *, system_prompt, max_output_chars):
        self.seen_actions = list(available_actions)
        self.seen_messages = list(messages)
        return self.decision


CATALOG = {
    "video_formats": [
        {"id": "bestvideo+bestaudio/best"},
        {"id": "a", "height": 1080, "fps": 24, "ext": "mp4", "vcodec": "avc1", "filesize": 80},
        {"id": "b", "height": 1080, "fps": 24, "ext": "mp4", "vcodec": "av01", "filesize": 40},
        {"id": "c", "height": 720, "fps": 24, "ext": "mp4", "vcodec": "avc1", "filesize": 20},
    ],
    "audio_formats": [
        {"id": "bestaudio/best"},
        {"id": "140", "ext": "m4a", "acodec": "mp4a.40.2", "abr": 129},
    ],
}


async def test_no_model_uses_host_tool():
    payload = await run_download_list_scene(CATALOG, model=None)
    assert payload == execute(CATALOG)
    assert [item["id"] for item in payload["video"]] == ["bestvideo+bestaudio/best", "b", "c"]


async def test_model_selects_tool_and_passes_detect_catalog():
    model = _FakeModel(RecoveryDecision(
        kind=RecoveryDecisionKind.ACTION,
        action=TOOL_ID,
        arguments=CATALOG,
    ))
    payload = await run_download_list_scene(CATALOG, model=model)
    assert model.seen_actions[0]["name"] == TOOL_ID
    assert "detect" in model.seen_messages[0]["content"]
    assert payload == execute(CATALOG)


async def test_model_empty_arguments_pass_through_detect_catalog():
    model = _FakeModel(RecoveryDecision(
        kind=RecoveryDecisionKind.ACTION,
        action=TOOL_ID,
        arguments={},
    ))
    payload = await run_download_list_scene(CATALOG, model=model)
    assert payload == execute(CATALOG)


async def test_unknown_action_falls_back_to_host_tool():
    model = _FakeModel(RecoveryDecision(
        kind=RecoveryDecisionKind.ACTION,
        action=TOOL_ID,
        arguments={"video_formats": [CATALOG["video_formats"][0]], "audio_formats": []},
    ))
    subset = await run_download_list_scene(CATALOG, model=model)
    assert [item["id"] for item in subset["video"]] == ["bestvideo+bestaudio/best"]

    model = _FakeModel(RecoveryDecision(
        kind=RecoveryDecisionKind.COMPLETED,
        message="done",
    ))
    payload = await run_download_list_scene(CATALOG, model=model)
    assert payload == execute(CATALOG)


class _BoomModel:
    async def decide(self, *args, **kwargs):
        raise RuntimeError("nope")


async def test_model_error_falls_back_to_host_tool():
    payload = await run_download_list_scene(CATALOG, model=_BoomModel())
    assert payload == execute(CATALOG)
