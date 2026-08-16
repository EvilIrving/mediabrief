from unittest import mock

from llm_client import build_openai_client


def test_build_openai_client_disables_thinking():
    fake = mock.MagicMock()
    raw_create = mock.MagicMock(return_value="ok")
    fake.chat.completions.create = raw_create
    with mock.patch("llm_client.openai.OpenAI", return_value=fake):
        client = build_openai_client(api_key="sk-test")
        assert client.chat.completions.create(model="deepseek-v4-flash", messages=[]) == "ok"
        assert raw_create.call_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_build_openai_client_retries_without_thinking_if_rejected():
    fake = mock.MagicMock()
    raw_create = mock.MagicMock(side_effect=[TypeError("unexpected keyword thinking"), "ok"])
    fake.chat.completions.create = raw_create
    with mock.patch("llm_client.openai.OpenAI", return_value=fake):
        client = build_openai_client(api_key="sk-test")
        assert client.chat.completions.create(model="m", messages=[]) == "ok"
        assert raw_create.call_count == 2
        assert "extra_body" not in raw_create.call_args.kwargs
