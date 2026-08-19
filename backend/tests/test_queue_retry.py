"""队列 Retry：清掉上一轮 error，避免前端继续显示重试按钮并 409。"""
from __future__ import annotations

import pytest

import db
from task_queue import TaskQueueManager


@pytest.mark.asyncio
async def test_retry_failed_item_resets_task_and_requeues(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_db_path", tmp_path / "retry.db")
    monkeypatch.setattr(db, "_schema_ready", False)
    await db.init_db()

    await db.create_task("task-1", {
        "status": "error",
        "error": "download failed",
        "error_code": "media_download_failed",
        "progress": 40,
    })
    old = await db.queue_enqueue("tasks", "process_video", "process_video:http://x", {
        "task_id": "task-1",
        "url": "http://x",
    })
    await db.queue_set_error(old["id"], "download failed")

    qm = TaskQueueManager()
    result = await qm.retry_failed_item("tasks", old["id"])

    assert result["id"] != old["id"]
    assert result["status"] == "queued"
    assert await db.queue_get_item(old["id"]) is None
    task = await db.get_task("task-1")
    assert task["status"] == "queued"
    assert task.get("error") in ("", None)
    stored = await db.queue_get_item_payload(result["id"])
    assert stored["item_type"] == "process_video"
    assert stored["payload"]["url"] == "http://x"


@pytest.mark.asyncio
async def test_retry_failed_item_rejects_non_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_db_path", tmp_path / "retry.db")
    monkeypatch.setattr(db, "_schema_ready", False)
    await db.init_db()
    queued = await db.queue_enqueue("tasks", "process_video", "k", {"task_id": "t"})
    qm = TaskQueueManager()
    with pytest.raises(ValueError):
        await qm.retry_failed_item("tasks", queued["id"])
