"""DeepSeek Responses API 客户端。

官方文档：
- Responses API https://api-docs.deepseek.com/zh-cn/guides/responses_api
- Tool Calls https://api-docs.deepseek.com/zh-cn/guides/tool_calls
- JSON Output https://api-docs.deepseek.com/zh-cn/guides/json_mode

不走 chat.completions。思考由配置控制，默认关闭。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import openai

from llm_tools import JSON_OBJECT_FORMAT, parse_json_arguments


def build_openai_client(*, thinking: bool = False, **kwargs: Any):
    client = openai.OpenAI(**kwargs)
    client._mb_thinking = bool(thinking)  # type: ignore[attr-defined]
    return client


@dataclass
class LLMCompletion:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    status: str = ""


def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions = ""
    rest: list[dict[str, Any]] = []
    for item in messages:
        if item.get("role") == "system" and not instructions:
            instructions = str(item.get("content") or "")
        else:
            rest.append(item)
    return instructions, rest


def _parse_responses(response: Any) -> LLMCompletion:
    text = getattr(response, "output_text", None) or ""
    calls = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "function_call":
            continue
        calls.append({
            "id": getattr(item, "call_id", None) or getattr(item, "id", "") or "",
            "name": getattr(item, "name", "") or "",
            "arguments": parse_json_arguments(getattr(item, "arguments", "") or {}),
        })
    return LLMCompletion(
        text=text,
        tool_calls=calls,
        status=str(getattr(response, "status", "") or ""),
    )


def complete_model(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    json_object: bool = False,
    max_tokens: int = 800,
    temperature: float = 0,
) -> LLMCompletion:
    """唯一模型调用入口：Responses API。"""
    instructions, rest = _split_system(messages)
    kwargs: dict[str, Any] = {
        "model": model,
        "input": rest or messages,
        "max_output_tokens": max_tokens,
        "temperature": temperature,
    }
    if instructions:
        kwargs["instructions"] = instructions
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if json_object and not tools:
        kwargs["text"] = {"format": JSON_OBJECT_FORMAT}
    if getattr(client, "_mb_thinking", False):
        kwargs["reasoning"] = {"effort": "high"}
    return _parse_responses(client.responses.create(**kwargs))
