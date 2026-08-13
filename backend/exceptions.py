"""领域异常：用类型化的异常替代到处 ``raise Exception(...)``。

路由层可据此把不同失败映射为合适的 HTTP 状态码（见 ``routers`` 中的处理），
而不是把所有错误都压成 500。每个异常都带一个 ``http_status`` 供路由统一映射。
"""
from __future__ import annotations


class TranscriberError(Exception):
    """转录/摘要管线相关错误的基类。"""

    http_status: int = 500


class SourceError(TranscriberError):
    """输入来源无法获取或无可处理内容（用户侧问题，4xx）。"""

    http_status = 400


class MediaExtractionError(SourceError):
    """携带脱敏 ``ExtractionFailure`` 的媒体获取错误。"""

    def __init__(self, failure, *, previous_failures=()):
        from media_contracts import ExtractionFailure

        if not isinstance(failure, ExtractionFailure):
            raise TypeError("failure must be an ExtractionFailure")
        previous = tuple(previous_failures)
        if any(not isinstance(item, ExtractionFailure) for item in previous):
            raise TypeError("previous_failures must contain ExtractionFailure values")
        self.failure = failure
        self.previous_failures = previous
        super().__init__(failure.sanitized_summary)


class MediaRecoveryActionRequired(SourceError):
    """恢复 Loop 已结束，任务需要固定的用户动作后重新入队。"""

    def __init__(self, result):
        from media_recovery import RecoveryResult, RecoveryRunStatus

        if not isinstance(result, RecoveryResult) or result.status is not RecoveryRunStatus.ACTION_REQUIRED:
            raise TypeError("result must be an action_required RecoveryResult")
        self.result = result
        super().__init__(result.message)


class UnsupportedSourceError(SourceError):
    """不支持的来源类型 / 文件类型。"""

    http_status = 415


class TranscriptionError(TranscriberError):
    """音频转文字阶段失败（ASR 后端错误，服务端 5xx）。"""

    http_status = 502


class LLMError(TranscriberError):
    """LLM 调用失败或超时（上游模型错误，5xx）。"""

    http_status = 502
