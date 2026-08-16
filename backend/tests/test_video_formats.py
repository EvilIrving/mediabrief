from video_processor import _download_format_id


def test_download_format_id_merges_audio_for_video_only_dash():
    assert _download_format_id("401", False) == "401+bestaudio"
    assert _download_format_id("18", True) == "18"
    assert _download_format_id("bestvideo+bestaudio/best", False) == "bestvideo+bestaudio/best"
    assert _download_format_id("137+bestaudio", False) == "137+bestaudio"
