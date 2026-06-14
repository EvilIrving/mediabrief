# backend/db.py 拆分方案

## 背景

`backend/db.py` 当前约 996 行，职责过多，主要混合了：

1. SQLite 连接、schema 初始化、迁移。
2. tasks 表 CRUD、历史查询、转录正文按需读取。
3. task_queue 表 CRUD、队列状态、安全投影、processing 修复。
4. RSS 持久化与旧 JSON 数据迁移。

最近文件变大的主要来源是队列相关逻辑，包括原子认领、安全投影、processing 归一化、队列 REST 查询等。

目标不是重写数据库层，而是先做低风险拆分：**降低单文件体积，保持外部 API 兼容，尽量不改业务行为。**

## 推荐方案

采用 **兼容 façade + 按领域拆文件**。

拆分后结构：

```text
backend/
  db.py              # 兼容门面：re-export 公共函数
  db_core.py         # 连接、schema、init_db、通用 helper
  db_tasks.py        # tasks 表 CRUD、history、transcript、tasks JSON 迁移
  db_queue.py        # task_queue 表 CRUD、state、安全投影、stale 恢复
  db_rss.py          # rss_feeds 表 load/save、RSS JSON 迁移
```

`db.py` 保留为稳定入口，现有调用方继续使用：

```python
from db import get_task
from db import queue_get_state
from db import rss_load_sync
```

第一阶段不批量改成：

```python
from db_tasks import get_task
from db_queue import queue_get_state
```

这样可以降低改动面，避免和当前已有 staged changes 混在一起。

## 文件职责

### `backend/db_core.py`

放底层数据库能力：

- `_get_db_path`
- `_ensure_dir`
- `_connect`
- `_ensure_schema`
- `_migrate`
- `_run_in_thread`
- `init_db`

建议：`_migrate` 第一阶段继续集中创建所有表，避免 schema 初始化逻辑被拆散后增加启动风险。

`init_db()` 可以在这里编排：

- 初始化 schema。
- 重启时处理 processing / queued 残留状态。
- 调用 RSS 和 tasks 的 JSON 迁移函数。

### `backend/db_tasks.py`

放 tasks 表相关逻辑：

- `TASK_FIXED_COLUMNS`
- `_sync_columns`
- `_create_task_sync`
- `_update_task_sync`
- `row_to_task_dict` 或 `_row_to_task_dict`
- `create_task`
- `update_task`
- `get_task`
- `task_exists`
- `delete_task`
- `delete_tasks`
- `list_recent_tasks`
- `list_history`
- `get_transcript`
- `tasks_migrate_from_json`

注意：如果 queue 模块需要把 tasks 行合并 JSON data，应导出一个语义明确的内部 helper，例如：

```python
from db_tasks import row_to_task_dict as _row_to_task_dict
```

避免继续依赖语义模糊的 `_row_to_dict`。

### `backend/db_queue.py`

放 task_queue 表相关逻辑：

- `queue_enqueue`
- `queue_get_next`
- `queue_claim_next`
- `queue_set_processing`
- `queue_set_completed`
- `queue_set_error`
- `queue_set_cancelled`
- `queue_remove`
- `queue_remove_by_task_id`
- `queue_recover_stale`
- `_safe_source_label`
- `_normalize_single_processing`
- `_enrich_processing_item`
- `queue_get_state`
- `_queue_row_to_dict`
- `queue_get_item`
- `queue_stats`
- `queue_list_items`
- `queue_clear_completed`

这个模块是第一阶段拆分收益最大的部分，因为队列逻辑占用了 `db.py` 的大量行数，并且职责相对独立。

### `backend/db_rss.py`

放 RSS 持久化逻辑：

- `rss_load_sync`
- `rss_save_sync`
- `rss_migrate_from_json`

保持同步函数形式，因为现有 `rss_reader.py` 内部直接调用同步 load/save。

### `backend/db.py`

改成兼容门面，只负责 re-export：

```python
"""SQLite 数据库层公共入口。"""

from db_core import init_db
from db_tasks import (
    create_task,
    update_task,
    get_task,
    task_exists,
    delete_task,
    delete_tasks,
    list_recent_tasks,
    list_history,
    get_transcript,
)
from db_queue import (
    queue_enqueue,
    queue_get_next,
    queue_claim_next,
    queue_set_processing,
    queue_set_completed,
    queue_set_error,
    queue_set_cancelled,
    queue_remove,
    queue_remove_by_task_id,
    queue_recover_stale,
    queue_get_state,
    queue_get_item,
    queue_stats,
    queue_list_items,
    queue_clear_completed,
)
from db_rss import rss_load_sync, rss_save_sync
```

如需兼容旧内部测试或脚本，也可以临时 re-export migration helper，但第一阶段不建议暴露更多非公共函数。

## 导入约束

后端运行目录是 `backend/`，所以新模块必须继续使用 flat import：

```python
from db_core import _connect, _run_in_thread
```

不要使用 package-relative import：

```python
from .db_core import _connect  # 不符合当前项目运行方式
```

## 实施步骤

1. 基于当前工作区内容拆分，尤其保留 `backend/db.py` 里已有 staged 改动。
2. 新建：
   - `backend/db_core.py`
   - `backend/db_tasks.py`
   - `backend/db_queue.py`
   - `backend/db_rss.py`
3. 将对应代码块纯移动到新模块，尽量不改 SQL、不改字段、不改返回结构。
4. 将 `backend/db.py` 改为 re-export façade。
5. 只在必要处调整内部 helper 名称，例如 `_row_to_dict` → `row_to_task_dict`。
6. 不批量修改现有调用方 import。
7. 跑最小验证。

## 验证命令

```bash
cd backend && python -c "import main; print('OK', len(main.app.routes))"
```

期望：后端可正常 import，路由数量符合当前项目预期。

再跑语法检查：

```bash
python -m compileall backend
```

如果后续要提高信心，再做一次队列 smoke test：

- 入队一个任务。
- 查询队列状态。
- claim 下一项。
- 标记 completed / error / cancelled。
- 确认安全投影不返回 `api_key`、`model_base_url`、`model_id`、`script`、`summary`、`translation` 正文。

## 风险与注意事项

- 当前工作区已有 staged changes，拆分时不能回退或覆盖这些改动。
- `_get_db_path()` 里的延迟导入 `task_store.TEMP_DIR` 不要随意改，避免循环依赖。
- `_migrate()` 第一阶段不要过度拆分，避免 schema 初始化顺序变化。
- `db_queue.py` 的安全投影逻辑不要退回原始 `payload/result` 返回，否则可能重新暴露密钥或正文。
- `init_db()` 的重启恢复语义要保持一致，尤其是 tasks 和 task_queue 的残留状态处理。

## 不建议第一阶段做的事

- 不重写 SQL。
- 不引入 ORM。
- 不改数据库 schema。
- 不批量修改全项目 import。
- 不顺手重构 task_store、task_queue、routers。
- 不把 schema 分散到多个模块分别创建，除非后续有测试覆盖。

## 推荐结论

第一阶段只做一件事：

> 把 `backend/db.py` 拆成 `db_core.py`、`db_tasks.py`、`db_queue.py`、`db_rss.py`，并保留 `db.py` 作为兼容门面。

这样能明显降低 `db.py` 体积，同时最大限度保持现有调用方和业务行为不变。
