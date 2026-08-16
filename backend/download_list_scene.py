"""Detect 接入 Harness：把 Detect 返回交给环，模型只选 ``present_download_list``。

模型不可用或没选这个 Tool 时，宿主直接跑同一 ``execute``，页面仍拿到同一份 payload。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from format_curator import TOOL_ID, execute, tool_spec
from media_recovery import RecoveryDecisionKind, RecoveryModel

logger = logging.getLogger(__name__)

DOWNLOAD_LIST_GOAL = "present a parseable download list from the Detect catalog"
DOWNLOAD_LIST_SYSTEM_PROMPT = (
    "You attach after Detect. The only allowed action is present_download_list. "
    "Call it and pass the Detect video_formats and audio_formats through as arguments. "
    "Do not invent format ids. Never request secrets, cookies, shell, or files. "
    "Return JSON only: {\"kind\":\"action\",\"action\":\"present_download_list\","
    "\"arguments\":{\"video_formats\":[],\"audio_formats\":[]}}."
)

_SLIM_KEYS = ("id", "ext", "height", "fps", "vcodec", "abr", "acodec", "filesize", "label")


def slim_detect_catalog(catalog: dict[str, Any]) -> dict[str, list[dict]]:
    return {
        "video_formats": [_slim_item(item) for item in catalog.get("video_formats") or []],
        "audio_formats": [_slim_item(item) for item in catalog.get("audio_formats") or []],
    }


async def run_download_list_scene(
    catalog: dict[str, Any],
    *,
    model: Optional[RecoveryModel] = None,
) -> dict[str, list[dict]]:
    """返回 present_download_list 的 payload。有模型就让它选 Tool，没有就宿主自己跑。"""
    catalog = slim_detect_catalog(catalog)
    host_payload = execute(catalog)
    if model is None:
        return host_payload

    messages = [{
        "role": "user",
        "content": json.dumps(
            {"goal": DOWNLOAD_LIST_GOAL, "detect": catalog},
            ensure_ascii=False,
        ),
    }]
    try:
        decision = await model.decide(
            messages,
            (tool_spec(),),
            system_prompt=DOWNLOAD_LIST_SYSTEM_PROMPT,
            max_output_chars=8_000,
        )
    except Exception as exc:
        logger.warning("download list scene model unavailable: %s", exc)
        return host_payload

    if decision.kind is not RecoveryDecisionKind.ACTION or decision.action != TOOL_ID:
        logger.info("download list scene did not select %s, using host payload", TOOL_ID)
        return host_payload

    arguments = decision.arguments if isinstance(decision.arguments, dict) else {}
    video = arguments.get("video_formats")
    audio = arguments.get("audio_formats")
    if not video and not audio:
        arguments = catalog
    try:
        return execute(arguments)
    except Exception as exc:
        logger.warning("present_download_list failed, using host payload: %s", exc)
        return host_payload


def _slim_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {key: item[key] for key in _SLIM_KEYS if key in item and item[key] not in (None, "")}