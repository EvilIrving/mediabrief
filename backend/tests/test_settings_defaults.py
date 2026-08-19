from llm_models import DEFAULT_LLM_MODEL
from settings_store import _validate


def test_empty_model_becomes_flash():
    settings = _validate({"model": ""})
    assert settings.model == DEFAULT_LLM_MODEL


def test_thinking_defaults_on_two_step_on():
    settings = _validate({})
    assert settings.useThinking is True
    assert settings.useTwoStep is True
    assert settings.model == DEFAULT_LLM_MODEL


def test_thinking_false_is_kept():
    settings = _validate({"useThinking": False})
    assert settings.useThinking is False
