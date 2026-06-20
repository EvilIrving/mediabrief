"""翻译阶段提示词：把翻译角色绑定到「任务层」（user 侧）。

角色定义见 ``roles.TRANSLATOR`` / ``roles.TRANSLATOR_CHUNK``（含翻译规则与输出契约）；
这里只声明用户侧要给出的任务说明与输入。single / chunk 共用同一组任务层（输入统一用
``{text}`` 占位）。变量：``source_lang_name`` / ``target_lang_name`` / ``text`` /
``part`` / ``total``。
"""
from __future__ import annotations

from . import Layer, Prompt
from . import roles

# ── 任务层（user）：single / chunk 共用 ──
_INSTRUCTION = Layer("instruction", "请将以下{source_lang_name}文本翻译为{target_lang_name}：")
_INPUT = Layer("input", "{text}")
_OUTPUT_REMINDER = Layer("output_reminder", "把翻译结果放在 <translation>...</translation> 内。")

_TASK_LAYERS = (_INSTRUCTION, _INPUT, _OUTPUT_REMINDER)


SINGLE = Prompt(
    name="translate.single",
    role=roles.TRANSLATOR,
    task_layers=_TASK_LAYERS,
    temperature=0.1,
    max_tokens=8000,
)

CHUNK = Prompt(
    name="translate.chunk",
    role=roles.TRANSLATOR_CHUNK,
    task_layers=_TASK_LAYERS,
    temperature=0.1,
    max_tokens=8000,
)
