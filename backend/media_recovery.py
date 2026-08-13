"""受限媒体恢复 Loop：模型只选择闭集动作，宿主执行并验证结果。"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, Sequence

import cancellation
from cancellation import CancelledByUser
from media_contracts import (
    ExtractionFailure,
    ObservationStatus,
    RecoveryAction,
    RecoveryObservation,
    sanitize_diagnostic,
    sanitize_plain_text,
)

logger = logging.getLogger(__name__)


class RecoveryDecisionKind(str, Enum):
    ACTION = "action"
    COMPLETED = "completed"
    FAILED = "failed"


class RecoveryRunStatus(str, Enum):
    RECOVERED = "recovered"
    ACTION_REQUIRED = "action_required"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"


class UserActionCode(str, Enum):
    ENABLE_BROWSER_SESSION = "enable_browser_session"
    LOGIN_THEN_RETRY = "login_then_retry"
    REQUEUE_CONTINUE = "requeue_continue"
    ABORT = "abort"
    COPY_SANITIZED_DIAGNOSTIC = "copy_sanitized_diagnostic"


REQUESTABLE_USER_ACTION_CODES = frozenset({
    UserActionCode.ENABLE_BROWSER_SESSION,
    UserActionCode.LOGIN_THEN_RETRY,
    UserActionCode.REQUEUE_CONTINUE,
    UserActionCode.ABORT,
})


def allowed_recovery_user_actions(*, login_declined: bool = False) -> set[UserActionCode]:
    actions = set(REQUESTABLE_USER_ACTION_CODES)
    if login_declined:
        actions.difference_update({
            UserActionCode.ENABLE_BROWSER_SESSION,
            UserActionCode.LOGIN_THEN_RETRY,
        })
    return actions


@dataclass(frozen=True)
class RecoveryDecision:
    kind: RecoveryDecisionKind
    action: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def __post_init__(self):
        try:
            kind = self.kind if isinstance(self.kind, RecoveryDecisionKind) else RecoveryDecisionKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid recovery decision kind") from exc
        object.__setattr__(self, "kind", kind)
        if not isinstance(self.arguments, dict):
            raise ValueError("recovery decision arguments must be an object")
        object.__setattr__(self, "action", str(self.action or "").strip())
        object.__setattr__(self, "message", sanitize_plain_text(self.message, max_length=500))


@dataclass(frozen=True)
class RecoveryContinuation:
    """可持久化的最小继续现场；原 URL 仍由任务记录持有。"""

    platform: str
    failure_kind: str
    failure_stage: str
    attempted_actions: tuple[str, ...]


@dataclass(frozen=True)
class RecoveryResult:
    status: RecoveryRunStatus
    code: str
    message: str
    media_path: Optional[str] = None
    subtitle_text: Optional[str] = None
    title: Optional[str] = None
    language: Optional[str] = None
    user_action: Optional[UserActionCode] = None
    continuation: Optional[RecoveryContinuation] = None
    observations: tuple[RecoveryObservation, ...] = ()

    def __post_init__(self):
        status = self.status if isinstance(self.status, RecoveryRunStatus) else RecoveryRunStatus(self.status)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "code", str(self.code or "recovery_failed")[:64])
        object.__setattr__(self, "message", sanitize_plain_text(self.message, max_length=800))
        if self.user_action is not None and not isinstance(self.user_action, UserActionCode):
            object.__setattr__(self, "user_action", UserActionCode(self.user_action))
        if status is RecoveryRunStatus.RECOVERED and not (self.media_path or self.subtitle_text):
            raise ValueError("recovered result requires a host-verified artifact")
        if status is RecoveryRunStatus.ACTION_REQUIRED:
            if self.user_action is None or self.continuation is None:
                raise ValueError("action_required result requires action and continuation")


@dataclass(frozen=True)
class RecoveryBudget:
    max_model_turns: int = 5
    max_actions: int = 6
    total_timeout_sec: float = 120.0
    model_timeout_sec: float = 30.0
    action_timeout_sec: float = 60.0
    max_model_output_chars: int = 8_000
    max_observation_chars: int = 1_200

    def __post_init__(self):
        if self.max_model_turns < 1 or self.max_actions < 1:
            raise ValueError("recovery budgets must be positive")
        if min(self.total_timeout_sec, self.model_timeout_sec, self.action_timeout_sec) <= 0:
            raise ValueError("recovery timeouts must be positive")


class RecoveryModel(Protocol):
    async def decide(
        self,
        messages: Sequence[dict[str, str]],
        available_actions: Sequence[dict[str, Any]],
        *,
        max_output_chars: int,
    ) -> RecoveryDecision: ...


class RecoveryActionExecutor(Protocol):
    def action_specs(self) -> Sequence[dict[str, Any]]: ...

    async def execute(self, action: RecoveryAction, arguments: dict[str, Any]) -> RecoveryObservation: ...

    def verified_result(self, observations: tuple[RecoveryObservation, ...]) -> Optional[RecoveryResult]: ...

    def pending_user_action(self) -> Optional[tuple[UserActionCode, str]]: ...


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class OpenAICompatibleRecoveryModel:
    """DeepSeek/OpenAI-compatible 适配；Key 只保存在 SDK client 内。"""

    def __init__(self, *, api_key: str, base_url: str, model: str):
        import openai

        key = (api_key or "").strip()
        model_id = (model or "").strip()
        if not key or not model_id:
            raise ValueError("recovery model requires api_key and model")
        kwargs: dict[str, Any] = {"api_key": key, "timeout": 30.0, "max_retries": 0}
        if (base_url or "").strip():
            kwargs["base_url"] = base_url.strip().rstrip("/")
        self._client = openai.OpenAI(**kwargs)
        self._model = model_id

    async def decide(
        self,
        messages: Sequence[dict[str, str]],
        available_actions: Sequence[dict[str, Any]],
        *,
        max_output_chars: int,
    ) -> RecoveryDecision:
        system = (
            "You diagnose media extraction failures. Choose only one listed action at a time. "
            "Never request secrets, cookies, tokens, shell, files, or source-code access. "
            "Return JSON only: {\"kind\":\"action\",\"action\":\"...\",\"arguments\":{}} "
            "or {\"kind\":\"completed\",\"message\":\"...\"} or "
            "{\"kind\":\"failed\",\"message\":\"...\"}. "
            f"Available actions: {json.dumps(list(available_actions), ensure_ascii=False)}"
        )

        def _call():
            return self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system}, *messages],
                temperature=0,
                max_tokens=800,
                response_format={"type": "json_object"},
            )

        response = await asyncio.to_thread(_call)
        content = response.choices[0].message.content or ""
        if len(content) > max_output_chars:
            raise ValueError("recovery model output exceeded limit")
        raw = _JSON_FENCE_RE.sub("", content.strip())
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("recovery model returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("recovery model result must be an object")
        return RecoveryDecision(
            kind=data.get("kind", ""),
            action=data.get("action", ""),
            arguments=data.get("arguments") or {},
            message=data.get("message", ""),
        )


class MediaRecoveryCoordinator:
    """短生命周期 loop；没有可用模型时立即返回，不改变既有失败。"""

    def __init__(
        self,
        model: Optional[RecoveryModel],
        executor: RecoveryActionExecutor,
        *,
        budget: RecoveryBudget = RecoveryBudget(),
    ):
        self._model = model
        self._executor = executor
        self._budget = budget

    async def run(self, failure: ExtractionFailure) -> RecoveryResult:
        if self._model is None:
            return RecoveryResult(
                status=RecoveryRunStatus.UNAVAILABLE,
                code="model_unavailable",
                message="媒体恢复模型未配置，保留原始失败。",
            )
        try:
            return await asyncio.wait_for(self._run_loop(failure), timeout=self._budget.total_timeout_sec)
        except asyncio.TimeoutError:
            return RecoveryResult(
                status=RecoveryRunStatus.FAILED,
                code="total_timeout",
                message="媒体恢复已达到总时间上限。",
            )
        except CancelledByUser:
            return RecoveryResult(
                status=RecoveryRunStatus.CANCELLED,
                code="cancelled",
                message="媒体恢复已取消。",
            )

    async def _run_loop(self, failure: ExtractionFailure) -> RecoveryResult:
        observations: list[RecoveryObservation] = []
        messages: list[dict[str, str]] = [{
            "role": "user",
            "content": json.dumps({
                "goal": "recover a verified subtitle or audio artifact",
                "failure": {
                    "platform": failure.platform,
                    "stage": failure.stage.value,
                    "kind": failure.kind.value,
                    "summary": failure.sanitized_summary,
                    "yt_dlp_version": failure.yt_dlp_version,
                    "cookie_available": failure.cookie_available,
                    "deno_available": failure.deno_available,
                    "ejs_available": failure.ejs_available,
                    "attempted_actions": [item.value for item in failure.attempted_actions],
                },
            }, ensure_ascii=False),
        }]
        action_count = 0

        for _turn in range(self._budget.max_model_turns):
            token = cancellation.current()
            if token is not None:
                token.check()
            try:
                decision = await asyncio.wait_for(
                    self._model.decide(
                        messages,
                        self._executor.action_specs(),
                        max_output_chars=self._budget.max_model_output_chars,
                    ),
                    timeout=self._budget.model_timeout_sec,
                )
            except asyncio.TimeoutError:
                return self._failed("model_timeout", "媒体恢复模型调用超时。", observations)
            except CancelledByUser:
                raise
            except Exception as exc:
                logger.warning("媒体恢复模型调用失败: %s", sanitize_diagnostic(exc))
                return self._failed("model_error", "媒体恢复模型不可用，保留原始失败。", observations)

            if decision.kind is RecoveryDecisionKind.COMPLETED:
                verified = self._executor.verified_result(tuple(observations))
                if verified is not None:
                    return verified
                messages.append({"role": "assistant", "content": self._decision_json(decision)})
                messages.append({"role": "user", "content": json.dumps({
                    "observation": {"status": "failure", "code": "artifact_not_verified",
                                    "summary": "Host has not verified any subtitle or media artifact."}
                })})
                continue

            if decision.kind is RecoveryDecisionKind.FAILED:
                return self._failed("model_stopped", decision.message or "模型判断无法安全恢复。", observations)

            if action_count >= self._budget.max_actions:
                return self._failed("action_budget_exhausted", "媒体恢复动作次数已达到上限。", observations)
            action_count += 1
            messages.append({"role": "assistant", "content": self._decision_json(decision)})

            try:
                action = RecoveryAction(decision.action)
            except ValueError:
                observation = RecoveryObservation(
                    action=RecoveryAction.INSPECT_FAILURE,
                    status=ObservationStatus.FAILURE,
                    code="unknown_action",
                    sanitized_summary=f"未知恢复动作：{decision.action}",
                )
            else:
                try:
                    observation = await asyncio.wait_for(
                        self._executor.execute(action, decision.arguments),
                        timeout=self._budget.action_timeout_sec,
                    )
                except asyncio.TimeoutError:
                    observation = RecoveryObservation(
                        action=action,
                        status=ObservationStatus.FAILURE,
                        code="action_timeout",
                        sanitized_summary="恢复动作执行超时。",
                    )
                except CancelledByUser:
                    raise
                except Exception as exc:
                    logger.warning("媒体恢复动作异常: %s", sanitize_diagnostic(exc))
                    observation = RecoveryObservation(
                        action=action,
                        status=ObservationStatus.FAILURE,
                        code="action_error",
                        sanitized_summary=sanitize_diagnostic(exc),
                    )
            observations.append(observation)

            pending = self._executor.pending_user_action()
            if pending is not None:
                action_code, message = pending
                continuation = RecoveryContinuation(
                    platform=failure.platform,
                    failure_kind=failure.kind.value,
                    failure_stage=failure.stage.value,
                    attempted_actions=tuple(item.action.value for item in observations),
                )
                return RecoveryResult(
                    status=RecoveryRunStatus.ACTION_REQUIRED,
                    code="user_action_required",
                    message=message,
                    user_action=action_code,
                    continuation=continuation,
                    observations=tuple(observations),
                )

            messages.append({"role": "user", "content": self._observation_json(observation)})

        return self._failed("model_turn_budget_exhausted", "媒体恢复模型轮数已达到上限。", observations)

    @staticmethod
    def _decision_json(decision: RecoveryDecision) -> str:
        return json.dumps({
            "kind": decision.kind.value,
            "action": decision.action,
            "arguments": decision.arguments,
            "message": decision.message,
        }, ensure_ascii=False)

    def _observation_json(self, observation: RecoveryObservation) -> str:
        summary = observation.sanitized_summary[: self._budget.max_observation_chars]
        return json.dumps({
            "observation": {
                "action": observation.action.value,
                "status": observation.status.value,
                "code": observation.code,
                "summary": summary,
            }
        }, ensure_ascii=False)

    @staticmethod
    def _failed(code: str, message: str, observations: Sequence[RecoveryObservation]) -> RecoveryResult:
        return RecoveryResult(
            status=RecoveryRunStatus.FAILED,
            code=code,
            message=message,
            observations=tuple(observations),
        )
