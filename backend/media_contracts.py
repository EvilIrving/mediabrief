"""媒体获取、音频分析与转录质量之间的类型化契约。

本模块只定义数据边界和不变量，不执行媒体恢复、音频分析、策略选择或质量检查。
未知事实统一用 ``None`` / ``not_*`` 表达，不能用 0 或 False 伪装成已测结果。
"""
from __future__ import annotations

import math
import re
from html import unescape
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import urlsplit


MAX_DIAGNOSTIC_LENGTH = 800


class _StringEnum(str, Enum):
    """可安全序列化为稳定字符串的闭集枚举。"""


class ExtractionStage(_StringEnum):
    METADATA = "metadata"
    SUBTITLE_DOWNLOAD = "subtitle_download"
    SUBTITLE_PARSE = "subtitle_parse"
    MEDIA_DOWNLOAD = "media_download"
    MEDIA_VALIDATION = "media_validation"


class ExtractionFailureKind(_StringEnum):
    METADATA_FAILED = "metadata_failed"
    SUBTITLE_DOWNLOAD_FAILED = "subtitle_download_failed"
    SUBTITLE_PARSE_FAILED = "subtitle_parse_failed"
    MEDIA_DOWNLOAD_FAILED = "media_download_failed"
    MEDIA_VALIDATION_FAILED = "media_validation_failed"
    AUTH_REQUIRED = "auth_required"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMITED = "rate_limited"
    CHALLENGE_REQUIRED = "challenge_required"
    DRM_PROTECTED = "drm_protected"
    CANCELLED = "cancelled"


class ExtractionAction(_StringEnum):
    INSPECT_METADATA = "inspect_metadata"
    DOWNLOAD_SUBTITLE = "download_subtitle"
    PARSE_SUBTITLE = "parse_subtitle"
    DOWNLOAD_AUDIO = "download_audio"
    VALIDATE_MEDIA = "validate_media"
    RETRY_WITHOUT_COOKIES = "retry_without_cookies"


class RecoveryAction(_StringEnum):
    INSPECT_FAILURE = "inspect_failure"
    INSPECT_RUNTIME = "inspect_runtime"
    RUN_YTDLP = "run_ytdlp"
    PREPARE_YTDLP_UPDATE = "prepare_ytdlp_update"
    HTTP_REQUEST = "http_request"
    RUN_CANDIDATE_PARSER = "run_candidate_parser"
    USE_BROWSER_SESSION = "use_browser_session"
    REQUEST_YOUTUBE_CHALLENGE_CAPABILITY = "request_youtube_challenge_capability"
    DOWNLOAD_CANDIDATE = "download_candidate"
    VALIDATE_MEDIA = "validate_media"
    VALIDATE_SUBTITLE = "validate_subtitle"
    SET_USER_MESSAGE = "set_user_message"
    ASK_USER = "ask_user"


class ObservationStatus(_StringEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class SubtitleFetchStatus(_StringEnum):
    FOUND = "found"
    NO_SUBTITLES = "no_subtitles"
    FAILED = "failed"
    SKIPPED = "skipped"


class AudioAnalysisStatus(_StringEnum):
    NOT_ANALYZED = "not_analyzed"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class AudioQualityGrade(_StringEnum):
    UNKNOWN = "unknown"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNUSABLE = "unusable"


class AudioIntegrityFlag(_StringEnum):
    CORRUPT = "corrupt"
    NO_AUDIO_TRACK = "no_audio_track"
    ABNORMALLY_SHORT = "abnormally_short"
    ALL_SILENCE = "all_silence"


class HeuristicLevel(_StringEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StrategyProfile(_StringEnum):
    DEFAULT = "default"
    CLEAN_SPEECH = "clean_speech"
    LONG_FORM = "long_form"
    SILENCE_HEAVY = "silence_heavy"
    LOW_VOLUME_OR_NOISY = "low_volume_or_noisy"
    SAFE_FALLBACK = "safe_fallback"


class LanguageMode(_StringEnum):
    AUTO = "auto"
    EXPLICIT = "explicit"


class VadProfile(_StringEnum):
    CURRENT_DEFAULT = "current_default"
    STANDARD = "standard"
    SILENCE_HEAVY = "silence_heavy"


class DecodeProfile(_StringEnum):
    CURRENT_DEFAULT = "current_default"
    CLEAN = "clean"
    ROBUST = "robust"


class ChunkBoundaryProfile(_StringEnum):
    CURRENT_DEFAULT = "current_default"
    PADDED = "padded"


class QualityEvaluationStatus(_StringEnum):
    NOT_EVALUATED = "not_evaluated"
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class QualityFindingCode(_StringEnum):
    EMPTY_WITH_SPEECH = "empty_with_speech"
    LOW_COVERAGE = "low_coverage"
    FIXED_INTERVAL_REPEAT = "fixed_interval_repeat"
    KNOWN_HALLUCINATION = "known_hallucination"
    SPEECH_GAP = "speech_gap"
    OVERLONG_SEGMENT = "overlong_segment"
    TIMESTAMP_REGRESSION = "timestamp_regression"
    TIMESTAMP_OUT_OF_BOUNDS = "timestamp_out_of_bounds"


class EvidenceKind(_StringEnum):
    DETERMINISTIC = "deterministic"
    HEURISTIC = "heuristic"


class FinalTranscriptSelection(_StringEnum):
    NOT_APPLICABLE = "not_applicable"
    ORIGINAL = "original"
    RETRY = "retry"


_URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(
    r"(?im)\b(?:authorization|proxy-authorization)\s*:\s*[^\r\n]*"
)
_COOKIE_HEADER_RE = re.compile(r"(?im)\b(?:cookie|set-cookie)\s*:\s*[^\r\n]*")
_MAPPING_SECRET_RE = re.compile(
    r"(?i)(['\"](?:authorization|proxy-authorization|cookie|set-cookie|api[\s_-]?key|"
    r"access[\s_-]?token|refresh[\s_-]?token|po[\s_-]?token|token|password|passwd|secret|"
    r"signature|cookies?[\s_-]?file|cookiesfrombrowser)['\"]\s*:\s*)"
    r"(?:['\"][^'\"]*['\"]|[^,}\]]+)"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:authorization|proxy-authorization|cookie|set-cookie|api[\s_-]?key|"
    r"access[\s_-]?token|refresh[\s_-]?token|po[\s_-]?token|token|password|passwd|"
    r"secret|signature|cookies?[\s_-]?file|cookiesfrombrowser)\b"
    r"\s*[:=]\s*(?:['\"][^'\"]*['\"]|[^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:sk|xox[baprs])-[A-Za-z0-9_-]{8,}\b|\beyJ[A-Za-z0-9_-]{12,}(?:\.[A-Za-z0-9_-]+){1,2}\b"
)
_COOKIE_DB_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:\\Users\\[^\r\n,'\"}\]]*?(?:Cookies|cookies\.sqlite)|"
    r"/(?:Users|home)/[^\r\n,'\"}\]]*?(?:Cookies|cookies\.sqlite))"
)
_USER_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:\\Users\\[^\r\n,'\"}\]]+|/(?:Users|home)/[^\r\n,'\"}\]]+)"
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_HTML_BLOCK_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?(?:</\1\s*>|$)")
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _redact_url(match: re.Match) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ").,;]}":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or "redacted-host"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme.lower()}://{host}{port}/[redacted]" + trailing
    except (TypeError, ValueError):
        return "[REDACTED_URL]" + trailing


def sanitize_diagnostic(value: object, *, max_length: int = MAX_DIAGNOSTIC_LENGTH) -> str:
    """清除诊断文本中的认证信息、私有 URL、用户路径和控制字符。

    分类逻辑可以在内存中读取原始异常，但任何日志、数据库、模型上下文或 API
    边界都只能消费本函数的结果。
    """
    text = "" if value is None else str(value)
    text = _MAPPING_SECRET_RE.sub(r"\1'[REDACTED]'", text)
    text = _AUTH_HEADER_RE.sub("Authorization: [REDACTED]", text)
    text = _COOKIE_HEADER_RE.sub("Cookie: [REDACTED]", text)
    text = _URL_RE.sub(_redact_url, text)
    text = _COOKIE_DB_PATH_RE.sub("[COOKIE_DB_PATH]", text)
    text = _USER_PATH_RE.sub("[USER_PATH]", text)
    text = _SECRET_VALUE_RE.sub("[REDACTED_SECRET]", text)
    text = _BEARER_RE.sub("[REDACTED_AUTH]", text)
    text = _KNOWN_TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    text = _CONTROL_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if max_length < 1:
        raise ValueError("max_length must be positive")
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


def sanitize_plain_text(value: object, *, max_length: int = MAX_DIAGNOSTIC_LENGTH) -> str:
    """生成可直接展示的纯文本，同时应用诊断脱敏和长度上限。"""
    text = unescape("" if value is None else str(value))
    text = _HTML_BLOCK_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    return sanitize_diagnostic(text, max_length=max_length)


def sanitize_source_reference(value: object) -> str:
    """生成仅保留来源域名的日志标签，绝不记录媒体 ID、查询参数或认证信息。"""
    safe = sanitize_diagnostic(value, max_length=200)
    return safe or "[unknown source]"


def _enum(value, enum_type, field_name: str):
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


def _optional_nonnegative(value: Optional[float], field_name: str) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field_name} must be a finite non-negative number")
    return number


def _optional_ratio(value: Optional[float], field_name: str) -> Optional[float]:
    number = _optional_nonnegative(value, field_name)
    if number is not None and number > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return number


def _codes(values, field_name: str) -> tuple[str, ...]:
    result = tuple(str(value) for value in (values or ()))
    if any(not _CODE_RE.fullmatch(value) for value in result):
        raise ValueError(f"{field_name} contains an invalid code")
    return result


def _default_failure_kind(stage: ExtractionStage) -> ExtractionFailureKind:
    return {
        ExtractionStage.METADATA: ExtractionFailureKind.METADATA_FAILED,
        ExtractionStage.SUBTITLE_DOWNLOAD: ExtractionFailureKind.SUBTITLE_DOWNLOAD_FAILED,
        ExtractionStage.SUBTITLE_PARSE: ExtractionFailureKind.SUBTITLE_PARSE_FAILED,
        ExtractionStage.MEDIA_DOWNLOAD: ExtractionFailureKind.MEDIA_DOWNLOAD_FAILED,
        ExtractionStage.MEDIA_VALIDATION: ExtractionFailureKind.MEDIA_VALIDATION_FAILED,
    }[stage]


def classify_extraction_failure(raw_error: object, stage: ExtractionStage) -> ExtractionFailureKind:
    """按稳定信号分类；返回值不包含原始错误文本。"""
    stage = _enum(stage, ExtractionStage, "stage")
    low = str(raw_error or "").lower()
    if any(signal in low for signal in (
        "drm protected", "drm-protected", "digital rights management",
        "encrypted media", "encrypted stream",
    )):
        return ExtractionFailureKind.DRM_PROTECTED
    if any(signal in low for signal in (
        "confirm you're not a bot", "sign in to confirm", "po token", "po_token",
        "challenge", "nsig", "signature solving", "javascript runtime", "ejs",
        "precondition failed",
    )) or re.search(r"\b412\b", low):
        return ExtractionFailureKind.CHALLENGE_REQUIRED
    if re.search(r"\b429\b", low) or any(signal in low for signal in ("too many requests", "rate limit")):
        return ExtractionFailureKind.RATE_LIMITED
    if any(signal in low for signal in (
        "private video", "this video is private", "members-only", "member-only",
        "membership required", "forbidden",
        "not available in your country", "geo-restricted",
    )) or re.search(r"\b403\b", low):
        return ExtractionFailureKind.PERMISSION_DENIED
    if any(signal in low for signal in (
        "login required", "authentication required", "sign in required", "cookies required",
        "cookie required", "unauthorized", "age-restricted", "age restriction",
        "age verification",
    )) or re.search(r"\b401\b", low):
        return ExtractionFailureKind.AUTH_REQUIRED
    return _default_failure_kind(stage)


@dataclass(frozen=True)
class ExtractionFailure:
    """脱敏后的媒体提取失败现场。绝不保存 URL、原始异常或认证材料。"""

    platform: str
    stage: ExtractionStage
    kind: ExtractionFailureKind
    sanitized_summary: str
    yt_dlp_version: Optional[str] = None
    cookie_available: Optional[bool] = None
    deno_available: Optional[bool] = None
    ejs_available: Optional[bool] = None
    attempted_actions: tuple[ExtractionAction, ...] = ()
    cancelled: bool = False

    def __post_init__(self):
        platform = sanitize_diagnostic(self.platform, max_length=64).lower()
        if not platform or not _CODE_RE.fullmatch(platform):
            raise ValueError("platform must be a stable non-empty code")
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "stage", _enum(self.stage, ExtractionStage, "stage"))
        object.__setattr__(self, "kind", _enum(self.kind, ExtractionFailureKind, "kind"))
        summary = sanitize_diagnostic(self.sanitized_summary)
        object.__setattr__(self, "sanitized_summary", summary or "媒体提取失败")
        if self.yt_dlp_version is not None:
            version = sanitize_diagnostic(self.yt_dlp_version, max_length=64) or None
            object.__setattr__(self, "yt_dlp_version", version)
        for field_name in ("cookie_available", "deno_available", "ejs_available"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{field_name} must be bool or None")
        actions = tuple(_enum(action, ExtractionAction, "attempted_actions") for action in self.attempted_actions)
        object.__setattr__(self, "attempted_actions", actions)
        if not isinstance(self.cancelled, bool):
            raise ValueError("cancelled must be bool")
        if self.cancelled != (self.kind is ExtractionFailureKind.CANCELLED):
            raise ValueError("cancelled must agree with failure kind")

    @classmethod
    def from_error(
        cls,
        *,
        platform: str,
        stage: ExtractionStage,
        error: object,
        yt_dlp_version: Optional[str],
        cookie_available: Optional[bool],
        deno_available: Optional[bool],
        ejs_available: Optional[bool],
        attempted_actions: tuple[ExtractionAction, ...],
        kind: Optional[ExtractionFailureKind] = None,
    ) -> "ExtractionFailure":
        resolved_stage = _enum(stage, ExtractionStage, "stage")
        return cls(
            platform=platform,
            stage=resolved_stage,
            kind=kind or classify_extraction_failure(error, resolved_stage),
            sanitized_summary=sanitize_diagnostic(error),
            yt_dlp_version=yt_dlp_version,
            cookie_available=cookie_available,
            deno_available=deno_available,
            ejs_available=ejs_available,
            attempted_actions=attempted_actions,
            cancelled=False,
        )


@dataclass(frozen=True)
class SubtitleFetchResult:
    """字幕探测的显式三态边界；``None`` 不再同时代表缺席和失败。"""

    status: SubtitleFetchStatus
    text: Optional[str] = None
    title: Optional[str] = None
    language: Optional[str] = None
    duration_seconds: float = 0.0
    failure: Optional[ExtractionFailure] = None

    def __post_init__(self):
        status = _enum(self.status, SubtitleFetchStatus, "status")
        object.__setattr__(self, "status", status)
        duration = _optional_nonnegative(self.duration_seconds, "duration_seconds")
        object.__setattr__(self, "duration_seconds", duration or 0.0)
        if status is SubtitleFetchStatus.FOUND:
            if not (self.text or "").strip() or self.failure is not None:
                raise ValueError("found subtitles require non-empty text and no failure")
        elif status is SubtitleFetchStatus.FAILED:
            if self.text is not None or self.failure is None:
                raise ValueError("failed subtitle result requires failure and no text")
        elif self.text is not None or self.failure is not None:
            raise ValueError("absent/skipped subtitle result cannot carry text or failure")


@dataclass(frozen=True)
class RecoveryObservation:
    """未来恢复 Loop 的安全 observation 外壳；不开放任意 data 字典。"""

    action: RecoveryAction
    status: ObservationStatus
    code: str
    sanitized_summary: str
    failure: Optional[ExtractionFailure] = None

    def __post_init__(self):
        action = _enum(self.action, RecoveryAction, "action")
        status = _enum(self.status, ObservationStatus, "status")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "status", status)
        code = str(self.code or "")
        if not _CODE_RE.fullmatch(code):
            raise ValueError("code must be a stable non-empty code")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "sanitized_summary", sanitize_plain_text(self.sanitized_summary))
        if status is ObservationStatus.SUCCESS and self.failure is not None:
            raise ValueError("successful observation cannot carry failure")
        if status is ObservationStatus.CANCELLED:
            if self.failure is None or not self.failure.cancelled:
                raise ValueError("cancelled observation requires a cancelled failure")


@dataclass(frozen=True)
class AudioProfile:
    """确定性音频体检结果；Task 1 仅定义契约，不产生分析数据。"""

    analysis_status: AudioAnalysisStatus = AudioAnalysisStatus.NOT_ANALYZED
    container: Optional[str] = None
    codec: Optional[str] = None
    duration_seconds: Optional[float] = None
    sample_rate_hz: Optional[int] = None
    channels: Optional[int] = None
    bitrate_bps: Optional[int] = None
    rms_amplitude: Optional[float] = None
    peak_amplitude: Optional[float] = None
    clipping_ratio: Optional[float] = None
    low_volume: Optional[bool] = None
    speech_duration_seconds: Optional[float] = None
    speech_ratio: Optional[float] = None
    silence_ratio: Optional[float] = None
    longest_silence_seconds: Optional[float] = None
    integrity_flags: tuple[AudioIntegrityFlag, ...] = ()
    noise_level: Optional[HeuristicLevel] = None
    noise_confidence: Optional[float] = None
    music_level: Optional[HeuristicLevel] = None
    music_confidence: Optional[float] = None
    quality_grade: AudioQualityGrade = AudioQualityGrade.UNKNOWN
    reason_codes: tuple[str, ...] = ()
    analysis_error: Optional[str] = None

    def __post_init__(self):
        status = _enum(self.analysis_status, AudioAnalysisStatus, "analysis_status")
        grade = _enum(self.quality_grade, AudioQualityGrade, "quality_grade")
        object.__setattr__(self, "analysis_status", status)
        object.__setattr__(self, "quality_grade", grade)
        for name in ("duration_seconds", "speech_duration_seconds", "longest_silence_seconds"):
            object.__setattr__(self, name, _optional_nonnegative(getattr(self, name), name))
        for name in ("rms_amplitude", "peak_amplitude", "clipping_ratio", "speech_ratio", "silence_ratio"):
            object.__setattr__(self, name, _optional_ratio(getattr(self, name), name))
        for name in ("sample_rate_hz", "channels", "bitrate_bps"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value <= 0):
                raise ValueError(f"{name} must be a positive integer or None")
        if self.low_volume is not None and not isinstance(self.low_volume, bool):
            raise ValueError("low_volume must be bool or None")
        flags = tuple(_enum(flag, AudioIntegrityFlag, "integrity_flags") for flag in self.integrity_flags)
        object.__setattr__(self, "integrity_flags", flags)
        for prefix in ("noise", "music"):
            level = getattr(self, f"{prefix}_level")
            confidence = getattr(self, f"{prefix}_confidence")
            if level is not None:
                object.__setattr__(self, f"{prefix}_level", _enum(level, HeuristicLevel, f"{prefix}_level"))
            confidence = _optional_ratio(confidence, f"{prefix}_confidence")
            object.__setattr__(self, f"{prefix}_confidence", confidence)
            if (level is None) != (confidence is None):
                raise ValueError(f"{prefix} level and confidence must be provided together")
        reasons = _codes(self.reason_codes, "reason_codes")
        object.__setattr__(self, "reason_codes", reasons)
        if grade is not AudioQualityGrade.UNKNOWN and not reasons:
            raise ValueError("known quality grade requires reason codes")
        if self.analysis_error is not None:
            object.__setattr__(self, "analysis_error", sanitize_diagnostic(self.analysis_error))
            if status not in (AudioAnalysisStatus.PARTIAL, AudioAnalysisStatus.FAILED):
                raise ValueError("analysis_error is only valid for partial/failed analysis")
        measured = (
            self.container, self.codec, self.duration_seconds, self.sample_rate_hz, self.channels,
            self.bitrate_bps, self.rms_amplitude, self.peak_amplitude, self.clipping_ratio,
            self.low_volume, self.speech_duration_seconds, self.speech_ratio, self.silence_ratio,
            self.longest_silence_seconds, self.noise_level, self.music_level,
        )
        if status is AudioAnalysisStatus.NOT_ANALYZED and any(value is not None for value in measured):
            raise ValueError("not_analyzed profile cannot contain measured values")
        if status is AudioAnalysisStatus.NOT_ANALYZED and (flags or grade is not AudioQualityGrade.UNKNOWN):
            raise ValueError("not_analyzed profile cannot claim integrity or quality facts")
        if status is AudioAnalysisStatus.COMPLETE:
            required = (
                self.container, self.codec, self.duration_seconds, self.sample_rate_hz,
                self.channels, self.bitrate_bps, self.rms_amplitude, self.peak_amplitude,
                self.clipping_ratio, self.low_volume, self.speech_duration_seconds,
                self.speech_ratio, self.silence_ratio, self.longest_silence_seconds,
            )
            if any(value is None for value in required):
                raise ValueError("complete audio profile requires all deterministic metrics")
            if grade is AudioQualityGrade.UNKNOWN:
                raise ValueError("complete audio profile requires a traceable quality grade")
        if (
            self.duration_seconds is not None
            and self.speech_duration_seconds is not None
            and self.speech_duration_seconds > self.duration_seconds
        ):
            raise ValueError("speech duration cannot exceed audio duration")
        if (
            self.duration_seconds is not None
            and self.longest_silence_seconds is not None
            and self.longest_silence_seconds > self.duration_seconds
        ):
            raise ValueError("longest silence cannot exceed audio duration")


@dataclass(frozen=True)
class TranscriptionStrategy:
    """宿主白名单内的 Whisper 策略，不能承载任意底层参数。"""

    profile: StrategyProfile
    model_id: str
    language_mode: LanguageMode
    language: Optional[str]
    normalize_volume: bool
    chunk_seconds: float
    overlap_seconds: float
    boundary_profile: ChunkBoundaryProfile
    vad_profile: VadProfile
    decode_profile: DecodeProfile
    max_segment_retries: int
    retry_profile: Optional[StrategyProfile]
    reason_codes: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "profile", _enum(self.profile, StrategyProfile, "profile"))
        model_id = sanitize_diagnostic(self.model_id, max_length=128)
        if not model_id or model_id.startswith(("/", "\\")) or ".." in model_id:
            raise ValueError("model_id must identify a host-approved installed model")
        object.__setattr__(self, "model_id", model_id)
        mode = _enum(self.language_mode, LanguageMode, "language_mode")
        object.__setattr__(self, "language_mode", mode)
        language = (self.language or "").strip() or None
        if mode is LanguageMode.EXPLICIT and language is None:
            raise ValueError("explicit language mode requires language")
        if mode is LanguageMode.AUTO and language is not None:
            raise ValueError("auto language mode cannot carry language")
        object.__setattr__(self, "language", language)
        if not isinstance(self.normalize_volume, bool):
            raise ValueError("normalize_volume must be bool")
        chunk = _optional_nonnegative(self.chunk_seconds, "chunk_seconds")
        overlap = _optional_nonnegative(self.overlap_seconds, "overlap_seconds")
        if not chunk or overlap is None or overlap >= chunk:
            raise ValueError("chunk_seconds must be positive and overlap must be smaller")
        object.__setattr__(self, "chunk_seconds", chunk)
        object.__setattr__(self, "overlap_seconds", overlap)
        object.__setattr__(self, "boundary_profile", _enum(self.boundary_profile, ChunkBoundaryProfile, "boundary_profile"))
        object.__setattr__(self, "vad_profile", _enum(self.vad_profile, VadProfile, "vad_profile"))
        object.__setattr__(self, "decode_profile", _enum(self.decode_profile, DecodeProfile, "decode_profile"))
        if not isinstance(self.max_segment_retries, int) or not 0 <= self.max_segment_retries <= 1:
            raise ValueError("max_segment_retries must be 0 or 1")
        retry = self.retry_profile
        if retry is not None:
            retry = _enum(retry, StrategyProfile, "retry_profile")
        if self.max_segment_retries == 0 and retry is not None:
            raise ValueError("retry_profile requires a retry budget")
        if self.max_segment_retries > 0 and retry is None:
            raise ValueError("retry budget requires retry_profile")
        object.__setattr__(self, "retry_profile", retry)
        reasons = _codes(self.reason_codes, "reason_codes")
        if not reasons:
            raise ValueError("transcription strategy requires structured reasons")
        object.__setattr__(self, "reason_codes", reasons)

    @classmethod
    def current_default(cls, model_id: str) -> "TranscriptionStrategy":
        """精确表达当前 10 分钟分块路径；本轮不把它传给 Transcriber。"""
        return cls(
            profile=StrategyProfile.DEFAULT,
            model_id=model_id,
            language_mode=LanguageMode.AUTO,
            language=None,
            normalize_volume=False,
            chunk_seconds=600.0,
            overlap_seconds=0.0,
            boundary_profile=ChunkBoundaryProfile.CURRENT_DEFAULT,
            vad_profile=VadProfile.CURRENT_DEFAULT,
            decode_profile=DecodeProfile.CURRENT_DEFAULT,
            max_segment_retries=0,
            retry_profile=None,
            reason_codes=("current_default",),
        )


@dataclass(frozen=True)
class TimeRange:
    start_seconds: float
    end_seconds: float

    def __post_init__(self):
        start = _optional_nonnegative(self.start_seconds, "start_seconds")
        end = _optional_nonnegative(self.end_seconds, "end_seconds")
        if start is None or end is None or end <= start:
            raise ValueError("time range must satisfy 0 <= start < end")
        object.__setattr__(self, "start_seconds", start)
        object.__setattr__(self, "end_seconds", end)


@dataclass(frozen=True)
class QualityFinding:
    code: QualityFindingCode
    evidence: EvidenceKind
    ranges: tuple[TimeRange, ...] = ()
    count: Optional[int] = None

    def __post_init__(self):
        object.__setattr__(self, "code", _enum(self.code, QualityFindingCode, "code"))
        object.__setattr__(self, "evidence", _enum(self.evidence, EvidenceKind, "evidence"))
        ranges = tuple(self.ranges)
        if any(not isinstance(time_range, TimeRange) for time_range in ranges):
            raise ValueError("finding ranges must contain TimeRange values")
        object.__setattr__(self, "ranges", ranges)
        if self.count is not None and (not isinstance(self.count, int) or self.count < 1):
            raise ValueError("finding count must be a positive integer")


@dataclass(frozen=True)
class TranscriptRetryRecord:
    time_range: TimeRange
    before_findings: tuple[QualityFindingCode, ...]
    after_findings: tuple[QualityFindingCode, ...]
    selected: FinalTranscriptSelection

    def __post_init__(self):
        if not isinstance(self.time_range, TimeRange):
            raise ValueError("retry time_range must be a TimeRange")
        before = tuple(_enum(code, QualityFindingCode, "before_findings") for code in self.before_findings)
        after = tuple(_enum(code, QualityFindingCode, "after_findings") for code in self.after_findings)
        selected = _enum(self.selected, FinalTranscriptSelection, "selected")
        if selected is FinalTranscriptSelection.NOT_APPLICABLE:
            raise ValueError("retry record must select original or retry")
        object.__setattr__(self, "before_findings", before)
        object.__setattr__(self, "after_findings", after)
        object.__setattr__(self, "selected", selected)


@dataclass(frozen=True)
class TranscriptQualityReport:
    """转录复核结果，显式区分确定事实、启发式信号和未知指标。"""

    evaluation_status: QualityEvaluationStatus = QualityEvaluationStatus.NOT_EVALUATED
    audio_duration_seconds: Optional[float] = None
    speech_duration_seconds: Optional[float] = None
    segment_count: Optional[int] = None
    coverage_ratio: Optional[float] = None
    findings: tuple[QualityFinding, ...] = ()
    suspicious_ranges: tuple[TimeRange, ...] = ()
    unavailable_metrics: tuple[str, ...] = ()
    retry_records: tuple[TranscriptRetryRecord, ...] = ()
    final_selection: FinalTranscriptSelection = FinalTranscriptSelection.NOT_APPLICABLE

    def __post_init__(self):
        status = _enum(self.evaluation_status, QualityEvaluationStatus, "evaluation_status")
        selection = _enum(self.final_selection, FinalTranscriptSelection, "final_selection")
        object.__setattr__(self, "evaluation_status", status)
        object.__setattr__(self, "final_selection", selection)
        for name in ("audio_duration_seconds", "speech_duration_seconds"):
            object.__setattr__(self, name, _optional_nonnegative(getattr(self, name), name))
        object.__setattr__(self, "coverage_ratio", _optional_ratio(self.coverage_ratio, "coverage_ratio"))
        if self.segment_count is not None and (not isinstance(self.segment_count, int) or self.segment_count < 0):
            raise ValueError("segment_count must be a non-negative integer or None")
        findings = tuple(self.findings)
        ranges = tuple(self.suspicious_ranges)
        retries = tuple(self.retry_records)
        if any(not isinstance(finding, QualityFinding) for finding in findings):
            raise ValueError("findings must contain QualityFinding values")
        if any(not isinstance(time_range, TimeRange) for time_range in ranges):
            raise ValueError("suspicious_ranges must contain TimeRange values")
        if any(not isinstance(record, TranscriptRetryRecord) for record in retries):
            raise ValueError("retry_records must contain TranscriptRetryRecord values")
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "suspicious_ranges", ranges)
        object.__setattr__(self, "retry_records", retries)
        object.__setattr__(self, "unavailable_metrics", _codes(self.unavailable_metrics, "unavailable_metrics"))
        if self.audio_duration_seconds is not None:
            duration = self.audio_duration_seconds
            all_ranges = list(ranges)
            all_ranges.extend(r for finding in findings for r in finding.ranges)
            all_ranges.extend(record.time_range for record in retries)
            if any(r.end_seconds > duration for r in all_ranges):
                raise ValueError("quality report range exceeds audio duration")
        if status is QualityEvaluationStatus.NOT_EVALUATED:
            measured = (
                self.audio_duration_seconds,
                self.speech_duration_seconds,
                self.segment_count,
                self.coverage_ratio,
            )
            if (
                any(value is not None for value in measured)
                or findings
                or ranges
                or retries
                or selection is not FinalTranscriptSelection.NOT_APPLICABLE
            ):
                raise ValueError("not_evaluated report cannot claim metrics, findings, retries or selection")
        elif selection is FinalTranscriptSelection.NOT_APPLICABLE:
            raise ValueError("evaluated report must identify the selected transcript")
        if status is QualityEvaluationStatus.PASSED and findings:
            raise ValueError("passed report cannot contain quality findings")


@dataclass(frozen=True)
class TranscriptionOutcome:
    """转录阶段的统一结果；文本保持现有 Markdown 格式。"""

    transcript: str
    strategy: TranscriptionStrategy
    quality_report: TranscriptQualityReport

    def __post_init__(self):
        if not isinstance(self.transcript, str):
            raise ValueError("transcript must be text")
        if not isinstance(self.strategy, TranscriptionStrategy):
            raise ValueError("strategy must be a TranscriptionStrategy")
        if not isinstance(self.quality_report, TranscriptQualityReport):
            raise ValueError("quality_report must be a TranscriptQualityReport")
