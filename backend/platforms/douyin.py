"""抖音平台适配器。

抖音的特殊处理：
- 短链 ``v.douyin.com/xxx`` 会 302 跳转到真实视频页，yt-dlp 会自动跟随；
- 抖音对无 ``Referer`` 的请求风控较严，补上 Referer/UA 提升成功率；
- 国内 CDN 波动，沿用较长超时与多重试；
- 内容以中文为主，字幕优先中文。
"""

import re

from ._base import BasePlatformAdapter


class DouyinAdapter(BasePlatformAdapter):
    name = "douyin"

    _URL_PATTERN = re.compile(
        r"(^|://|\.)(douyin\.com|iesdouyin\.com)/|(^|://)v\.douyin\.com/",
        re.IGNORECASE,
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
            # 抖音对缺失 Referer 的请求风控较严，补上来源头降低被拦概率。
            "http_headers": {
                "Referer": "https://www.douyin.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
        }

    def get_subtitle_lang_priority(self) -> list[str]:
        return ["zh-Hans", "zh-Hant", "zh", "en"]
