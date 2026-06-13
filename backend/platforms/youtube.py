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
        # player_client 顺序决定取到哪批 format。web/ios/mweb 等客户端要解 nsig 签名，
        # 依赖本机 JS 运行时(Deno) + 运行时从 GitHub 拉解算脚本；打包分发 / 无 Deno /
        # 国内 GitHub 不可达时这些 format 会被丢弃，表现为
        # "Requested format is not available"（实测可复现）。
        # android_vr / android 客户端免 JS、不解签名即可拿到可播放音视频(实测无任何
        # JS 运行时下仍解出最佳 opus 251)，故放最前作为可靠主路；default 垫底，
        # 当本机恰好有 Deno 时仍可回退到 web 客户端并配合 EJS 解 nsig。
        return {
            "extractor_args": {
                "youtube": {"player_client": ["android_vr", "android", "default"]},
            },
            "remote_components": ["ejs:github", "ejs:npm"],
        }

    @property
    def requires_cookies(self) -> bool:
        return True
