from format_curator import (
    TOOL_ID,
    collapse_formats,
    execute,
    format_label,
    one_per_height,
    present_download_list,
    tool_spec,
)


def test_tool_spec_names_present_download_list():
    spec = tool_spec()
    assert spec["name"] == TOOL_ID == "present_download_list"
    assert "video_formats" in spec["arguments"]
    assert "audio_formats" in spec["arguments"]


def test_execute_turns_detect_catalog_into_parseable_payload():
    payload = execute({
        "video_formats": [
            {"id": "bestvideo+bestaudio/best"},
            {"id": "a", "height": 1080, "fps": 24, "ext": "mp4", "vcodec": "avc1", "filesize": 80},
            {"id": "b", "height": 1080, "fps": 24, "ext": "mp4", "vcodec": "av01", "filesize": 40},
            {"id": "c", "height": 720, "fps": 24, "ext": "mp4", "vcodec": "avc1", "filesize": 20},
            {"id": "d", "height": 480, "fps": 24, "ext": "mp4", "vcodec": "av01", "filesize": 10},
        ],
        "audio_formats": [
            {"id": "bestaudio/best", "ext": "m4a"},
            {"id": "251", "ext": "webm", "acodec": "opus", "abr": 118.4, "filesize": 10_400_000},
            {"id": "251-drc", "ext": "webm", "acodec": "opus", "abr": 117.6, "filesize": 10_400_000},
            {"id": "140", "ext": "m4a", "acodec": "mp4a.40.2", "abr": 129.1, "filesize": 11_400_000},
        ],
    })
    assert list(payload) == ["video", "audio"]
    assert [item["id"] for item in payload["video"]] == ["bestvideo+bestaudio/best", "b", "c"]
    assert payload["video"][1]["label"] == "1080p mp4 24fps av1"
    assert [item["id"] for item in payload["audio"]] == ["bestaudio/best", "251", "140"]
    assert payload["audio"][2]["label"] == "m4a 129kbps aac"


def test_present_download_list_matches_execute():
    args = {"video_formats": [{"id": "bestvideo+bestaudio/best"}], "audio_formats": []}
    assert present_download_list(**args) == execute(args)


def test_collapse_drops_audio_rows_that_look_the_same():
    rows = collapse_formats(
        [
            {"id": "bestaudio/best", "ext": "m4a"},
            {"id": "251", "ext": "webm", "acodec": "opus", "abr": 118.4, "filesize": 10_400_000},
            {"id": "251-drc", "ext": "webm", "acodec": "opus", "abr": 117.6, "filesize": 10_400_000},
            {"id": "250", "ext": "webm", "acodec": "opus", "abr": 63.2, "filesize": 5_500_000},
            {"id": "140", "ext": "m4a", "acodec": "mp4a.40.2", "abr": 129.1, "filesize": 11_400_000},
        ],
        "audio",
    )
    assert [item["label"] for item in rows if item["label"]] == [
        "webm 118kbps opus",
        "webm 63kbps opus",
        "m4a 129kbps aac",
    ]


def test_format_label_skips_missing_fields():
    assert format_label({"id": "18", "height": 360, "ext": "mp4", "vcodec": "avc1"}, "video") == "360p mp4 h264"
    assert format_label({"id": "bestvideo+bestaudio/best"}, "video") == ""


def test_one_per_height_keeps_smallest_1080_and_720():
    rows = one_per_height(
        [
            {"id": "bestvideo+bestaudio/best"},
            {"id": "h264", "height": 1080, "fps": 24, "ext": "mp4", "vcodec": "avc1", "filesize": 80},
            {"id": "vp9", "height": 1080, "fps": 24, "ext": "webm", "vcodec": "vp9", "filesize": 50},
            {"id": "av1", "height": 1080, "fps": 24, "ext": "mp4", "vcodec": "av01", "filesize": 40},
            {"id": "720-h264", "height": 720, "fps": 24, "ext": "mp4", "vcodec": "avc1", "filesize": 30},
            {"id": "720-vp9", "height": 720, "fps": 24, "ext": "webm", "vcodec": "vp9", "filesize": 20},
        ]
    )
    assert [item["id"] for item in rows] == ["bestvideo+bestaudio/best", "av1", "720-vp9"]
