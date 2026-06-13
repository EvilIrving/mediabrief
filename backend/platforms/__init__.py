"""平台适配器自动发现与导出。

新增平台只需在此目录下新建一个文件（如 ``tiktok.py``），
定义一个继承 ``BasePlatformAdapter`` 的类，即可自动被 VideoProcessor 发现。
无需修改任何其他文件。
"""

import importlib
import logging
import pkgutil
from typing import Type

from ._base import BasePlatformAdapter

logger = logging.getLogger(__name__)

# 公开 API
__all__ = ["BasePlatformAdapter", "resolve_adapter", "list_adapters"]


def _discover_adapter_classes() -> list[Type[BasePlatformAdapter]]:
    """扫描 platforms/ 目录，自动发现所有 BasePlatformAdapter 子类。

    返回的列表中，GenericAdapter 始终在最后（兜底）。
    """
    from .generic import GenericAdapter

    classes: list[Type[BasePlatformAdapter]] = []

    for _finder, name, _ispkg in pkgutil.iter_modules(__path__):
        if name.startswith("_"):
            continue  # 跳过私有模块
        if name == "generic":
            continue  # 最后统一追加
        try:
            mod = importlib.import_module(f".{name}", package=__package__)
        except Exception:
            logger.warning("跳过无法加载的平台模块: %s", name, exc_info=True)
            continue
        for obj in vars(mod).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BasePlatformAdapter)
                and obj is not BasePlatformAdapter
                and obj is not GenericAdapter
            ):
                classes.append(obj)

    classes.append(GenericAdapter)
    return classes


# 模块级缓存，按需初始化
_ADAPTER_CLASSES: list[Type[BasePlatformAdapter]] | None = None


def _get_adapter_classes() -> list[Type[BasePlatformAdapter]]:
    global _ADAPTER_CLASSES
    if _ADAPTER_CLASSES is None:
        _ADAPTER_CLASSES = _discover_adapter_classes()
    return _ADAPTER_CLASSES


def resolve_adapter(url: str) -> BasePlatformAdapter:
    """按 URL 匹配平台适配器。

    遍历所有已发现的 adapter 类，返回到第一个 ``matches(url)``
    返回 True 的实例。GenericAdapter 总是最后一个被尝试，
    因此保证始终返回一个有效适配器。
    """
    for cls in _get_adapter_classes():
        if cls.matches(url):
            return cls()
    # 理论不可达（GenericAdapter.matches 始终 True），但保留安全回退
    from .generic import GenericAdapter
    return GenericAdapter()


def list_adapters() -> list[str]:
    """返回所有已注册的平台名称列表（用于调试和前端展示）。"""
    return [cls.name for cls in _get_adapter_classes()]
