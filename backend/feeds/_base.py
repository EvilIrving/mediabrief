"""订阅源输入适配器基类。

把用户在订阅框里粘贴的「源标识」归一化成一个标准的 RSS/Atom feed URL。
不同平台（YouTube 频道、未来的播客平台等）各实现一个子类，封装该平台的：
- 输入识别（频道 ID、@handle、频道页 URL 等）
- 归一化逻辑（能静态解析的直接拼，否则抓一次页面 HTML 提取）

与 ``platforms/`` 的视频适配器是并列关系：``platforms`` 处理「一个视频 URL 怎么下」，
``feeds`` 处理「一个订阅输入怎么变成 feed URL」。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

# 抓取页面 HTML 的回调（由 rss_reader 注入，避免本包直接耦合 urllib）。
FetchHtml = Callable[[str], Awaitable[str]]


class BaseFeedAdapter(ABC):
    """订阅源适配器抽象基类。

    子类只需覆写 ``matches()`` 与 ``resolve()``。
    """

    name: str = "generic"
    """平台名，用于日志和展示。"""

    @classmethod
    @abstractmethod
    def matches(cls, raw: str) -> bool:
        """判断这段原始输入是否属于本平台。"""
        ...

    @abstractmethod
    async def resolve(self, raw: str, fetch_html: FetchHtml) -> str:
        """把原始输入归一化为标准 feed URL。

        ``fetch_html(url)`` 用于需要抓页面才能确定 feed 的情况（如 @handle）；
        能纯静态解析的实现应避免调用它。
        """
        ...
