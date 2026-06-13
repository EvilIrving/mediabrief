"""平台适配器基类。

每个视频平台（YouTube、Bilibili 等）实现一个子类，封装该平台的：
- URL 识别
- 下载参数（超时、重试、chunk size）
- extractor 级别参数（如 remote_components）
- 字幕语言优先级
- cookies 需求
"""

from abc import ABC, abstractmethod
from typing import Any


class BasePlatformAdapter(ABC):
    """平台适配器抽象基类。

    子类只需要覆写 matches() 和有差异的方法，其余走基类默认值。
    """

    name: str = "generic"
    """平台名，用于日志和展示。"""

    # ── URL 匹配 ──────────────────────────────────────────────

    @classmethod
    @abstractmethod
    def matches(cls, url: str) -> bool:
        """判断 URL 是否属于本平台。"""
        ...

    # ── 下载参数 ──────────────────────────────────────────────

    def get_download_opts(self) -> dict[str, Any]:
        """返回下载时附加的 yt-dlp 选项（超时、重试、chunk 等）。

        这些选项会在 _get_base_opts 之上叠加，允许不同平台有不同的
        网络容忍度。例如 Bilibili 国内 CDN 波动大，需要更长超时。
        """
        return {
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "file_access_retries": 3,
        }

    def get_extractor_args(self) -> dict[str, Any]:
        """返回 yt-dlp extractor 级别的参数。

        例如 YouTube 需要 ``remote_components: ["ejs:github"]`` 来解
        nsig 签名。非 YouTube 平台不应启用此参数以避免网络依赖。
        """
        return {}

    # ── 字幕行为 ──────────────────────────────────────────────

    @property
    def prefer_auto_captions(self) -> bool:
        """没有手动字幕时，是否优先使用自动字幕。

        YouTube 自动字幕质量高，通常值得用；B站 手动字幕少但
        自动字幕可能更全。
        """
        return True

    def get_subtitle_lang_priority(self) -> list[str]:
        """字幕语言优先级列表（从高到低）。

        默认优先级：英语 > 简体中文 > 繁体中文 > 其他常见语言。
        平台可覆写（如 B站 应优先中文）。
        """
        return ["en", "en-orig", "zh-Hans", "zh-Hant", "zh", "ja", "ko", "fr", "de", "es"]

    # ── Cookies / 认证 ───────────────────────────────────────

    @property
    def requires_cookies(self) -> bool:
        """此平台是否强依赖 cookies 才能正常下载。

        YouTube 在检测到无 cookies 时经常返回 bot 验证页面，
        因此标记为 True，提示 VideoProcessor 确保 cookies 已配置。
        """
        return False

    # ── 后处理钩子 ────────────────────────────────────────────

    def post_process_info(self, info: dict[str, Any]) -> dict[str, Any]:
        """对 yt-dlp extract_info 返回的字典做平台级后处理。

        可用于：修正标题编码、过滤无效格式、补充元数据等。
        默认不做任何修改。
        """
        return info
