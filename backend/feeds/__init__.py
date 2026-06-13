"""订阅源适配器自动发现与导出。

新增订阅平台只需在此目录下新建一个文件（如 ``apple_podcast.py``），
定义一个继承 ``BaseFeedAdapter`` 的类，即可被自动发现，无需修改其他文件。

与 ``platforms/`` 同构：``platforms`` 解析视频 URL 的下载策略，``feeds`` 解析
订阅输入到标准 feed URL。
"""

import importlib
import logging
import pkgutil
from typing import Type

from ._base import BaseFeedAdapter, FetchHtml

logger = logging.getLogger(__name__)

__all__ = ["BaseFeedAdapter", "FetchHtml", "resolve_feed_adapter", "normalize_feed_input", "list_feed_adapters"]


def _discover_adapter_classes() -> list[Type[BaseFeedAdapter]]:
    """扫描 feeds/ 目录，自动发现所有 BaseFeedAdapter 子类（GenericFeedAdapter 兜底在最后）。"""
    from .generic import GenericFeedAdapter

    classes: list[Type[BaseFeedAdapter]] = []
    for _finder, name, _ispkg in pkgutil.iter_modules(__path__):
        if name.startswith("_") or name == "generic":
            continue
        try:
            mod = importlib.import_module(f".{name}", package=__package__)
        except Exception:
            logger.warning("跳过无法加载的订阅源模块: %s", name, exc_info=True)
            continue
        for obj in vars(mod).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseFeedAdapter)
                and obj is not BaseFeedAdapter
                and obj is not GenericFeedAdapter
            ):
                classes.append(obj)

    classes.append(GenericFeedAdapter)
    return classes


_ADAPTER_CLASSES: list[Type[BaseFeedAdapter]] | None = None


def _get_adapter_classes() -> list[Type[BaseFeedAdapter]]:
    global _ADAPTER_CLASSES
    if _ADAPTER_CLASSES is None:
        _ADAPTER_CLASSES = _discover_adapter_classes()
    return _ADAPTER_CLASSES


def resolve_feed_adapter(raw: str) -> BaseFeedAdapter:
    """按原始输入匹配订阅源适配器，GenericFeedAdapter 兜底。"""
    for cls in _get_adapter_classes():
        if cls.matches(raw):
            return cls()
    from .generic import GenericFeedAdapter
    return GenericFeedAdapter()


async def normalize_feed_input(raw: str, fetch_html: FetchHtml) -> str:
    """把任意订阅输入归一化成标准 feed URL（非特定平台原样返回）。"""
    return await resolve_feed_adapter(raw).resolve(raw, fetch_html)


def list_feed_adapters() -> list[str]:
    """返回所有已注册的订阅源平台名称（调试 / 前端展示用）。"""
    return [cls.name for cls in _get_adapter_classes()]
