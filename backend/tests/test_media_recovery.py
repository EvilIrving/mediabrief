from __future__ import annotations

from pathlib import Path

import pytest

import cancellation
from media_contracts import (
    ExtractionFailure,
    ExtractionFailureKind,
    ExtractionStage,
    ObservationStatus,
    RecoveryAction,
    RecoveryObservation,
)
from media_recovery import (
    MediaRecoveryCoordinator,
    RecoveryBudget,
    RecoveryDecision,
    RecoveryResult,
    RecoveryRunStatus,
    UserActionCode,
)


def _failure(summary="HTTP 429 from source"):
    return ExtractionFailure(
        platform="youtube",
        stage=ExtractionStage.MEDIA_DOWNLOAD,
        kind=ExtractionFailureKind.RATE_LIMITED,
        sanitized_summary=summary,
        yt_dlp_version="2026.08.01",
        cookie_available=False,
        deno_available=True,
        ejs_available=True,
    )


class FakeModel:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = []

    async def decide(self, messages, available_actions, *, max_output_chars):
        self.calls.append((list(messages), list(available_actions), max_output_chars))
        item = self.decisions.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeExecutor:
    def __init__(self, *, fail_action=False):
        self.calls = []
        self.verified = False
        self.pending = None
        self.fail_action = fail_action

    def action_specs(self):
        return [{"name": "inspect_failure"}, {"name": "run_ytdlp"}, {"name": "ask_user"}]

    async def execute(self, action, arguments):
        self.calls.append((action, arguments))
        if self.fail_action:
            raise RuntimeError("Cookie: secret-value https://example.com/private?id=1")
        if action is RecoveryAction.INSPECT_FAILURE:
            return RecoveryObservation(
                action=action,
                status=ObservationStatus.SUCCESS,
                code="failure_inspected",
                sanitized_summary="rate limited",
            )
        if action is RecoveryAction.RUN_YTDLP:
            if set(arguments) != {"profile"}:
                return RecoveryObservation(
                    action=action,
                    status=ObservationStatus.FAILURE,
                    code="invalid_arguments",
                    sanitized_summary="invalid args",
                )
            self.verified = True
            return RecoveryObservation(
                action=action,
                status=ObservationStatus.SUCCESS,
                code="media_downloaded",
                sanitized_summary="host verified media",
            )
        if action is RecoveryAction.ASK_USER:
            self.pending = (UserActionCode.ENABLE_BROWSER_SESSION, "请允许本次浏览器会话")
            return RecoveryObservation(
                action=action,
                status=ObservationStatus.SUCCESS,
                code="user_action_requested",
                sanitized_summary="需要用户操作",
            )
        raise AssertionError(action)

    def verified_result(self, observations):
        if not self.verified:
            return None
        return RecoveryResult(
            status=RecoveryRunStatus.RECOVERED,
            code="artifact_verified",
            message="verified",
            media_path="/tmp/verified.m4a",
            observations=observations,
        )

    def pending_user_action(self):
        return self.pending


async def test_multistep_loop_only_completes_after_host_verification():
    model = FakeModel([
        RecoveryDecision("action", "inspect_failure", {}),
        RecoveryDecision("action", "run_ytdlp", {"profile": "audio"}),
        RecoveryDecision("completed", message="done"),
    ])
    executor = FakeExecutor()

    result = await MediaRecoveryCoordinator(model, executor).run(_failure())

    assert result.status is RecoveryRunStatus.RECOVERED
    assert [call[0] for call in executor.calls] == [RecoveryAction.INSPECT_FAILURE, RecoveryAction.RUN_YTDLP]
    assert len(result.observations) == 2
    model_context = str(model.calls)
    assert "secret-value" not in model_context


async def test_unknown_action_becomes_observation_instead_of_capability():
    model = FakeModel([
        RecoveryDecision("action", "run_shell", {"command": "env"}),
        RecoveryDecision("failed", message="stop"),
    ])
    executor = FakeExecutor()

    result = await MediaRecoveryCoordinator(model, executor).run(_failure())

    assert result.status is RecoveryRunStatus.FAILED
    assert result.observations[0].code == "unknown_action"
    assert executor.calls == []


async def test_invalid_arguments_are_returned_to_model_and_loop_stops_safely():
    model = FakeModel([
        RecoveryDecision("action", "run_ytdlp", {"raw_options": {"exec": "x"}}),
        RecoveryDecision("failed", message="cannot recover"),
    ])
    executor = FakeExecutor()

    result = await MediaRecoveryCoordinator(model, executor).run(_failure())

    assert result.observations[0].code == "invalid_arguments"
    assert result.status is RecoveryRunStatus.FAILED


async def test_action_exception_is_sanitized_observation():
    model = FakeModel([
        RecoveryDecision("action", "inspect_failure", {}),
        RecoveryDecision("failed", message="stop"),
    ])

    result = await MediaRecoveryCoordinator(model, FakeExecutor(fail_action=True)).run(_failure())

    assert result.observations[0].code == "action_error"
    assert "secret-value" not in result.observations[0].sanitized_summary
    assert "private?id=1" not in result.observations[0].sanitized_summary


async def test_model_turn_budget_is_hard_limit():
    model = FakeModel([RecoveryDecision("action", "inspect_failure", {})] * 3)
    coordinator = MediaRecoveryCoordinator(
        model,
        FakeExecutor(),
        budget=RecoveryBudget(max_model_turns=2, max_actions=4),
    )

    result = await coordinator.run(_failure())

    assert result.status is RecoveryRunStatus.FAILED
    assert result.code == "model_turn_budget_exhausted"
    assert len(model.calls) == 2


async def test_ask_user_returns_minimal_continuation_and_ends_run():
    model = FakeModel([
        RecoveryDecision("action", "ask_user", {
            "action_code": "enable_browser_session",
            "message": "allow browser session",
        }),
    ])

    result = await MediaRecoveryCoordinator(model, FakeExecutor()).run(_failure())

    assert result.status is RecoveryRunStatus.ACTION_REQUIRED
    assert result.user_action is UserActionCode.ENABLE_BROWSER_SESSION
    assert result.continuation.platform == "youtube"
    assert not hasattr(result.continuation, "source_url")


async def test_cancelled_token_stops_before_model_call():
    token = cancellation.create("recovery-cancel-test")
    token.cancel()
    model = FakeModel([RecoveryDecision("failed", message="unused")])
    try:
        result = await MediaRecoveryCoordinator(model, FakeExecutor()).run(_failure())
    finally:
        cancellation.discard("recovery-cancel-test")

    assert result.status is RecoveryRunStatus.CANCELLED
    assert model.calls == []


async def test_unconfigured_model_preserves_original_failure_without_actions():
    executor = FakeExecutor()

    result = await MediaRecoveryCoordinator(None, executor).run(_failure())

    assert result.status is RecoveryRunStatus.UNAVAILABLE
    assert executor.calls == []

