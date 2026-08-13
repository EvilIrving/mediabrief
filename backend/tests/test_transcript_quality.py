from media_contracts import (
    AudioAnalysisStatus,
    AudioProfile,
    EvidenceKind,
    FinalTranscriptSelection,
    QualityEvaluationStatus,
    QualityFindingCode,
    TimeRange,
)
from transcript_quality import (
    TranscriptSegment,
    evaluate_local_candidate,
    evaluate_transcript,
    select_retry_candidate,
)


def _profile(*, duration=60.0, speech=40.0):
    return AudioProfile(
        analysis_status=AudioAnalysisStatus.PARTIAL,
        duration_seconds=duration,
        speech_duration_seconds=speech,
        speech_ratio=speech / duration,
        silence_ratio=1.0 - speech / duration,
    )


def _codes(report):
    return {finding.code for finding in report.findings}


def test_vad_range_slightly_past_probe_duration_is_clipped():
    report = evaluate_transcript(
        [{"start": 0, "end": 10, "text": "one"}],
        _profile(duration=10, speech=10),
        speech_ranges=[(0, 10.006)],
    )

    assert report.evaluation_status is QualityEvaluationStatus.PASSED
    assert report.speech_duration_seconds == 10
    assert report.coverage_ratio == 1.0


def test_clean_transcript_passes_with_deterministic_coverage():
    report = evaluate_transcript(
        [
            {"start": 0, "end": 10, "text": "one"},
            {"start": 10, "end": 20, "text": "two"},
        ],
        _profile(duration=30, speech=20),
        speech_ranges=[(0, 20)],
    )

    assert report.evaluation_status is QualityEvaluationStatus.PASSED
    assert report.coverage_ratio == 1.0
    assert report.findings == ()
    assert report.final_selection is FinalTranscriptSelection.ORIGINAL


def test_empty_transcript_with_speech_fails_and_marks_full_range():
    report = evaluate_transcript([], _profile(duration=30, speech=20))

    assert report.evaluation_status is QualityEvaluationStatus.FAILED
    assert _codes(report) == {QualityFindingCode.EMPTY_WITH_SPEECH}
    assert report.suspicious_ranges == (TimeRange(0, 30),)


def test_low_coverage_and_long_speech_gap_use_vad_timeline():
    report = evaluate_transcript(
        [{"start": 0, "end": 4, "text": "opening"}],
        _profile(duration=40, speech=30),
        speech_ranges=[(0, 30)],
    )

    assert report.coverage_ratio == 4 / 30
    assert QualityFindingCode.LOW_COVERAGE in _codes(report)
    assert QualityFindingCode.SPEECH_GAP in _codes(report)
    gap = next(item for item in report.findings if item.code is QualityFindingCode.SPEECH_GAP)
    assert gap.evidence is EvidenceKind.DETERMINISTIC
    assert gap.ranges == (TimeRange(4, 30),)


def test_fixed_interval_repeat_and_known_hallucination_are_reported():
    report = evaluate_transcript(
        [
            {"start": 0, "end": 1, "text": "谢谢观看"},
            {"start": 2, "end": 3, "text": "谢谢观看"},
            {"start": 4, "end": 5, "text": "谢谢观看"},
            {"start": 6, "end": 7, "text": "谢谢观看"},
        ],
        _profile(duration=10, speech=7),
    )

    assert QualityFindingCode.FIXED_INTERVAL_REPEAT in _codes(report)
    assert QualityFindingCode.KNOWN_HALLUCINATION in _codes(report)
    assert report.evaluation_status is QualityEvaluationStatus.WARNING


def test_timestamp_and_overlong_checks_preserve_input_order():
    report = evaluate_transcript(
        [
            TranscriptSegment(20, 21, "later"),
            TranscriptSegment(5, 55, "overlong"),
            TranscriptSegment(59, 65, "past end"),
        ],
        _profile(duration=60, speech=30),
    )

    assert QualityFindingCode.TIMESTAMP_REGRESSION in _codes(report)
    assert QualityFindingCode.TIMESTAMP_OUT_OF_BOUNDS in _codes(report)
    assert QualityFindingCode.OVERLONG_SEGMENT in _codes(report)
    assert report.evaluation_status is QualityEvaluationStatus.FAILED
    assert all(item.end_seconds <= 60 for item in report.suspicious_ranges)


def test_local_candidate_uses_only_target_range():
    report = evaluate_local_candidate(
        [
            TranscriptSegment(0, 5, "outside"),
            TranscriptSegment(20, 24, "inside"),
        ],
        _profile(duration=30, speech=20),
        TimeRange(20, 25),
        speech_ranges=[TimeRange(20, 25)],
    )

    assert report.segment_count == 2
    assert report.coverage_ratio == 0.8
    assert report.evaluation_status is QualityEvaluationStatus.PASSED


def test_retry_candidate_replaces_repeated_hallucination_and_records_decision():
    original = [
        TranscriptSegment(10, 11, "谢谢观看"),
        TranscriptSegment(12, 13, "谢谢观看"),
        TranscriptSegment(14, 15, "谢谢观看"),
        TranscriptSegment(16, 17, "谢谢观看"),
    ]
    retry = [TranscriptSegment(10, 18, "the actual sentence")]

    result = select_retry_candidate(
        original,
        retry,
        _profile(duration=30, speech=20),
        TimeRange(10, 20),
        speech_ranges=[TimeRange(10, 18)],
    )

    assert result.selected is FinalTranscriptSelection.RETRY
    assert result.selected_segments == tuple(retry)
    assert result.record.before_findings
    assert result.record.after_findings == ()
    assert result.record.selected is FinalTranscriptSelection.RETRY
    assert result.report.retry_records == (result.record,)


def test_retry_candidate_keeps_original_on_tie_or_worse_result():
    original = [TranscriptSegment(10, 18, "credible text")]
    retry = [TranscriptSegment(10, 18, "谢谢观看")]

    result = select_retry_candidate(
        original,
        retry,
        _profile(duration=30, speech=20),
        TimeRange(10, 20),
        speech_ranges=[TimeRange(10, 18)],
    )

    assert result.selected is FinalTranscriptSelection.ORIGINAL
    assert result.selected_segments == tuple(original)
    assert result.record.after_findings == (QualityFindingCode.KNOWN_HALLUCINATION,)


def test_missing_speech_timeline_is_explicit_not_invented_for_local_range():
    report = evaluate_local_candidate(
        [TranscriptSegment(10, 12, "text")],
        _profile(duration=30, speech=20),
        TimeRange(10, 15),
    )

    assert report.coverage_ratio is None
    assert "speech_timeline" in report.unavailable_metrics
    assert "coverage" in report.unavailable_metrics
