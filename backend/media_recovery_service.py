"""把单次恢复所需的模型、宿主动作和任务上下文装配起来。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from media_contracts import ExtractionFailure
from media_recovery import (
    MediaRecoveryCoordinator,
    OpenAICompatibleRecoveryModel,
    RecoveryBudget,
    RecoveryModel,
    RecoveryResult,
    UserActionCode,
)
from media_recovery_actions import MediaRecoveryActions


class MediaRecoveryService:
    def __init__(
        self,
        *,
        model: Optional[RecoveryModel],
        video_processor,
        budget: RecoveryBudget = RecoveryBudget(),
    ):
        self._model = model
        self._video_processor = video_processor
        self._budget = budget

    async def recover(
        self,
        *,
        source_url: str,
        failure: ExtractionFailure,
        temp_dir: Path,
        model: Optional[RecoveryModel] = None,
        set_user_message: Optional[Callable[[str], Any]] = None,
        allowed_user_actions: Optional[set[UserActionCode]] = None,
    ) -> RecoveryResult:
        actions = MediaRecoveryActions(
            source_url=source_url,
            failure=failure,
            video_processor=self._video_processor,
            temp_dir=temp_dir,
            set_user_message=set_user_message,
            allowed_user_actions=allowed_user_actions,
        )
        effective_model = model if model is not None else self._model
        coordinator = MediaRecoveryCoordinator(effective_model, actions, budget=self._budget)
        return await coordinator.run(failure)


def build_recovery_model(*, api_key: str, base_url: str, model: str):
    if not (api_key or "").strip() or not (model or "").strip():
        return None
    return OpenAICompatibleRecoveryModel(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
