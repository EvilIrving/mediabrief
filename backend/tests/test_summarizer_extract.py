"""Summarizer 输出提取的单元测试：转录优化的 schema/标签/回退三级降级。

不触网：Summarizer() 不带 key 时 client 为 None，被测方法均为纯解析逻辑。
"""
from __future__ import annotations

import openai
import pytest

from summarizer import Summarizer


@pytest.fixture
def s() -> Summarizer:
    return Summarizer()  # 无 API key → client=None，不会发起请求


class TestExtractOptimizedText:
    def test_json_schema_paragraphs(self, s):
        raw = '{"paragraphs": ["第一段", "第二段"]}'
        assert s._extract_optimized_text(raw) == "第一段\n\n第二段"

    def test_json_paragraphs_skip_blank(self, s):
        raw = '{"paragraphs": ["有内容", "   ", ""]}'
        assert s._extract_optimized_text(raw) == "有内容"

    def test_transcript_tag_drops_surrounding_meta(self, s):
        raw = (
            "Detected Language: en\n"
            "<transcript>正文一\n\n正文二</transcript>\n"
            "以上是优化结果"
        )
        assert s._extract_optimized_text(raw) == "正文一\n\n正文二"

    def test_truncated_open_tag(self, s):
        raw = "<transcript>被截断的正文没有闭合"
        assert s._extract_optimized_text(raw) == "被截断的正文没有闭合"

    def test_plaintext_falls_back_to_strip(self, s):
        # 既非 JSON 也无标签：回退到旧黑名单清洗，剥离前言。
        raw = "以下是优化后的转录文本：\n\n真正的正文。"
        assert s._extract_optimized_text(raw) == "真正的正文。"

    def test_empty(self, s):
        assert s._extract_optimized_text("") == ""
        assert s._extract_optimized_text(None) == ""


class TestIsUnsupportedSchemaError:
    def test_bad_request_mentioning_response_format_is_recoverable(self, s):
        exc = openai.BadRequestError.__new__(openai.BadRequestError)
        Exception.__init__(exc, "Unknown parameter: 'response_format.json_schema'")
        assert s._is_unsupported_schema_error(exc) is True

    def test_unrelated_bad_request_not_recoverable(self, s):
        exc = openai.BadRequestError.__new__(openai.BadRequestError)
        Exception.__init__(exc, "context length exceeded")
        assert s._is_unsupported_schema_error(exc) is False

    def test_generic_exception_not_recoverable(self, s):
        assert s._is_unsupported_schema_error(ValueError("response_format")) is False
