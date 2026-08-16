"""OpenAI 兼容客户端。DeepSeek V4 默认开思考，这里统一关掉。"""
from __future__ import annotations

from typing import Any

import openai

_THINKING_OFF = {"thinking": {"type": "disabled"}}


def build_openai_client(**kwargs: Any):
    client = openai.OpenAI(**kwargs)
    raw_create = client.chat.completions.create

    def create(*args, **kw):
        extra = dict(kw.get("extra_body") or {})
        extra.setdefault("thinking", {"type": "disabled"})
        kw["extra_body"] = extra
        try:
            return raw_create(*args, **kw)
        except Exception as exc:
            text = str(exc).lower()
            if "thinking" not in text and "unexpected" not in text and "unknown" not in text:
                raise
            kw.pop("extra_body", None)
            return raw_create(*args, **kw)

    client.chat.completions.create = create  # type: ignore[method-assign]
    return client
