import pytest

import task_store


async def _capture_stage_update(monkeypatch, task, stage, stage_progress):
    updates = []

    async def get_task(task_id):
        assert task_id == "download-task"
        return task

    async def update_task(task_id, **fields):
        updates.append((task_id, fields))
        return True

    monkeypatch.setattr(task_store, "_db_get_task", get_task)
    monkeypatch.setattr(task_store, "update_task", update_task)

    await task_store.set_task_stage("download-task", stage, stage_progress)
    return updates


@pytest.mark.parametrize(
    ("stage", "stage_progress", "expected_total"),
    [
        ("identify_resource", 50, 5.0),
        ("identify_resource", 100, 10.0),
        ("download", 10, 19.0),
        ("download", 800 / 9, 90.0),
        ("download", 100, 100.0),
    ],
)
async def test_set_download_task_stage_uses_download_weights(
    monkeypatch,
    stage,
    stage_progress,
    expected_total,
):
    task = {
        "stages": [
            {"name": "identify_resource"},
            {"name": "download"},
        ],
        "skipped_stages": [],
        "task_type": "download_only",
    }

    updates = await _capture_stage_update(monkeypatch, task, stage, stage_progress)

    assert updates == [
        (
            "download-task",
            {
                "current_stage": stage,
                "current_stage_index": 0 if stage == "identify_resource" else 1,
                "progress": expected_total,
            },
        )
    ]


async def test_set_task_stage_keeps_equal_weights_for_other_task_types(monkeypatch):
    task = {
        "stages": [{"name": "first"}, {"name": "second"}],
        "skipped_stages": [],
        "task_type": "local_text",
    }

    updates = await _capture_stage_update(monkeypatch, task, "second", 10)

    assert updates[0][1]["progress"] == 55.0


@pytest.mark.parametrize(("stage_progress", "expected_total"), [(-10, 10.0), (120, 100.0)])
async def test_set_task_stage_clamps_stage_progress(
    monkeypatch,
    stage_progress,
    expected_total,
):
    task = {
        "stages": [{"name": "identify_resource"}, {"name": "download"}],
        "skipped_stages": [],
        "task_type": "download_only",
    }

    updates = await _capture_stage_update(monkeypatch, task, "download", stage_progress)

    assert updates[0][1]["progress"] == expected_total
