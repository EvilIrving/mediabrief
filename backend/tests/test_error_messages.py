"""error_messages 的单元测试：签名匹配、领域异常透传、code/文案一致性。"""
from __future__ import annotations

import pytest

from error_messages import (
    _SIGNATURES,
    _SIGNATURE_CODES,
    humanize_error,
    humanize_error_code,
)
from exceptions import (
    LLMError,
    SourceError,
    TranscriberError,
    TranscriptionError,
    UnsupportedSourceError,
)


class TestHumanizeError:
    def test_domain_error_passthrough(self):
        # 我们自己的领域异常信息已友好，应原样透传。
        assert humanize_error(LLMError("模型超时，请稍后重试")) == "模型超时，请稍后重试"

    @pytest.mark.parametrize(
        "raw, needle",
        [
            ("ERROR: Sign in to confirm you're not a bot", "登录验证"),
            ("HTTP Error 429: Too Many Requests", "限流"),
            ("Requested format is not available", "可用格式"),
            ("Operation timed out", "超时"),
            ("Postprocessing: Invalid argument", "音频转换失败"),
        ],
    )
    def test_signature_match(self, raw, needle):
        assert needle in humanize_error(Exception(raw))

    def test_match_is_case_insensitive(self):
        assert humanize_error(Exception("VIDEO UNAVAILABLE")) == humanize_error(
            Exception("video unavailable")
        )

    def test_unmatched_keeps_truncated_raw(self):
        msg = humanize_error(Exception("某种我们没见过的底层错误 xyz"))
        assert msg.startswith("处理失败：")
        assert "xyz" in msg

    def test_unmatched_long_message_truncated(self):
        long = "x" * 500
        msg = humanize_error(Exception(long))
        assert msg.endswith("…")
        assert len(msg) < 250

    def test_empty_message_fallback(self):
        assert humanize_error(Exception("")) == "处理失败，请稍后重试。"


class TestHumanizeErrorCode:
    @pytest.mark.parametrize(
        "exc, code",
        [
            (UnsupportedSourceError("x"), "unsupported_source"),
            (SourceError("x"), "source_unavailable"),
            (TranscriptionError("x"), "transcription_failed"),
            (LLMError("x"), "llm_failed"),
            (TranscriberError("x"), "generic"),
        ],
    )
    def test_domain_exception_codes(self, exc, code):
        assert humanize_error_code(exc) == code

    @pytest.mark.parametrize(
        "raw, code",
        [
            ("Sign in to confirm", "auth_required"),
            ("HTTP Error 403", "auth_required"),
            ("HTTP Error 429", "rate_limited"),
            ("Connection refused", "network"),
            ("ffmpeg not found", "ffmpeg_failed"),
        ],
    )
    def test_signature_codes(self, raw, code):
        assert humanize_error_code(Exception(raw)) == code

    def test_unknown_is_generic(self):
        assert humanize_error_code(Exception("完全陌生的错误")) == "generic"


def test_signature_tables_stay_in_sync():
    # 两张表必须同序、同 needle，否则文案与 code 会错位。
    assert [n for n, _ in _SIGNATURES] == [n for n, _ in _SIGNATURE_CODES]
