from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import recovery_user_actions as user_actions
import db
from media_contracts import (
    ExtractionFailure,
    ExtractionFailureKind,
    ExtractionStage,
    RecoveryAction,
    sanitize_plain_text,
)
from media_recovery import UserActionCode, allowed_recovery_user_actions
from media_recovery_actions import MediaRecoveryActions
from routers import recovery as recovery_router


def _pending_task(action: UserActionCode) -> dict:
    return {
        "task_id": "task-1",
        "status": "error",
        "error": "needs action",
        "error_code": "recovery_action_required",
        "error_message": "needs action",
        "message": "error.recovery_action_required",
        "recovery_status": "action_required",
        "recovery_action_state": "pending",
        "recovery_user_action": action.value,
        "recovery_message": "needs action",
        "recovery_observations": [],
    }


def _install_state(monkeypatch, task: dict, *, queue_result=None):
    updates = []
    requeues = []
    removals = []

    async def get_task(task_id):
        return task if task_id == task["task_id"] else None

    async def update_task(task_id, fields):
        assert task_id == task["task_id"]
        task.update(fields)
        updates.append(dict(fields))
        return True

    async def requeue(queue_name, task_id, *, browser_session=None):
        requeues.append((queue_name, task_id, browser_session))
        return queue_result or {"id": "queue-new", "status": "queued"}

    async def remove(queue_name, task_id):
        removals.append((queue_name, task_id))
        return 1

    async def broadcast(task_id):
        assert task_id == task["task_id"]

    monkeypatch.setattr(user_actions, "_ACTION_LOCK", asyncio.Lock())
    monkeypatch.setattr(user_actions, "_db_get_task", get_task)
    monkeypatch.setattr(user_actions, "_db_update_task", update_task)
    monkeypatch.setattr(user_actions.queue_manager, "requeue_recovery_task", requeue)
    monkeypatch.setattr(user_actions.queue_manager, "remove_task_by_id", remove)
    monkeypatch.setattr(user_actions, "broadcast_task_update", broadcast)
    return updates, requeues, removals


def test_user_action_codes_are_the_fixed_product_boundary():
    assert {item.value for item in UserActionCode} == {
        "enable_browser_session",
        "login_then_retry",
        "requeue_continue",
        "abort",
        "copy_sanitized_diagnostic",
    }


def test_plain_text_and_copied_diagnostic_strip_markup_secrets_and_controls():
    raw = "<script>steal()</script><b>说明</b>\x00 Cookie: secret https://example.com/a?q=1"
    safe = sanitize_plain_text(raw, max_length=120)
    assert "<" not in safe and ">" not in safe
    assert "steal" not in safe
    assert "secret" not in safe
    assert "?q=1" not in safe
    assert "\x00" not in safe

    task = _pending_task(UserActionCode.LOGIN_THEN_RETRY)
    task["recovery_message"] = raw
    task["recovery_observations"] = [{
        "action": "inspect_failure",
        "status": "failure",
        "code": "auth_required",
        "summary": raw * 100,
    }]
    diagnostic = user_actions.build_sanitized_recovery_diagnostic(task)
    assert len(diagnostic) <= 6_000
    assert "<" not in diagnostic and "secret" not in diagnostic and "?q=1" not in diagnostic


@pytest.mark.asyncio
async def test_allow_browser_session_requeues_saved_job_with_opaque_capability(monkeypatch):
    task = _pending_task(UserActionCode.ENABLE_BROWSER_SESSION)
    _, requeues, _ = _install_state(monkeypatch, task)

    result = await user_actions.apply_recovery_user_action(
        task["task_id"],
        UserActionCode.ENABLE_BROWSER_SESSION,
    )

    assert result["status"] == "requeued"
    assert result["queue_id"] == "queue-new"
    assert requeues == [("tasks", "task-1", True)]
    assert task["status"] == "queued"
    assert task["recovery_browser_session_granted"] is True
    assert task["recovery_user_action"] == ""


@pytest.mark.asyncio
async def test_continue_without_login_records_decline_and_never_requests_login_again(monkeypatch, tmp_path):
    task = _pending_task(UserActionCode.LOGIN_THEN_RETRY)
    _, requeues, _ = _install_state(monkeypatch, task)

    await user_actions.apply_recovery_user_action(
        task["task_id"],
        UserActionCode.REQUEUE_CONTINUE,
    )

    assert requeues == [("tasks", "task-1", False)]
    assert task["recovery_login_declined"] is True
    allowed = allowed_recovery_user_actions(login_declined=True)
    assert UserActionCode.LOGIN_THEN_RETRY not in allowed
    assert UserActionCode.ENABLE_BROWSER_SESSION not in allowed

    failure = ExtractionFailure(
        platform="youtube",
        stage=ExtractionStage.MEDIA_DOWNLOAD,
        kind=ExtractionFailureKind.AUTH_REQUIRED,
        sanitized_summary="login required",
    )
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=public",
        failure=failure,
        video_processor=object(),
        temp_dir=tmp_path,
        allowed_user_actions=allowed,
    )
    spec = next(item for item in actions.action_specs() if item["name"] == "ask_user")
    assert "login_then_retry" not in spec["arguments"]["action_code"]
    observation = await actions.execute(RecoveryAction.ASK_USER, {
        "action_code": "login_then_retry",
        "message": "ask again",
    })
    assert observation.code == "invalid_arguments"
    assert actions.pending_user_action() is None


@pytest.mark.asyncio
async def test_abort_consumes_login_request_without_requeue(monkeypatch):
    task = _pending_task(UserActionCode.LOGIN_THEN_RETRY)
    _, requeues, removals = _install_state(monkeypatch, task)

    result = await user_actions.apply_recovery_user_action(task["task_id"], UserActionCode.ABORT)

    assert result["status"] == "aborted"
    assert not requeues
    assert removals == [("tasks", "task-1")]
    assert task["recovery_status"] == "aborted"
    assert task["recovery_login_declined"] is True
    assert task["recovery_action_state"] == "aborted"


@pytest.mark.asyncio
async def test_consumed_action_cannot_enqueue_twice(monkeypatch):
    task = _pending_task(UserActionCode.REQUEUE_CONTINUE)
    _, requeues, _ = _install_state(monkeypatch, task)
    await user_actions.apply_recovery_user_action(task["task_id"], UserActionCode.REQUEUE_CONTINUE)

    with pytest.raises(user_actions.RecoveryActionConflict):
        await user_actions.apply_recovery_user_action(task["task_id"], UserActionCode.REQUEUE_CONTINUE)
    assert len(requeues) == 1


def test_http_boundary_rejects_unknown_actions_and_extra_payload(monkeypatch):
    async def fake_apply(task_id, action):
        return {"task_id": task_id, "action_code": action.value, "status": "requeued"}

    monkeypatch.setattr(recovery_router, "apply_recovery_user_action", fake_apply)
    app = FastAPI()
    app.include_router(recovery_router.router)
    client = TestClient(app)

    unknown = client.post("/api/task/task-1/recovery-action", json={"action_code": "run_shell"})
    assert unknown.status_code == 422
    extra = client.post("/api/task/task-1/recovery-action", json={
        "action_code": "requeue_continue",
        "payload": {"item_type": "shell"},
    })
    assert extra.status_code == 422
    valid = client.post("/api/task/task-1/recovery-action", json={"action_code": "requeue_continue"})
    assert valid.status_code == 200
    assert valid.json()["action_code"] == "requeue_continue"


@pytest.mark.asyncio
async def test_queue_recovery_reuses_only_host_saved_media_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_db_path", tmp_path / "actions.db")
    monkeypatch.setattr(db, "_schema_ready", False)
    await db.init_db()
    await db.create_task("task-safe", {"status": "error"})
    old = await db.queue_enqueue("tasks", "process_video", "original", {
        "task_id": "task-safe",
        "url": "https://example.com/watch?v=1",
        "api_key": "stored-only-secret",
        "auto_detect_browser_cookies": False,
    })

    result = await db.queue_requeue_recovery_task(
        "tasks",
        "task-safe",
        browser_session=True,
    )

    assert result is not None and result["id"] != old["id"]
    assert "payload" not in result and "stored-only-secret" not in str(result)
    stored = await db.queue_get_item_payload(result["id"])
    assert stored["item_type"] == "process_video"
    assert stored["payload"]["api_key"] == "stored-only-secret"
    assert stored["payload"]["auto_detect_browser_cookies"] is True

    await db.create_task("task-blocked", {"status": "error"})
    await db.queue_enqueue("tasks", "download_video", "download", {
        "task_id": "task-blocked",
        "url": "https://example.com/video",
    })
    assert await db.queue_requeue_recovery_task("tasks", "task-blocked") is None
