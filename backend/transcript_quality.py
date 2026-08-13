"""转录结果的确定性质量复核与一次局部重试候选选择。"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

from media_contracts import (
    AudioProfile,
    EvidenceKind,
    FinalTranscriptSelection,
    QualityEvaluationStatus,
    QualityFinding,
    QualityFindingCode,
    TimeRange,
    TranscriptQualityReport,
    TranscriptRetryRecord,
)


MIN_SPEECH_FOR_EMPTY_SECONDS = 1.0
MIN_SPEECH_FOR_COVERAGE_SECONDS = 5.0
LOW_COVERAGE_RATIO = 0.5
FAILED_COVERAGE_RATIO = 0.15
MIN_SPEECH_GAP_SECONDS = 8.0
OVERLONG_SEGMENT_SECONDS = 45.0
TIMESTAMP_TOLERANCE_SECONDS = 0.05
REPEAT_MIN_RUN = 4
REPEAT_MAX_TEXT_CHARS = 32
REPEAT_MIN_STEP_SECONDS = 0.75
REPEAT_MAX_STEP_SECONDS = 6.0
REPEAT_MAX_STEP_SPREAD_SECONDS = 0.75

_TEXT_NORMALIZE_RE = re.compile(
    r"[\s，。！？、,.!?;；:：\"'“”‘’（）()【】\[\]{}<>《》…~\-—_]+"
)
_KNOWN_HALLUCINATIONS = {
    "我可以做的",
    "我可以用水煮的",
    "我会继续来到",
    "感谢观看",
    "谢谢观看",
    "请订阅频道",
    "thankyouforwatching",
    "thanksforwatching",
    "subtitlesbytheamaraorgcommunity",
}


@dataclass(frozen=True)
class TranscriptSegment:
    """质量检查器消费的最小段落类型；时间是否合法由检查器报告。"""

    start_seconds: float
    end_seconds: float
    text: str

    def __post_init__(self):
        start = float(self.start_seconds)
        end = float(self.end_seconds)
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("transcript timestamps must be finite")
        object.__setattr__(self, "start_seconds", start)
        object.__setattr__(self, "end_seconds", end)
        object.__setattr__(self, "text", str(self.text or "").strip())


@dataclass(frozen=True)
class RetrySelection:
    """一次局部重试的纯函数结果；调用方负责把选中片段拼回全文。"""

    selected: FinalTranscriptSelection
    selected_segments: tuple[TranscriptSegment, ...]
    report: TranscriptQualityReport
    record: TranscriptRetryRecord


SegmentInput = TranscriptSegment | Mapping[str, object]
RangeInput = TimeRange | Sequence[float] | Mapping[str, object]

_MARKDOWN_RANGE_RE = re.compile(
    r"^\*\*\[([0-9]{1,3}(?::[0-9]{2}){1,2}) - ([0-9]{1,3}(?::[0-9]{2}){1,2})\]\*\*$"
)


def _parse_clock(value: str) -> float:
    fields = [int(item) for item in value.split(":")]
    if len(fields) == 2:
        return float(fields[0] * 60 + fields[1])
    if len(fields) == 3:
        return float(fields[0] * 3600 + fields[1] * 60 + fields[2])
    raise ValueError("invalid transcript timestamp")


def parse_markdown_segments(transcript: str) -> tuple[TranscriptSegment, ...]:
    """读取 MediaBrief 现有 Markdown 转录格式，不解析任意 Markdown。"""
    lines = (transcript or "").splitlines()
    parsed: list[TranscriptSegment] = []
    index = 0
    while index < len(lines):
        matched = _MARKDOWN_RANGE_RE.fullmatch(lines[index].strip())
        if matched is None:
            index += 1
            continue
        start = _parse_clock(matched.group(1))
        end = _parse_clock(matched.group(2))
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and _MARKDOWN_RANGE_RE.fullmatch(lines[index].strip()) is None:
            if lines[index].strip():
                text_lines.append(lines[index].strip())
            index += 1
        parsed.append(TranscriptSegment(start, end, " ".join(text_lines)))
    return tuple(parsed)


def _segment(value: SegmentInput) -> TranscriptSegment:
    if isinstance(value, TranscriptSegment):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("segments must contain TranscriptSegment or mapping values")
    return TranscriptSegment(
        start_seconds=value.get("start_seconds", value.get("start", 0.0)),
        end_seconds=value.get("end_seconds", value.get("end", 0.0)),
        text=value.get("text", ""),
    )


def _time_range(value: RangeInput) -> TimeRange:
    if isinstance(value, TimeRange):
        return value
    if isinstance(value, Mapping):
        return TimeRange(
            value.get("start_seconds", value.get("start", 0.0)),
            value.get("end_seconds", value.get("end", 0.0)),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        return TimeRange(value[0], value[1])
    raise TypeError("ranges must contain TimeRange, pair, or mapping values")


def _normalize_text(text: str) -> str:
    return _TEXT_NORMALIZE_RE.sub("", text or "").lower()


def _merge_ranges(ranges: Iterable[TimeRange], *, join_gap: float = 0.05) -> tuple[TimeRange, ...]:
    ordered = sorted(ranges, key=lambda item: (item.start_seconds, item.end_seconds))
    merged: list[TimeRange] = []
    for current in ordered:
        if not merged or current.start_seconds > merged[-1].end_seconds + join_gap:
            merged.append(current)
            continue
        previous = merged[-1]
        merged[-1] = TimeRange(
            previous.start_seconds,
            max(previous.end_seconds, current.end_seconds),
        )
    return tuple(merged)


def _intersect(left: TimeRange, right: TimeRange) -> TimeRange | None:
    start = max(left.start_seconds, right.start_seconds)
    end = min(left.end_seconds, right.end_seconds)
    return TimeRange(start, end) if end > start else None


def _duration(ranges: Iterable[TimeRange]) -> float:
    return sum(item.end_seconds - item.start_seconds for item in _merge_ranges(ranges))


def _safe_segment_range(segment: TranscriptSegment, audio_duration: float | None) -> TimeRange | None:
    start = max(0.0, segment.start_seconds)
    end = segment.end_seconds
    if audio_duration is not None:
        start = min(start, audio_duration)
        end = min(end, audio_duration)
    if end <= start:
        return None
    return TimeRange(start, end)


def _valid_segment_range(segment: TranscriptSegment, audio_duration: float | None) -> TimeRange | None:
    if segment.start_seconds < 0 or segment.end_seconds <= segment.start_seconds:
        return None
    if audio_duration is not None and (
        segment.start_seconds >= audio_duration
        or segment.end_seconds > audio_duration + TIMESTAMP_TOLERANCE_SECONDS
    ):
        return None
    end = min(segment.end_seconds, audio_duration) if audio_duration is not None else segment.end_seconds
    return TimeRange(segment.start_seconds, end) if end > segment.start_seconds else None


def _finding(
    code: QualityFindingCode,
    evidence: EvidenceKind,
    ranges: Iterable[TimeRange],
    count: int,
) -> QualityFinding:
    return QualityFinding(
        code=code,
        evidence=evidence,
        ranges=_merge_ranges(ranges),
        count=max(1, count),
    )


def _fixed_repeat_ranges(segments: Sequence[TranscriptSegment]) -> tuple[TimeRange, ...]:
    ranges: list[TimeRange] = []
    index = 0
    while index < len(segments):
        normalized = _normalize_text(segments[index].text)
        end = index + 1
        while end < len(segments) and _normalize_text(segments[end].text) == normalized:
            end += 1
        run = segments[index:end]
        if REPEAT_MIN_RUN <= len(run) and normalized and len(normalized) <= REPEAT_MAX_TEXT_CHARS:
            starts = [item.start_seconds for item in run]
            steps = [right - left for left, right in zip(starts, starts[1:])]
            fixed = (
                steps
                and min(steps) >= REPEAT_MIN_STEP_SECONDS
                and max(steps) <= REPEAT_MAX_STEP_SECONDS
                and max(steps) - min(steps) <= REPEAT_MAX_STEP_SPREAD_SECONDS
            )
            if fixed:
                start = max(0.0, run[0].start_seconds)
                finish = max(start, run[-1].end_seconds)
                if finish > start:
                    ranges.append(TimeRange(start, finish))
        index = end
    return tuple(ranges)


def _subtract_ranges(
    source_ranges: Iterable[TimeRange],
    covered_ranges: Iterable[TimeRange],
) -> tuple[TimeRange, ...]:
    covered = _merge_ranges(covered_ranges)
    missing: list[TimeRange] = []
    for source in _merge_ranges(source_ranges):
        cursor = source.start_seconds
        for item in covered:
            overlap = _intersect(source, item)
            if overlap is None:
                continue
            if overlap.start_seconds > cursor:
                missing.append(TimeRange(cursor, overlap.start_seconds))
            cursor = max(cursor, overlap.end_seconds)
        if cursor < source.end_seconds:
            missing.append(TimeRange(cursor, source.end_seconds))
    return tuple(missing)


def _evaluate(
    segments: Iterable[SegmentInput],
    audio_profile: AudioProfile,
    *,
    speech_ranges: Iterable[RangeInput] | None,
    evaluation_range: TimeRange | None,
    selection: FinalTranscriptSelection,
) -> TranscriptQualityReport:
    if not isinstance(audio_profile, AudioProfile):
        raise TypeError("audio_profile must be an AudioProfile")
    parsed = tuple(_segment(value) for value in segments)
    audio_duration = audio_profile.duration_seconds
    unavailable: list[str] = []
    if audio_duration is None:
        unavailable.append("audio_duration")

    timeline: tuple[TimeRange, ...] | None = None
    if speech_ranges is not None:
        # VAD 末窗常比 ffprobe 时长多几毫秒；裁到媒体时长，不要因此炸掉整次转录。
        raw_ranges = [_time_range(value) for value in speech_ranges]
        if audio_duration is not None:
            clipped: list[TimeRange] = []
            for item in raw_ranges:
                if item.start_seconds >= audio_duration:
                    continue
                end = min(item.end_seconds, audio_duration)
                if end > item.start_seconds:
                    clipped.append(TimeRange(item.start_seconds, end))
            raw_ranges = clipped
        timeline = _merge_ranges(raw_ranges)
        if evaluation_range is not None:
            timeline = tuple(
                overlap
                for item in timeline
                if (overlap := _intersect(item, evaluation_range)) is not None
            )
        speech_duration = _duration(timeline)
    elif evaluation_range is None:
        speech_duration = audio_profile.speech_duration_seconds
        unavailable.append("speech_timeline")
    else:
        speech_duration = None
        unavailable.extend(("speech_duration", "speech_timeline"))
    if speech_duration is None and "speech_duration" not in unavailable:
        unavailable.append("speech_duration")

    findings: list[QualityFinding] = []
    timestamp_bounds_ranges: list[TimeRange] = []
    timestamp_bounds_count = 0
    regression_ranges: list[TimeRange] = []
    regression_count = 0
    previous: TranscriptSegment | None = None
    valid_text_segments: list[TranscriptSegment] = []
    valid_text_ranges: list[TimeRange] = []

    for segment in parsed:
        out_of_bounds = (
            segment.start_seconds < 0
            or segment.end_seconds <= segment.start_seconds
            or (
                audio_duration is not None
                and (
                    segment.start_seconds >= audio_duration
                    or segment.end_seconds > audio_duration + TIMESTAMP_TOLERANCE_SECONDS
                )
            )
        )
        if out_of_bounds:
            timestamp_bounds_count += 1
            safe = _safe_segment_range(segment, audio_duration)
            if safe is not None:
                timestamp_bounds_ranges.append(safe)
        if previous is not None and (
            segment.start_seconds < previous.start_seconds - TIMESTAMP_TOLERANCE_SECONDS
            or segment.end_seconds < previous.end_seconds - TIMESTAMP_TOLERANCE_SECONDS
        ):
            regression_count += 1
            for item in (previous, segment):
                safe = _safe_segment_range(item, audio_duration)
                if safe is not None:
                    regression_ranges.append(safe)
        previous = segment

        valid = _valid_segment_range(segment, audio_duration)
        if valid is None or not segment.text:
            continue
        if evaluation_range is not None:
            valid = _intersect(valid, evaluation_range)
            if valid is None:
                continue
        valid_text_segments.append(segment)
        valid_text_ranges.append(valid)

    if timestamp_bounds_count:
        findings.append(_finding(
            QualityFindingCode.TIMESTAMP_OUT_OF_BOUNDS,
            EvidenceKind.DETERMINISTIC,
            timestamp_bounds_ranges,
            timestamp_bounds_count,
        ))
    if regression_count:
        findings.append(_finding(
            QualityFindingCode.TIMESTAMP_REGRESSION,
            EvidenceKind.DETERMINISTIC,
            regression_ranges,
            regression_count,
        ))

    repeat_ranges = _fixed_repeat_ranges(valid_text_segments)
    if repeat_ranges:
        findings.append(_finding(
            QualityFindingCode.FIXED_INTERVAL_REPEAT,
            EvidenceKind.HEURISTIC,
            repeat_ranges,
            len(repeat_ranges),
        ))

    hallucination_ranges = tuple(
        item
        for segment in valid_text_segments
        if _normalize_text(segment.text) in _KNOWN_HALLUCINATIONS
        if (item := _valid_segment_range(segment, audio_duration)) is not None
        if evaluation_range is None or (item := _intersect(item, evaluation_range)) is not None
    )
    if hallucination_ranges:
        findings.append(_finding(
            QualityFindingCode.KNOWN_HALLUCINATION,
            EvidenceKind.HEURISTIC,
            hallucination_ranges,
            len(hallucination_ranges),
        ))

    overlong_ranges = tuple(
        item
        for item in valid_text_ranges
        if item.end_seconds - item.start_seconds > OVERLONG_SEGMENT_SECONDS
    )
    if overlong_ranges:
        findings.append(_finding(
            QualityFindingCode.OVERLONG_SEGMENT,
            EvidenceKind.DETERMINISTIC,
            overlong_ranges,
            len(overlong_ranges),
        ))

    merged_text_ranges = _merge_ranges(valid_text_ranges)
    coverage_ratio: float | None = None
    speech_gap_ranges: tuple[TimeRange, ...] = ()
    if timeline is not None:
        covered = tuple(
            overlap
            for speech in timeline
            for text_range in merged_text_ranges
            if (overlap := _intersect(speech, text_range)) is not None
        )
        coverage_ratio = min(1.0, _duration(covered) / speech_duration) if speech_duration else None
        speech_gap_ranges = tuple(
            item
            for item in _subtract_ranges(timeline, merged_text_ranges)
            if item.end_seconds - item.start_seconds >= MIN_SPEECH_GAP_SECONDS
        )
    elif speech_duration and evaluation_range is None:
        coverage_ratio = min(1.0, _duration(merged_text_ranges) / speech_duration)
    else:
        unavailable.append("coverage")

    expected_speech = speech_duration is not None and speech_duration >= MIN_SPEECH_FOR_EMPTY_SECONDS
    if expected_speech and not valid_text_segments:
        fallback = evaluation_range
        if fallback is None and audio_duration and audio_duration > 0:
            fallback = TimeRange(0.0, audio_duration)
        findings.append(_finding(
            QualityFindingCode.EMPTY_WITH_SPEECH,
            EvidenceKind.DETERMINISTIC,
            (fallback,) if fallback is not None else (),
            1,
        ))
    elif (
        expected_speech
        and speech_duration is not None
        and speech_duration >= MIN_SPEECH_FOR_COVERAGE_SECONDS
        and coverage_ratio is not None
        and coverage_ratio < LOW_COVERAGE_RATIO
    ):
        coverage_ranges = speech_gap_ranges
        if not coverage_ranges:
            fallback = evaluation_range
            if fallback is None and audio_duration and audio_duration > 0:
                fallback = TimeRange(0.0, audio_duration)
            coverage_ranges = (fallback,) if fallback is not None else ()
        findings.append(_finding(
            QualityFindingCode.LOW_COVERAGE,
            EvidenceKind.DETERMINISTIC,
            coverage_ranges,
            1,
        ))

    if speech_gap_ranges:
        findings.append(_finding(
            QualityFindingCode.SPEECH_GAP,
            EvidenceKind.DETERMINISTIC,
            speech_gap_ranges,
            len(speech_gap_ranges),
        ))

    suspicious = _merge_ranges(
        item for finding in findings for item in finding.ranges
    )
    codes = {finding.code for finding in findings}
    failed = bool(codes & {
        QualityFindingCode.EMPTY_WITH_SPEECH,
        QualityFindingCode.TIMESTAMP_REGRESSION,
        QualityFindingCode.TIMESTAMP_OUT_OF_BOUNDS,
    }) or (
        QualityFindingCode.LOW_COVERAGE in codes
        and coverage_ratio is not None
        and coverage_ratio < FAILED_COVERAGE_RATIO
    )
    status = (
        QualityEvaluationStatus.FAILED
        if failed
        else QualityEvaluationStatus.WARNING
        if findings
        else QualityEvaluationStatus.PASSED
    )
    return TranscriptQualityReport(
        evaluation_status=status,
        audio_duration_seconds=audio_duration,
        speech_duration_seconds=speech_duration,
        segment_count=len(parsed),
        coverage_ratio=coverage_ratio,
        findings=tuple(findings),
        suspicious_ranges=suspicious,
        unavailable_metrics=tuple(dict.fromkeys(unavailable)),
        final_selection=selection,
    )


def evaluate_transcript(
    segments: Iterable[SegmentInput],
    audio_profile: AudioProfile,
    *,
    speech_ranges: Iterable[RangeInput] | None = None,
) -> TranscriptQualityReport:
    """复核完整转录；同一输入总是生成相同报告。"""
    return _evaluate(
        segments,
        audio_profile,
        speech_ranges=speech_ranges,
        evaluation_range=None,
        selection=FinalTranscriptSelection.ORIGINAL,
    )


def evaluate_local_candidate(
    segments: Iterable[SegmentInput],
    audio_profile: AudioProfile,
    time_range: RangeInput,
    *,
    speech_ranges: Iterable[RangeInput] | None = None,
    selection: FinalTranscriptSelection = FinalTranscriptSelection.ORIGINAL,
) -> TranscriptQualityReport:
    """只评估给定绝对时间区间内的候选片段，不触发任何转录或重试。"""
    selected = FinalTranscriptSelection(selection)
    if selected is FinalTranscriptSelection.NOT_APPLICABLE:
        raise ValueError("local candidate must be original or retry")
    return _evaluate(
        segments,
        audio_profile,
        speech_ranges=speech_ranges,
        evaluation_range=_time_range(time_range),
        selection=selected,
    )


_FINDING_WEIGHTS = {
    QualityFindingCode.EMPTY_WITH_SPEECH: 100,
    QualityFindingCode.TIMESTAMP_OUT_OF_BOUNDS: 80,
    QualityFindingCode.TIMESTAMP_REGRESSION: 80,
    QualityFindingCode.KNOWN_HALLUCINATION: 45,
    QualityFindingCode.FIXED_INTERVAL_REPEAT: 40,
    QualityFindingCode.LOW_COVERAGE: 35,
    QualityFindingCode.SPEECH_GAP: 30,
    QualityFindingCode.OVERLONG_SEGMENT: 15,
}


def _credibility_key(
    report: TranscriptQualityReport,
    segments: Sequence[TranscriptSegment],
) -> tuple[float, float, int]:
    finding_penalty = sum(
        _FINDING_WEIGHTS[finding.code] * (finding.count or 1)
        for finding in report.findings
    )
    coverage_penalty = 1.0 - report.coverage_ratio if report.coverage_ratio is not None else 0.5
    empty_penalty = 1 if not any(segment.text for segment in segments) else 0
    return finding_penalty, coverage_penalty, empty_penalty


def select_retry_candidate(
    original_segments: Iterable[SegmentInput],
    retry_segments: Iterable[SegmentInput],
    audio_profile: AudioProfile,
    time_range: RangeInput,
    *,
    speech_ranges: Iterable[RangeInput] | None = None,
) -> RetrySelection:
    """比较一次局部重试；只有严格更可信时才替换原片段，平局保留原结果。"""
    target = _time_range(time_range)
    original = tuple(_segment(value) for value in original_segments)
    retry = tuple(_segment(value) for value in retry_segments)
    original_report = evaluate_local_candidate(
        original,
        audio_profile,
        target,
        speech_ranges=speech_ranges,
        selection=FinalTranscriptSelection.ORIGINAL,
    )
    retry_report = evaluate_local_candidate(
        retry,
        audio_profile,
        target,
        speech_ranges=speech_ranges,
        selection=FinalTranscriptSelection.RETRY,
    )
    use_retry = _credibility_key(retry_report, retry) < _credibility_key(original_report, original)
    selected = FinalTranscriptSelection.RETRY if use_retry else FinalTranscriptSelection.ORIGINAL
    if use_retry:
        outside = tuple(
            segment
            for segment in original
            if segment.end_seconds <= target.start_seconds
            or segment.start_seconds >= target.end_seconds
        )
        chosen_segments = tuple(sorted((*outside, *retry), key=lambda item: (item.start_seconds, item.end_seconds)))
    else:
        chosen_segments = original
    record = TranscriptRetryRecord(
        time_range=target,
        before_findings=tuple(finding.code for finding in original_report.findings),
        after_findings=tuple(finding.code for finding in retry_report.findings),
        selected=selected,
    )
    chosen_report = evaluate_transcript(chosen_segments, audio_profile, speech_ranges=speech_ranges)
    final_report = replace(
        chosen_report,
        retry_records=(record,),
        final_selection=selected,
    )
    return RetrySelection(
        selected=selected,
        selected_segments=chosen_segments,
        report=final_report,
        record=record,
    )


__all__ = [
    "RetrySelection",
    "TranscriptSegment",
    "evaluate_local_candidate",
    "evaluate_transcript",
    "parse_markdown_segments",
    "select_retry_candidate",
]
