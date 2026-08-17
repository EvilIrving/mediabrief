"""DeepSeek 官方 Tool / JSON 形态。

Tool Calls：https://api-docs.deepseek.com/zh-cn/guides/tool_calls
JSON Output：https://api-docs.deepseek.com/zh-cn/guides/json_mode
Responses API：https://api-docs.deepseek.com/zh-cn/guides/responses_api
"""
from __future__ import annotations

import json
from typing import Any

COMPLETE_TOOL = "complete"
FAIL_TOOL = "fail"

JSON_OBJECT_FORMAT = {"type": "json_object"}


def arguments_to_parameters(arguments: Any) -> dict[str, Any]:
    """把宿主内部的 arguments 说明转成官方 Function parameters JSON Schema。"""
    if not isinstance(arguments, dict) or not arguments:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for key, spec in arguments.items():
        name = str(key)
        if isinstance(spec, list):
            properties[name] = {
                "type": "string",
                "enum": [str(item) for item in spec],
            }
        elif isinstance(spec, dict) and spec.get("type"):
            properties[name] = spec
        else:
            properties[name] = {
                "type": "string",
                "description": str(spec or name),
            }
        required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def object_parameters(
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = list(required)
    return parameters


def string_prop(description: str = "", *, enum: list[str] | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"type": "string"}
    if description:
        spec["description"] = description
    if enum is not None:
        spec["enum"] = list(enum)
    return spec


def function_tool(name: str, description: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Responses API function tool：扁平 name / description / parameters。"""
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters or object_parameters(),
    }


def host_function_tool(
    name: str,
    description: str,
    *,
    capability: str,
    timeout_sec: int,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """官方 function + 宿主元数据。发给模型前用 spec_to_function_tool 去掉 capability/timeout。"""
    tool = function_tool(name, description, object_parameters(properties, required))
    tool["capability"] = capability
    tool["timeout_sec"] = timeout_sec
    return tool


def spec_to_function_tool(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name") or "").strip()
    description = str(spec.get("description") or name)
    parameters = spec.get("parameters")
    if not isinstance(parameters, dict):
        parameters = arguments_to_parameters(spec.get("arguments"))
    return function_tool(name, description, parameters)


def control_tools() -> list[dict[str, Any]]:
    return [
        function_tool(
            COMPLETE_TOOL,
            "Recovery is done. Call only after the host has verified a subtitle or media artifact.",
        ),
        function_tool(
            FAIL_TOOL,
            "Stop because recovery cannot continue safely.",
            {
                "type": "object",
                "properties": {"message": {"type": "string", "description": "Short sanitized reason"}},
                "required": ["message"],
                "additionalProperties": False,
            },
        ),
    ]


def parse_json_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
