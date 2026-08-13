"""Bilibili 平台适配器。

B站 的特殊处理：
- 国内 CDN 波动大，需要更长的超时和更多重试
- 字幕优先中文（手动字幕少，自动字幕往往更全）
- 不需要 EJS 等外部组件
"""

import re

from ._base import BasePlatformAdapter


class BilibiliAdapter(BasePlatformAdapter):
    name = "bilibili"

    _URL_PATTERN = re.compile(
        r"(^|://)(www\.)?bilibili\.com/|(^|://)b23\.tv/", re.IGNORECASE
    )

    @classmethod
    def matches(cls, url: str) -> bool:
        return bool(cls._URL_PATTERN.search(url or ""))

    def get_download_opts(self) -> dict:
        return {
            "socket_timeout": 60,
            "retries": 10,
            "fragment_retries": 10,
            "file_access_retries": 5,
            "http_chunk_size": 10 * 1024 * 1024,
        }

    def get_subtitle_lang_priority(self) -> list[str]:
        # B站内容以中文为主，优先中文再英语
        return ["zh-Hans", "zh-Hant", "zh", "en", "ja"]

    def get_recovery_profiles(self) -> dict:
        # 两个 profile 的网络参数相同，差异仅在是否使用当前任务已获准的不透明登录态。
        options = {
            "http_headers": {
                "Referer": "https://www.bilibili.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
                ),
            },
        }
        return {
            "bilibili_anonymous": {"use_cookies": False, "options": options},
            "bilibili_browser_session": {"use_cookies": True, "options": options},
        }

    @property
    def prefer_auto_captions(self) -> bool:
        # B站手动字幕覆盖率较低，自动字幕（AI 字幕）往往更全
        return True
