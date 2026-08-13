"""媒体恢复固定用户动作 HTTP 边界。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from media_recovery import UserActionCode
from recovery_user_actions import (
    RecoveryActionConflict,
    RecoveryTaskNotFound,
    apply_recovery_user_action,
)

router = APIRouter()


class RecoveryActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_code: UserActionCode


@router.post("/api/task/{task_id}/recovery-action")
async def recovery_action(task_id: str, body: RecoveryActionBody):
    try:
        return await apply_recovery_user_action(task_id, body.action_code)
    except RecoveryTaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecoveryActionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
