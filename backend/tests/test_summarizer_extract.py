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


class TestStripSummaryScaffolding:
    def test_drops_part_marker_lines(self, s):
        raw = "[Part 1]\nHost examines Q2 reports.\n\n[Part 2]\nManagers split on AI."
        assert s._strip_summary_scaffolding(raw) == (
            "Host examines Q2 reports.\n\nManagers split on AI."
        )

    def test_drops_inline_part_prefix(self, s):
        raw = "[Part 1] Host examines Q2 reports."
        assert s._strip_summary_scaffolding(raw) == "Host examines Q2 reports."

    def test_drops_raw_chunk_fallback_paragraphs(self, s):
        raw = (
            "A usable takeaway about scale rankings.\n\n"
            "第2部分内容概述：那我觉得这里面\n\n可能有一部分是因为PCB芯片...\n\n"
            "Another usable takeaway."
        )
        cleaned = s._strip_summary_scaffolding(raw)
        assert "第2部分内容概述" not in cleaned
        assert "PCB芯片" not in cleaned
        assert "usable takeaway" in cleaned

    def test_empty_and_none(self, s):
        assert s._strip_summary_scaffolding("") == ""
        assert s._strip_summary_scaffolding(None) == ""


class TestPrepareSummarySource:
    def test_merges_subtitle_fragments(self, s):
        raw = "哈喽大家好\n\n欢迎来到播客\n\n今天聊公募基金二季报"
        compact = s._prepare_summary_source(raw)
        assert compact == "哈喽大家好欢迎来到播客今天聊公募基金二季报"
        assert "\n\n" not in compact

    def test_keeps_paragraph_breaks_when_long(self, s):
        first = "甲" * 200
        second = "乙" * 200
        compact = s._prepare_summary_source(f"{first}\n\n{second}")
        assert first in compact
        assert second in compact
        assert "\n\n" in compact


class _FakeResponses:
    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []

    def create(self, **kwargs):
        from types import SimpleNamespace
        self.calls.append(kwargs)
        content = self.queue.pop(0) if self.queue else ""
        return SimpleNamespace(output_text=content, output=[], status="completed")


class _FakeClient:
    def __init__(self, queue):
        self.responses = _FakeResponses(queue)


def _summarizer_with_client(queue) -> Summarizer:
    s = Summarizer()
    s.client = _FakeClient(queue)
    s.fast_model = "dummy"
    s.advanced_model = "dummy"
    return s


class TestSummarizeWithChunks:
    def test_skips_empty_chunks_and_never_leaks_part_markers(self):
        s = _summarizer_with_client([
            "",
            "<summary>Managers split between AI and dividend styles.</summary>",
            "",
            "",  # integrate unused when only one success
        ])
        s._smart_chunk_text = lambda text, max_chars_per_chunk=4000: ["aaa", "bbb", "ccc"]
        out = s._summarize_with_chunks("long transcript", "en", "Q2 funds", 4000)
        assert "[Part" not in out
        assert "第" not in out or "部分内容概述" not in out
        assert "Managers split between AI and dividend styles." in out
        assert out.startswith("# Q2 funds")

    def test_all_chunks_empty_uses_fallback_not_raw_excerpt(self):
        s = _summarizer_with_client(["", "", ""])
        s._smart_chunk_text = lambda text, max_chars_per_chunk=4000: ["raw one", "raw two"]
        out = s._summarize_with_chunks("long transcript", "en", "Q2 funds", 4000)
        assert "raw one" not in out
        assert "部分内容概述" not in out
        assert "[Part" not in out
        assert "Q2 funds" in out

    def test_failed_integrate_joins_without_scaffolding(self):
        s = _summarizer_with_client([
            "<summary>First takeaway about scale.</summary>",
            "<summary>Second takeaway about crowding.</summary>",
            "",  # integrate empty
        ])
        s._smart_chunk_text = lambda text, max_chars_per_chunk=4000: ["aaa", "bbb"]
        out = s._summarize_with_chunks("long transcript", "en", "Q2 funds", 4000)
        assert "[Part" not in out
        assert "First takeaway about scale." in out
        assert "Second takeaway about crowding." in out


class TestFormatSummaryWithMeta:
    def test_strips_scaffolding_before_title(self, s):
        raw = "[Part 1]\nA clean paragraph.\n\n第2部分内容概述：原文碎片"
        out = s._format_summary_with_meta(raw, "en", "Episode")
        assert out == "# Episode\n\nA clean paragraph."
