"""LLM 模型目录：默认模型、上下文窗口，以及摘要分块预算。

flash 的窗口以当前 DeepSeek V4 Flash 为准：上下文 1M、输出上限 384K。
输出按窗口上限预留，给 High 思考留足 reasoning token；输入仍远大于普通播客。
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LLM_MODEL = "deepseek-v4-flash"

_SYSTEM_PROMPT_RESERVE = 4_000
_MIN_INPUT_BUDGET = 8_000
_MIN_CHUNK_CHARS = 4_000
# 与 Summarizer._estimate_tokens 同一套保守换算：tokens ≈ 1.65 * chars + 2500
_ESTIMATE_CHAR_WEIGHT = 1.65
_ESTIMATE_FIXED = 2_500


@dataclass(frozen=True)
class ModelWindow:
    context_tokens: int
    max_output_tokens: int


FLASH_WINDOW = ModelWindow(context_tokens=1_000_000, max_output_tokens=384_000)
DEFAULT_WINDOW = ModelWindow(context_tokens=128_000, max_output_tokens=8_192)

_WINDOWS = {
    DEFAULT_LLM_MODEL: FLASH_WINDOW,
}


def normalize_model_id(model_id: str | None) -> str:
    return (model_id or "").strip() or DEFAULT_LLM_MODEL


def resolve_model_window(model_id: str | None) -> ModelWindow:
    key = (model_id or "").strip().lower()
    if not key:
        return FLASH_WINDOW
    if key in _WINDOWS:
        return _WINDOWS[key]
    if "flash" in key:
        return FLASH_WINDOW
    return DEFAULT_WINDOW


def resolve_max_output_tokens(model_id: str | None) -> int:
    """单次调用的输出上限，含思考 token。"""
    return resolve_model_window(model_id).max_output_tokens


def summarize_input_budget(model_id: str | None) -> int:
    """单次摘要可喂给模型的输入 token 上限（已扣除输出和 system 预留）。"""
    window = resolve_model_window(model_id)
    return max(
        _MIN_INPUT_BUDGET,
        window.context_tokens - window.max_output_tokens - _SYSTEM_PROMPT_RESERVE,
    )


def chunk_char_limit(model_id: str | None) -> int:
    """分块时每块的字符上限，由输入预算反推。"""
    usable = int(summarize_input_budget(model_id) * 0.85)
    chars = int((usable - _ESTIMATE_FIXED) / _ESTIMATE_CHAR_WEIGHT)
    return max(_MIN_CHUNK_CHARS, chars)
