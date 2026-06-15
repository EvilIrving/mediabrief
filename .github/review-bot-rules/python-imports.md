# python-imports — 后端扁平导入

## 规则

`backend/` 根目录下的模块（非子包）必须使用扁平导入，禁止相对导入。

## 正确 ✓

```python
# 文件路径: backend/routers/transcribe.py
from services import summarizer
from task_store import tasks, broadcast_update
from pipeline import process_video_task
from cancellation import cancelled
from db import get_task as _db_get_task
```

## 错误 ✗

```python
# 文件路径: backend/routers/transcribe.py
from ..services import summarizer       # ❌ 相对导入
from .task_store import tasks           # ❌ 相对导入
from backend.services import summarizer # ❌ 包路径导入
```

## 例外

- `backend/platforms/`、`backend/feeds/`、`backend/bots/` 内的子包可使用 `from ._base import ...`（这是 Python 子包标准做法）
- 子包内部的模块间引用可使用相对导入

## 为什么

后端运行时工作目录是 `backend/`（由 `start.py` 通过 `os.chdir` 设置）。相对导入在根模块间会失败或产生歧义。
