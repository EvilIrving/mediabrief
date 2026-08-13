from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from media_contracts import (
    AudioAnalysisStatus,
    AudioProfile,
    EvidenceKind,
    ExtractionAction,
    ExtractionFailure,
    ExtractionFailureKind,
    ExtractionStage,
    FinalTranscriptSelection,
    ObservationStatus,
    QualityEvaluationStatus,
    QualityFinding,
    QualityFindingCode,
    RecoveryAction,
    RecoveryObservation,
    StrategyProfile,
    SubtitleFetchResult,
    SubtitleFetchStatus,
    TimeRange,
    TranscriptQualityReport,
    TranscriptionStrategy,
    classify_extraction_failure,
    sanitize_diagnostic,
)


def test_diagnostic_contract_redacts_secrets_paths_and_private_url_parts():
    raw = (
        "failed https://alice:pw@example.com/watch/private-id?v=abc&sig=url-secret "
        "api_key=sk-1234567890 po_token=proof-secret\n"
        "API Key=space-key PO Token=space-proof Cookie=equals-cookie\n"
        "Authorization: Bearer bearer-secret\n"
        "Cookie: SID=cookie-secret\n"
        "{'Cookie': 'mapping-cookie', 'Authorization': 'Bearer mapping-auth'}\n"
        "/Users/alice/Library/Application Support/Google/Chrome/Default/Cookies\n"
        "/Users/alice/My Secret/file.txt"
    )

    safe = sanitize_diagnostic(raw)

    for secret in (
        "alice", "private-id", "url-secret", "sk-1234567890", "proof-secret",
        "bearer-secret", "cookie-secret", "Google/Chrome/Default/Cookies",
        "mapping-cookie", "mapping-auth",
        "My Secret/file.txt",
        "space-key", "space-proof", "equals-cookie",
    ):
        assert secret not in safe
    assert "https://example.com/[redacted]" in safe


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sign in to confirm you're not a bot", ExtractionFailureKind.CHALLENGE_REQUIRED),
        ("HTTP Error 429: Too Many Requests", ExtractionFailureKind.RATE_LIMITED),
        ("This video is private", ExtractionFailureKind.PERMISSION_DENIED),
        ("HTTP Error 401: login required", ExtractionFailureKind.AUTH_REQUIRED),
        ("This format is DRM protected", ExtractionFailureKind.DRM_PROTECTED),
        ("connection reset", ExtractionFailureKind.SUBTITLE_DOWNLOAD_FAILED),
    ],
)
def test_extraction_failure_classification(raw, expected):
    assert classify_extraction_failure(raw, ExtractionStage.SUBTITLE_DOWNLOAD) is expected


def test_extraction_failure_is_safe_when_constructed_from_raw_error():
    failure = ExtractionFailure.from_error(
        platform="youtube",
        stage=ExtractionStage.METADATA,
        error="HTTP 429 https://example.com/watch?token=raw-secret api_key=key-secret",
        yt_dlp_version="2026.07.04",
        cookie_available=True,
        deno_available=True,
        ejs_available=True,
        attempted_actions=(ExtractionAction.INSPECT_METADATA,),
    )

    serialized = json.dumps(asdict(failure))
    assert failure.kind is ExtractionFailureKind.RATE_LIMITED
    assert "raw-secret" not in serialized
    assert "key-secret" not in serialized


def test_subtitle_result_enforces_found_absent_failed_boundary():
    failure = ExtractionFailure(
        platform="generic",
        stage=ExtractionStage.SUBTITLE_PARSE,
        kind=ExtractionFailureKind.SUBTITLE_PARSE_FAILED,
        sanitized_summary="invalid subtitle",
    )
    assert SubtitleFetchResult(status=SubtitleFetchStatus.NO_SUBTITLES).failure is None
    assert SubtitleFetchResult(status=SubtitleFetchStatus.FAILED, failure=failure).failure is failure
    with pytest.raises(ValueError):
        SubtitleFetchResult(status=SubtitleFetchStatus.FOUND, text="")


def test_remaining_contracts_express_unknown_default_without_running_later_tasks():
    observation = RecoveryObservation(
        action=RecoveryAction.INSPECT_FAILURE,
        status=ObservationStatus.SUCCESS,
        code="inspected",
        sanitized_summary="failure inspected",
    )
    audio = AudioProfile()
    strategy = TranscriptionStrategy.current_default("base")
    quality = TranscriptQualityReport()

    assert observation.failure is None
    assert audio.analysis_status is AudioAnalysisStatus.NOT_ANALYZED
    assert strategy.profile is StrategyProfile.DEFAULT
    assert strategy.max_segment_retries == 0
    assert quality.evaluation_status is QualityEvaluationStatus.NOT_EVALUATED
    assert quality.final_selection is FinalTranscriptSelection.NOT_APPLICABLE


def test_contract_validation_rejects_fabricated_or_out_of_bounds_facts():
    with pytest.raises(ValueError):
        AudioProfile(speech_ratio=0.5)
    with pytest.raises(ValueError):
        TimeRange(5, 5)
    with pytest.raises(ValueError):
        TranscriptQualityReport(
            evaluation_status=QualityEvaluationStatus.NOT_EVALUATED,
            findings=(
                QualityFinding(
                    code=QualityFindingCode.LOW_COVERAGE,
                    evidence=EvidenceKind.HEURISTIC,
                ),
            ),
        )
