"""上传原件必须留到任务成功或用户删除，失败重试才能找到文件。"""
from pathlib import Path

import pytest

import db
from task_store import discard_managed_upload


def test_discard_managed_upload_only_touches_temp_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr("task_store.TEMP_DIR", tmp_path)
    owned = tmp_path / "upload_abc123.m4a"
    owned.write_bytes(b"x")
    outsider = tmp_path / "notes.txt"
    outsider.write_bytes(b"y")
    other_dir = tmp_path.parent / "elsewhere_upload_x.m4a"
    other_dir.write_bytes(b"z")

    discard_managed_upload(owned)
    discard_managed_upload(outsider)
    discard_managed_upload(other_dir)

    assert owned.exists() is False
    assert outsider.exists() is True
    assert other_dir.exists() is True


@pytest.mark.asyncio
async def test_task_record_keeps_saved_path_for_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_db_path", tmp_path / "retry.db")
    monkeypatch.setattr(db, "_schema_ready", False)
    await db.init_db()
    saved = tmp_path / "upload_deadbeef.wav"
    saved.write_bytes(b"RIFF")
    await db.create_task("task-file", {
        "status": "error",
        "source_type": "file",
        "source_value": "meeting.wav",
        "saved_path": str(saved),
        "original_name": "meeting.wav",
        "ext_lower": ".wav",
    })
    task = await db.get_task("task-file")
    assert Path(task["saved_path"]).is_file()
    assert task["original_name"] == "meeting.wav"
