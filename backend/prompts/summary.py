"""摘要阶段提示词：把各摘要角色绑定到「任务层」（user 侧）。

角色（含规则与输出契约）见 ``roles``：
- ``SINGLE``      → ``roles.SUMMARY_EDITOR``
- ``CHUNK``       → ``roles.SECTION_SUMMARIZER``
- ``INTEGRATE``   → ``roles.SUMMARY_INTEGRATOR``
- ``TWO_STEP_1``  → ``roles.SUMMARY_PROMPT_DESIGNER``（生成定制化摘要 Prompt）
- ``TWO_STEP_2``  → ``roles.SUMMARY_EXECUTOR``（人设由 Step 1 的 ``custom_prompt`` 充当）

变量：``language_name`` 通用；``transcript`` / ``chunk`` / ``part`` / ``total`` /
``combined_summaries`` / ``preview`` / ``custom_prompt`` / ``transcript_for_summary``
按调用各取所需。
"""
from __future__ import annotations

from . import Layer, Prompt
from . import roles

# ── 单文本摘要 ──
SINGLE = Prompt(
    name="summary.single",
    role=roles.SUMMARY_EDITOR,
    task_layers=(
        Layer(
            "input",
            "Summarize the following content in {language_name}. Follow the system rules strictly "
            "(brief executive summary, no meta-commentary):\n\n{transcript}",
        ),
    ),
    temperature=0.25,
    max_tokens=4000,
)

# ── 分段摘要 ──
CHUNK = Prompt(
    name="summary.chunk",
    role=roles.SECTION_SUMMARIZER,
    task_layers=(
        Layer(
            "input",
            "[Part {part}/{total}] Summarize in {language_name} (80–160 words, tight prose):\n\n"
            "{chunk}\n\nPut the summary inside <summary>...</summary>.",
        ),
    ),
    temperature=0.25,
    max_tokens=2000,
)

# ── 整合分段摘要 ──
INTEGRATE = Prompt(
    name="summary.integrate",
    role=roles.SUMMARY_INTEGRATOR,
    task_layers=(
        Layer(
            "input",
            "Merge the following partial summaries into one executive summary in {language_name}:\n\n"
            "{combined_summaries}",
        ),
    ),
    temperature=0.25,
    max_tokens=4000,
)

# ── 双步摘要 Step 1：生成定制化 Prompt ──
TWO_STEP_1 = Prompt(
    name="summary.two_step.step1",
    role=roles.SUMMARY_PROMPT_DESIGNER,
    task_layers=(
        Layer(
            "input",
            "请阅读以下内容，然后为该内容设计一个量身定制的摘要生成Prompt：\n\n"
            "---\n{preview}\n---\n\n"
            "请输出定制化的摘要Prompt（用{language_name}）：",
        ),
    ),
    temperature=0.3,
    max_tokens=4000,
)

# ── 双步摘要 Step 2：以 Step 1 产出的 custom_prompt 为人设生成摘要 ──
TWO_STEP_2 = Prompt(
    name="summary.two_step.step2",
    role=roles.SUMMARY_EXECUTOR,
    task_layers=(
        Layer("input", "请根据系统提示词，直接总结以下原文内容：\n\n{transcript_for_summary}"),
    ),
    temperature=0.25,
    max_tokens=4000,
)
