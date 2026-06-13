"""YouTube 频道订阅源适配器。

把各种 YouTube 频道标识统一成标准 Atom feed URL：

    https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxxxxxx

支持的输入形态：
    UCxxxxxxxx                                          裸频道 ID
    https://www.youtube.com/channel/UCxxxxxxxx          频道页（含 ID）
    https://www.youtube.com/@handle                     handle
    https://www.youtube.com/c/name                      自定义名
    https://www.youtube.com/user/name                   旧版用户名
    https://www.youtube.com/feeds/videos.xml?channel_id=UC...   已是 feed
    @handle                                             裸 handle

前三种之外（@handle / c / user）无法从 URL 静态拿到 channel id，
需抓一次频道页 HTML，从中提取 channelId / externalId / canonical 链接。
不依赖 YouTube Data API。
"""

from __future__ import annotations

import re

from ._base import BaseFeedAdapter, FetchHtml

_FEED_TMPL = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"

# 频道 ID 形如 UC + 22 位 [A-Za-z0-9_-]
_CHANNEL_ID = re.compile(r"^UC[\w-]{22}$")
_CHANNEL_ID_IN_URL = re.compile(r"youtube\.com/channel/(UC[\w-]{22})", re.IGNORECASE)
_CHANNEL_ID_IN_QUERY = re.compile(r"[?&]channel_id=(UC[\w-]{22})", re.IGNORECASE)

# 从频道页 HTML 中提取 channel id 的几种常见来源（按可靠性排序）。
_HTML_PATTERNS = (
    re.compile(r'"channelId":"(UC[\w-]{22})"'),
    re.compile(r'"externalId":"(UC[\w-]{22})"'),
    re.compile(r'youtube\.com/channel/(UC[\w-]{22})'),
)

# 识别一段输入是否「看起来像 YouTube」。
_LOOKS_YOUTUBE = re.compile(
    r"(^UC[\w-]{22}$)|(^@[\w.-]+$)|(youtube\.com)|(youtu\.be)",
    re.IGNORECASE,
)


class YouTubeFeedAdapter(BaseFeedAdapter):
    name = "youtube"

    @classmethod
    def matches(cls, raw: str) -> bool:
        return bool(_LOOKS_YOUTUBE.search((raw or "").strip()))

    async def resolve(self, raw: str, fetch_html: FetchHtml) -> str:
        raw = (raw or "").strip()

        # 已经是 YouTube feed URL —— 原样返回。
        if "youtube.com/feeds/videos.xml" in raw.lower():
            return raw

        # ── 能静态解析的：裸 ID / channel 页 / channel_id 查询参数 ──
        if _CHANNEL_ID.match(raw):
            return _FEED_TMPL.format(cid=raw)
        m = _CHANNEL_ID_IN_URL.search(raw) or _CHANNEL_ID_IN_QUERY.search(raw)
        if m:
            return _FEED_TMPL.format(cid=m.group(1))

        # ── 需要抓页面：@handle / c / user ──
        page_url = self._channel_page_url(raw)
        html = await fetch_html(page_url)
        for pat in _HTML_PATTERNS:
            hit = pat.search(html)
            if hit:
                return _FEED_TMPL.format(cid=hit.group(1))

        raise ValueError(f"无法从 YouTube 频道解析出 channel_id: {raw}")

    @staticmethod
    def _channel_page_url(raw: str) -> str:
        """把输入还原成一个可抓取的频道页 URL。"""
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        if raw.startswith("@"):
            return f"https://www.youtube.com/{raw}"
        # 其余裸串当作 handle 处理。
        return f"https://www.youtube.com/@{raw.lstrip('@')}"
