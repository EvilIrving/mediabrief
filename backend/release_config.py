"""读取发行包内置的 AI 配置；真实配置仅在构建时生成，不进入源码仓库。"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class ReleaseLLMConfig:
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    recovery_api_key: str = ""
    recovery_base_url: str = ""
    recovery_model: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)


def _config_path() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        root = Path(__file__).resolve().parent.parent
    return root / "release-config.json"


@lru_cache(maxsize=1)
def get_release_llm_config() -> ReleaseLLMConfig:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return ReleaseLLMConfig()
    if not isinstance(data, dict):
        return ReleaseLLMConfig()
    return ReleaseLLMConfig(
        api_key=str(data.get("api_key") or "").strip(),
        base_url=str(data.get("base_url") or "").strip().rstrip("/"),
        model=str(data.get("model") or "").strip(),
        recovery_api_key=str(data.get("recovery_api_key") or data.get("api_key") or "").strip(),
        recovery_base_url=str(data.get("recovery_base_url") or data.get("base_url") or "").strip().rstrip("/"),
        recovery_model=str(data.get("recovery_model") or data.get("model") or "").strip(),
    )
