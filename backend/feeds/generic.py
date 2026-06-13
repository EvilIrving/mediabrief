"""通用订阅源适配器（兜底）。

匹配所有未被其他 adapter 处理的输入，原样返回（假定本身已是 feed URL）。
"""

from __future__ import annotations

from ._base import BaseFeedAdapter, FetchHtml


class GenericFeedAdapter(BaseFeedAdapter):
    name = "generic"

    @classmethod
    def matches(cls, raw: str) -> bool:
        # 兜底适配器始终返回 True，但应在所有特定 adapter 之后尝试。
        return True

    async def resolve(self, raw: str, fetch_html: FetchHtml) -> str:
        return raw.strip()
