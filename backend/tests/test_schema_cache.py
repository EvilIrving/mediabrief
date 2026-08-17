"""JSON Output 探测缓存：Responses API 的 text.format=json_object。"""
from __future__ import annotations

from unittest import mock

import pytest

from llm_client import LLMCompletion
from summarizer import (
    _schema_cache,
    _schema_cache_lock,
    _get_schema_support,
    _set_schema_support,
    Summarizer,
)


@pytest.fixture(autouse=True)
def clear_cache():
    with _schema_cache_lock:
        _schema_cache.clear()
    yield
    with _schema_cache_lock:
        _schema_cache.clear()


def make_summarizer(model="test-model", base_url=None, api_key="sk-test"):
    s = Summarizer(api_key=api_key, base_url=base_url or "", model=model)
    s.client = mock.MagicMock()
    return s


class TestGetSetSchemaSupport:
    def test_get_none_when_empty(self):
        assert _get_schema_support("m", "u") is None

    def test_set_and_get(self):
        _set_schema_support("m", "u", True)
        assert _get_schema_support("m", "u") is True

    def test_set_and_get_false(self):
        _set_schema_support("m", "u", False)
        assert _get_schema_support("m", "u") is False


class TestChatOptimizeWithJsonObject:
    def test_unknown_probes_and_caches_success(self):
        s = make_summarizer()
        fake = LLMCompletion(text='{"paragraphs":["hi"]}')
        with mock.patch("summarizer.complete_model", return_value=fake) as create:
            r1 = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
            assert r1 is fake
            assert create.call_count == 1
            assert create.call_args.kwargs["json_object"] is True
            assert _get_schema_support("test-model", "None") is True

            r2 = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
            assert r2 is fake
            assert create.call_count == 2
            assert create.call_args.kwargs["json_object"] is True

    def test_unknown_probes_and_caches_unsupported(self):
        from openai import BadRequestError

        s = make_summarizer()
        fallback = LLMCompletion(text="plain")
        with mock.patch(
            "summarizer.complete_model",
            side_effect=[
                BadRequestError("json_object unavailable", response=mock.MagicMock(), body={}),
                fallback,
            ],
        ) as create:
            r1 = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
            assert r1 is fallback
            assert create.call_count == 2
            assert create.call_args_list[0].kwargs["json_object"] is True
            assert create.call_args_list[1].kwargs["json_object"] is False
            assert _get_schema_support("test-model", "None") is False

            create.reset_mock()
            create.side_effect = None
            create.return_value = fallback
            r2 = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
            assert r2 is fallback
            assert create.call_count == 1
            assert create.call_args.kwargs["json_object"] is False

    def test_cached_false_skips_json_object(self):
        s = make_summarizer()
        _set_schema_support("test-model", "None", False)
        fake = LLMCompletion(text="plain")
        with mock.patch("summarizer.complete_model", return_value=fake) as create:
            r = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        assert r is fake
        assert create.call_count == 1
        assert create.call_args.kwargs["json_object"] is False

    def test_non_format_error_not_cached(self):
        from openai import AuthenticationError

        s = make_summarizer()
        with mock.patch(
            "summarizer.complete_model",
            side_effect=AuthenticationError("Invalid API key", response=mock.MagicMock(), body={}),
        ):
            with pytest.raises(AuthenticationError):
                s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        assert _get_schema_support("test-model", "None") is None
