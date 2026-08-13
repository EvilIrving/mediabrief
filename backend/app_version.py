"""MediaBrief 单一版本来源。开发态和打包态都读取根目录 VERSION。"""
from __future__ import annotations

import sys
from pathlib import Path


def _version_file() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "VERSION"
    return Path(__file__).resolve().parent.parent / "VERSION"


def get_app_version() -> str:
    try:
        version = _version_file().read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return version or "0.0.0"


APP_VERSION = get_app_version()
