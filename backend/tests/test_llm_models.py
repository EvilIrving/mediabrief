from llm_models import (
    DEFAULT_LLM_MODEL,
    DEFAULT_WINDOW,
    FLASH_WINDOW,
    chunk_char_limit,
    resolve_max_output_tokens,
    resolve_model_window,
    summarize_input_budget,
)


def test_default_model_is_flash():
    assert DEFAULT_LLM_MODEL == "deepseek-v4-flash"


def test_flash_window():
    window = resolve_model_window("deepseek-v4-flash")
    assert window == FLASH_WINDOW
    assert window.context_tokens == 1_000_000
    assert window.max_output_tokens == 384_000


def test_empty_model_uses_flash_window():
    assert resolve_model_window("") == FLASH_WINDOW
    assert resolve_model_window(None) == FLASH_WINDOW


def test_unknown_model_uses_conservative_window():
    assert resolve_model_window("gpt-4o") == DEFAULT_WINDOW


def test_flash_max_output_is_window_max():
    assert resolve_max_output_tokens("deepseek-v4-flash") == 384_000
    assert resolve_max_output_tokens("") == 384_000


def test_flash_budget_avoids_chunking_typical_podcast():
    budget = summarize_input_budget("deepseek-v4-flash")
    assert budget == 1_000_000 - 384_000 - 4_000
    # 90 分钟中文播客大约 15 万字，保守估算也远低于 flash 窗口
    assert budget > 150_000 * 2


def test_flash_chunk_chars_are_window_sized():
    assert chunk_char_limit("deepseek-v4-flash") > 200_000
    assert chunk_char_limit("unknown-small-model") < chunk_char_limit("deepseek-v4-flash")
