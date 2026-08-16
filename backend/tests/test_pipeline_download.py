from pathlib import Path

import pytest

import pipeline


async def test_download_task_streams_bytes_to_90_then_completes(monkeypatch, tmp_path):
    stage_updates = []
    task_updates = []
    finished = []
    output_path = tmp_path / "download.mp4"

    async def get_video_title(_url):
        return "Download"

    async def broadcast_stage(task_id, stage, progress, message=""):
        stage_updates.append((task_id, stage, progress, message))

    async def update_task(task_id, **fields):
        task_updates.append((task_id, fields))
        return True

    async def get_task(_task_id):
        return None

    async def do_download(video_title, progress_callback):
        assert video_title == "Download"
        await progress_callback(25)
        await progress_callback(100)
        await progress_callback(50)  # 重试或多轨切换不应让进度倒退
        output_path.write_bytes(b"media")
        return output_path, {}, "task.download_completed"

    monkeypatch.setattr(pipeline.video_processor, "get_video_title", get_video_title)
    monkeypatch.setattr(pipeline, "_broadcast_stage", broadcast_stage)
    monkeypatch.setattr(pipeline, "_update_task", update_task)
    monkeypatch.setattr(pipeline, "_db_get_task", get_task)
    monkeypatch.setattr(pipeline, "_finish_task", lambda task_id: finished.append(task_id))

    await pipeline.run_download_task(
        "download-task",
        "https://example.com/video",
        do_download,
    )

    assert stage_updates[:3] == [
        ("download-task", "identify_resource", 50, ""),
        ("download-task", "identify_resource", 100, ""),
        ("download-task", "download", 0, ""),
    ]
    assert stage_updates[3][1] == "download"
    assert stage_updates[3][2] == pytest.approx(25 * 8 / 9)
    assert stage_updates[4][1] == "download"
    assert stage_updates[4][2] == pytest.approx(100 * 8 / 9)
    assert stage_updates[5] == ("download-task", "download", 100, "")
    assert len(stage_updates) == 6
    assert task_updates[-1][1]["status"] == "completed"
    assert task_updates[-1][1]["progress"] == 100
    assert task_updates[-1][1]["output_path"] == str(Path(output_path))
    assert finished == ["download-task"]
