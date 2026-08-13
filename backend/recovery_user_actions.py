"""恢复等待态的固定用户动作边界。"""
from __future__ import annotations

import asyncio
import json
from enum import Enum
from typing import Any

from db import get_task as _db_get_task, update_task as _db_update_task
from media_contracts import sanitize_plain_text
from media_recovery import RecoveryRunStatus, UserActionCode
from task_queue import queue_manager
from task_store import broadcast_task_update


class RecoveryUserActionError(Exception):
    pass


class RecoveryTaskNotFound(RecoveryUserActionError):
    pass


class RecoveryActionConflict(RecoveryUserActionError):
    pass


class RecoveryUserActionStatus(str, Enum):
    REQUEUED = "requeued"
    ABORTED = "aborted"
    DIAGNOSTIC = "diagnostic"


_ACTION_LOCK = asyncio.Lock()
_LOGIN_ACTIONS = {
    UserActionCode.ENABLE_BROWSER_SESSION,
    UserActionCode.LOGIN_THEN_RETRY,
}
_MAX_DIAGNOSTIC_CHARS = 6_000


def build_sanitized_recovery_diagnostic(task: dict[str, Any]) -> str:
    """只导出恢复现场的安全字段，永不包含 URL、队列 payload 或认证材料。"""
    continuation = task.get("recovery_continuation")
    if not isinstance(continuation, dict):
        continuation = {}
    raw_observations = task.get("recovery_observations")
    observations = []
    if isinstance(raw_observations, list):
        for item in raw_observations[:30]:
            if not isinstance(item, dict):
                continue
            observations.append({
                "action": sanitize_plain_text(item.get("action"), max_length=64),
                "status": sanitize_plain_text(item.get("status"), max_length=32),
                "code": sanitize_plain_text(item.get("code"), max_length=64),
                "summary": sanitize_plain_text(item.get("summary"), max_length=800),
            })
    diagnostic = {
        "recovery_status": sanitize_plain_text(task.get("recovery_status"), max_length=32),
        "recovery_code": sanitize_plain_text(task.get("recovery_code"), max_length=64),
        "message": sanitize_plain_text(task.get("recovery_message"), max_length=800),
        "requested_action": sanitize_plain_text(task.get("recovery_user_action"), max_length=64),
        "continuation": {
            "platform": sanitize_plain_text(continuation.get("platform"), max_length=64),
            "failure_kind": sanitize_plain_text(continuation.get("failure_kind"), max_length=64),
            "failure_stage": sanitize_plain_text(continuation.get("failure_stage"), max_length=64),
            "attempted_actions": [
                sanitize_plain_text(value, max_length=64)
                for value in (continuation.get("attempted_actions") or [])[:30]
            ],
        },
        "observations": observations,
    }
    return sanitize_plain_text(
        json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":")),
        max_length=_MAX_DIAGNOSTIC_CHARS,
    )


async def apply_recovery_user_action(task_id: str, action: UserActionCode) -> dict[str, Any]:
    """消费一次等待态动作；继续操作总是创建新队列项。"""
    if not isinstance(action, UserActionCode):
        action = UserActionCode(action)

    async with _ACTION_LOCK:
        task = await _db_get_task(task_id)
        if not task:
            raise RecoveryTaskNotFound("任务不存在")

        if action is UserActionCode.COPY_SANITIZED_DIAGNOSTIC:
            return {
                "task_id": task_id,
                "action_code": action.value,
                "status": RecoveryUserActionStatus.DIAGNOSTIC.value,
                "message": "已生成脱敏诊断。",
                "diagnostic": build_sanitized_recovery_diagnostic(task),
            }

        if task.get("recovery_status") != RecoveryRunStatus.ACTION_REQUIRED.value:
            raise RecoveryActionConflict("任务当前不等待恢复动作")
        try:
            requested = UserActionCode(task.get("recovery_user_action"))
        except (TypeError, ValueError) as exc:
            raise RecoveryActionConflict("任务缺少有效的待处理动作") from exc
        if task.get("recovery_action_state") not in (None, "", "pending"):
            raise RecoveryActionConflict("恢复动作已经处理")

        login_declined = bool(task.get("recovery_login_declined"))
        if action in _LOGIN_ACTIONS:
            if login_declined:
                raise RecoveryActionConflict("该任务已拒绝使用登录态")
            if action is not requested:
                raise RecoveryActionConflict("动作与任务请求不匹配")

        declined_now = requested in _LOGIN_ACTIONS and action in {
            UserActionCode.REQUEUE_CONTINUE,
            UserActionCode.ABORT,
        }
        login_declined = login_declined or declined_now

        if action is UserActionCode.ABORT:
            message = "用户已放弃本次媒体恢复。"
            await _db_update_task(task_id, {
                "status": "error",
                "error": message,
                "error_code": "recovery_aborted",
                "error_message": message,
                "message": "error.recovery_aborted",
                "current_stage": "",
                "recovery_status": "aborted",
                "recovery_action_state": "aborted",
                "recovery_requested_action": requested.value,
                "recovery_user_action": "",
                "recovery_last_user_action": action.value,
                "recovery_login_declined": login_declined,
                "recovery_browser_session_granted": (
                    False if declined_now else bool(task.get("recovery_browser_session_granted"))
                ),
                "recovery_message": message,
            })
            await queue_manager.remove_task_by_id("tasks", task_id)
            await broadcast_task_update(task_id)
            return {
                "task_id": task_id,
                "action_code": action.value,
                "status": RecoveryUserActionStatus.ABORTED.value,
                "message": message,
            }

        if action not in {
            UserActionCode.ENABLE_BROWSER_SESSION,
            UserActionCode.LOGIN_THEN_RETRY,
            UserActionCode.REQUEUE_CONTINUE,
        }:
            raise RecoveryActionConflict("不支持的恢复动作")

        browser_session: bool | None = None
        if action in _LOGIN_ACTIONS:
            browser_session = True
        elif declined_now:
            browser_session = False

        previous_fields = {
            "status": task.get("status", "error"),
            "progress": task.get("progress", 0),
            "error": task.get("error", ""),
            "error_code": task.get("error_code", "recovery_action_required"),
            "error_message": task.get("error_message", ""),
            "message": task.get("message", "error.recovery_action_required"),
            "current_stage": task.get("current_stage", ""),
            "recovery_status": task.get("recovery_status"),
            "recovery_action_state": task.get("recovery_action_state", "pending"),
            "recovery_user_action": requested.value,
            "recovery_requested_action": task.get("recovery_requested_action", requested.value),
            "recovery_last_user_action": task.get("recovery_last_user_action", ""),
            "recovery_login_declined": bool(task.get("recovery_login_declined")),
            "recovery_browser_session_granted": bool(task.get("recovery_browser_session_granted")),
            "recovery_message": task.get("recovery_message", ""),
        }
        await _db_update_task(task_id, {
            "status": "queued",
            "progress": 0,
            "error": "",
            "error_code": "",
            "error_message": "",
            "message": "task.queued",
            "current_stage": "",
            "recovery_status": "queued",
            "recovery_action_state": "accepted",
            "recovery_requested_action": requested.value,
            "recovery_user_action": "",
            "recovery_last_user_action": action.value,
            "recovery_login_declined": login_declined,
            "recovery_browser_session_granted": (
                False if declined_now else
                bool(task.get("recovery_browser_session_granted")) or action in _LOGIN_ACTIONS
            ),
            "recovery_message": "恢复任务已重新入队。",
        })
        result = await queue_manager.requeue_recovery_task(
            "tasks",
            task_id,
            browser_session=browser_session,
        )
        if not result:
            await _db_update_task(task_id, previous_fields)
            await broadcast_task_update(task_id)
            raise RecoveryActionConflict("原队列现场已不存在，无法继续")
        await broadcast_task_update(task_id)
        return {
            "task_id": task_id,
            "queue_id": result["id"],
            "action_code": action.value,
            "status": RecoveryUserActionStatus.REQUEUED.value,
            "message": "恢复任务已重新入队。",
        }
