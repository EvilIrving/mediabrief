"""YouTube 平台适配器。

YouTube 的特殊处理：
- 需要 EJS 远程组件解 nsig 签名
- 强依赖 cookies（无 cookies 时反爬验证频繁失败）
- 自动字幕质量高，优先使用
"""

import re

from ._base import BasePlatformAdapter


class YouTubeAdapter(BasePlatformAdapter):
    name = "youtube"

    _URL_PATTERN = re.compile(
        r"(^|://|\.)(youtube\.com|youtu\.be)/", re.IGNORECASE
    )

    @classmethod
    def matches(cls, url: str) -> bool:
        return bool(cls._URL_PATTERN.search(url or ""))

    def get_extractor_args(self) -> dict:
        return {"remote_components": ["ejs:github"]}

    @property
    def requires_cookies(self) -> bool:
        return True
