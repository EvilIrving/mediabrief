"""转录阶段提示词：把转录角色绑定到「任务层」（user 侧）。

角色定义见 ``roles.TRANSCRIPT_ANALYST`` / ``TRANSCRIPT_EDITOR_ZH`` / ``TRANSCRIPT_EDITOR_EN``
（含分析/优化的全部行为准则与输出契约——这些是角色恒定的「怎么做」，归 system）；
这里只声明用户侧的「做什么 + 输入什么」。

变量：``title_hint`` / ``sample``（预分析），``domain_block`` / ``chunk_text``（优化）。
``domain_block`` 由调用方拼好整段或传空串；空串时该层在合并时被自动跳过。
"""
from __future__ import annotations

from . import Layer, Prompt
from . import roles

# ── 领域预分析任务层 ──
_DOMAIN_INPUT = Layer(
    "input",
    "请分析以下转录采样，输出领域与纠偏约束：{title_hint}\n\n---\n{sample}\n---",
)

DOMAIN_INFER = Prompt(
    name="transcript.domain_infer",
    role=roles.TRANSCRIPT_ANALYST,
    task_layers=(_DOMAIN_INPUT,),
    temperature=0.15,
    max_tokens=450,
)

# ── 单块优化任务层（中/英共用结构，仅输入提示语不同） ──
# 领域约束作为可选上下文层；空串时在合并时被自动跳过。
_OPT_DOMAIN = Layer("domain", "{domain_block}")
_OPT_INPUT_ZH = Layer("input", "原始转录文本：\n{chunk_text}")
_OPT_INPUT_EN = Layer("input", "Original transcript text:\n{chunk_text}")

OPTIMIZE_ZH = Prompt(
    name="transcript.optimize.zh",
    role=roles.TRANSCRIPT_EDITOR_ZH,
    task_layers=(_OPT_DOMAIN, _OPT_INPUT_ZH),
    temperature=0.1,
    max_tokens=8000,
)

OPTIMIZE_EN = Prompt(
    name="transcript.optimize.en",
    role=roles.TRANSCRIPT_EDITOR_EN,
    task_layers=(_OPT_DOMAIN, _OPT_INPUT_EN),
    temperature=0.1,
    max_tokens=8000,
)
