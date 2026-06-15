"""测试引导：保证 backend/ 在 sys.path 上，沿用运行时的 flat import 约定。

运行：
    cd backend && ../venv/bin/python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

# backend/ 根目录（tests/ 的上一级）。运行时 start.py 会 chdir 到此处，
# 测试里手动补上 sys.path，使 `import error_messages` 等 flat import 生效。
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
