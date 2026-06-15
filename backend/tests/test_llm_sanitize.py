"""llm_sanitize 的单元测试：尾部寒暄剥离、转录优化过程说明剥离。"""
from __future__ import annotations

from llm_sanitize import strip_llm_artifacts, strip_transcript_optimization_output


class TestStripLlmArtifacts:
    def test_none_and_empty(self):
        assert strip_llm_artifacts(None) == ""
        assert strip_llm_artifacts("") == ""

    def test_falsy_non_string_returns_empty(self):
        # 仅 None/falsy 走兜底；契约只针对 Optional[str]。
        assert strip_llm_artifacts(0) == ""  # type: ignore[arg-type]
        assert strip_llm_artifacts([]) == ""  # type: ignore[arg-type]

    def test_plain_text_unchanged(self):
        text = "第一段正文。\n\n第二段正文。"
        assert strip_llm_artifacts(text) == text

    def test_strips_trailing_english_closer(self):
        text = "Here is the summary body.\n\nLet me know if you need anything else!"
        assert strip_llm_artifacts(text) == "Here is the summary body."

    def test_strips_trailing_chinese_closer(self):
        text = "这是正文内容。\n\n如有需要，请随时告诉我。"
        assert strip_llm_artifacts(text) == "这是正文内容。"

    def test_strips_feel_free_block(self):
        text = "Body text.\n\nFeel free to ask follow-up questions."
        assert strip_llm_artifacts(text) == "Body text."

    def test_keeps_body_when_closer_in_middle(self):
        # 寒暄只在结尾才剥离，正文中的同类措辞应保留。
        text = "Let me know is a phrase.\n\n真正的正文在这里。"
        assert "真正的正文在这里。" in strip_llm_artifacts(text)


class TestStripTranscriptOptimizationOutput:
    def test_empty(self):
        assert strip_transcript_optimization_output(None) == ""

    def test_strips_chinese_leading_preamble(self):
        text = "以下是优化后的转录文本：\n\n实际的转录正文。"
        assert strip_transcript_optimization_output(text) == "实际的转录正文。"

    def test_strips_english_leading_preamble(self):
        text = "Here is the optimized transcript:\n\nThe real transcript body."
        assert strip_transcript_optimization_output(text) == "The real transcript body."

    def test_strips_think_block(self):
        text = "<think>模型在这里思考过程</think>\n正文内容。"
        assert strip_transcript_optimization_output(text) == "正文内容。"

    def test_drops_meta_lines(self):
        text = "正文第一句。\n说明：我修正了若干错别字。\n正文第二句。"
        out = strip_transcript_optimization_output(text)
        assert "说明：" not in out
        assert "正文第一句。" in out
        assert "正文第二句。" in out

    def test_plain_transcript_unchanged(self):
        text = "这是一段干净的转录文本，没有任何过程说明。"
        assert strip_transcript_optimization_output(text) == text
