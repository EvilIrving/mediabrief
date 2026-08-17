from types import SimpleNamespace
from unittest import mock

from llm_client import LLMCompletion, build_openai_client, complete_model
from llm_tools import function_tool, spec_to_function_tool


def _responses_result(text="", calls=None, status="completed"):
    output = []
    for call in calls or []:
        output.append(SimpleNamespace(
            type="function_call",
            name=call["name"],
            arguments=call.get("arguments", {}),
            call_id=call.get("id", "call_1"),
        ))
    return SimpleNamespace(output_text=text, output=output, status=status)


def test_complete_model_uses_responses_api_only():
    fake = mock.MagicMock()
    fake.responses.create.return_value = _responses_result("hello")
    fake._mb_thinking = False
    with mock.patch("llm_client.openai.OpenAI", return_value=fake):
        client = build_openai_client(api_key="sk-test")
        done = complete_model(
            client,
            model="deepseek-v4-flash",
            messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        )
    assert done == LLMCompletion(text="hello", tool_calls=[], status="completed")
    fake.chat.completions.create.assert_not_called()
    kwargs = fake.responses.create.call_args.kwargs
    assert kwargs["model"] == "deepseek-v4-flash"
    assert kwargs["instructions"] == "sys"
    assert kwargs["input"] == [{"role": "user", "content": "hi"}]
    assert "reasoning" not in kwargs


def test_thinking_uses_responses_reasoning():
    fake = mock.MagicMock()
    fake.responses.create.return_value = _responses_result("ok")
    with mock.patch("llm_client.openai.OpenAI", return_value=fake):
        client = build_openai_client(api_key="sk-test", thinking=True)
        complete_model(client, model="deepseek-v4-flash", messages=[{"role": "user", "content": "hi"}])
    assert fake.responses.create.call_args.kwargs["reasoning"] == {"effort": "high"}


def test_json_object_uses_text_format():
    fake = mock.MagicMock()
    fake.responses.create.return_value = _responses_result('{"a":1}')
    fake._mb_thinking = False
    complete_model(
        fake,
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "give json"}],
        json_object=True,
    )
    assert fake.responses.create.call_args.kwargs["text"] == {"format": {"type": "json_object"}}


def test_tools_are_flat_function_tools():
    fake = mock.MagicMock()
    fake.responses.create.return_value = _responses_result(
        "",
        calls=[{"name": "present_download_list", "arguments": '{"video_formats":[]}'}],
    )
    fake._mb_thinking = False
    tool = spec_to_function_tool({
        "name": "present_download_list",
        "description": "present list",
        "arguments": {"video_formats": "Detect video_formats array"},
    })
    done = complete_model(
        fake,
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "list"}],
        tools=[tool],
    )
    sent = fake.responses.create.call_args.kwargs["tools"][0]
    assert sent["type"] == "function"
    assert sent["name"] == "present_download_list"
    assert "function" not in sent
    assert done.tool_calls[0]["name"] == "present_download_list"
    assert done.tool_calls[0]["arguments"] == {"video_formats": []}


def test_function_tool_shape_is_responses():
    tool = function_tool("get_weather", "Get weather", {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"],
        "additionalProperties": False,
    })
    assert tool == {
        "type": "function",
        "name": "get_weather",
        "description": "Get weather",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
            "additionalProperties": False,
        },
    }
