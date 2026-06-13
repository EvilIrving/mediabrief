"""通用平台适配器（兜底）。

匹配所有未被其他 adapter 处理的 URL。
使用默认参数，不启用任何平台特定功能。
"""

from ._base import BasePlatformAdapter


class GenericAdapter(BasePlatformAdapter):
    name = "generic"

    @classmethod
    def matches(cls, url: str) -> bool:
        # 兜底适配器始终返回 True，但应在所有特定 adapter 之后尝试
        return True
