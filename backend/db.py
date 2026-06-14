"""SQLite 数据库层：任务持久化、历史查询。

使用内建 sqlite3 + asyncio.to_thread，不增加额外依赖。
所有任务以 JSON blob 存储，提供 get/update/list/delete 操作。
"""
import json
import logging
import sqlite3
import asyncio
import threading
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_db_path: Path | None = None

# 模式（schema）只需创建一次。用锁+标志保证幂等且线程安全：
# 任何连接（含 import 期的同步访问，早于 async init_db）都先确保表存在。
_schema_lock = threading.Lock()
_schema_ready = False


def _get_db_path() -> Path:
    """返回 DB 文件路径。

    frozen 时使用 task_store.TEMP_DIR（~/Library/Application Support/ai-transcriber），
    避免写 .app bundle 只读区域。延迟导入避免与 task_store 的循环依赖。
    """
    global _db_path
    if _db_path is not None:
        return _db_path
    from task_store import TEMP_DIR  # delayed import — avoid circular import
    _db_path = TEMP_DIR / "transcriber.db"
    return _db_path

TASK_FIXED_COLUMNS = (
    "status",
    "url",
    "source_type",
    "source_value",
    "video_title",
    "summary",
    "summary_language",
    "script",
)


def _ensure_dir():
    _get_db_path().parent.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(str(_get_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    """首次连接时建表，保证任何查询前 schema 已就绪。

    全新安装时 services.py 在 import 期就会读取 rss_feeds（早于 async
    init_db），若表未建好会抛 OperationalError 导致后端无法启动。
    """
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        _migrate(conn)
        _schema_ready = True


def _migrate(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id    TEXT PRIMARY KEY,
            status     TEXT NOT NULL DEFAULT 'processing',
            url        TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT '',
            source_value TEXT NOT NULL DEFAULT '',
            video_title TEXT NOT NULL DEFAULT '',
            summary    TEXT NOT NULL DEFAULT '',
            summary_language TEXT NOT NULL DEFAULT '',
            script     TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            data       TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_source_type ON tasks(source_type)")
    # RSS 表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_feeds (
            id           TEXT PRIMARY KEY,
            url          TEXT NOT NULL DEFAULT '',
            title        TEXT NOT NULL DEFAULT '',
            type         TEXT NOT NULL DEFAULT '',
            favorite     INTEGER NOT NULL DEFAULT 0,
            added_at     TEXT NOT NULL DEFAULT '',
            last_checked TEXT NOT NULL DEFAULT '',
            last_error   TEXT NOT NULL DEFAULT '',
            entries      TEXT NOT NULL DEFAULT '[]'
        )
    """)
    # 迁移：添加可能缺失的列（兼容旧 DB）
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN source_type TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN source_value TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN summary_language TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN script TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # 任务队列表（串行执行，DB 持久化）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_queue (
            id          TEXT PRIMARY KEY,
            queue_name  TEXT NOT NULL DEFAULT 'default',
            item_type   TEXT NOT NULL DEFAULT '',
            item_key    TEXT NOT NULL DEFAULT '',
            payload     TEXT NOT NULL DEFAULT '{}',
            status      TEXT NOT NULL DEFAULT 'queued',
            task_id     TEXT DEFAULT '',
            result      TEXT NOT NULL DEFAULT '{}',
            position    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            started_at  TEXT DEFAULT '',
            completed_at TEXT DEFAULT '',
            error       TEXT DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON task_queue(queue_name, status)")
    conn.commit()


async def init_db():
    """初始化数据库（启动时调用）。"""
    def _do():
        conn = _connect()
        try:
            _migrate(conn)
            # 将旧的处理中任务标为错误（服务器重启）
            conn.execute(
                "UPDATE tasks SET status='error', data=json_set(data, '$.error', '服务器重启，任务已失效') "
                "WHERE status='processing'"
            )
            # 将处理中的队列项标为错误（服务器重启中断了执行）
            conn.execute(
                "UPDATE task_queue SET status='error', error='服务器重启，任务已中断' "
                "WHERE status IN ('processing', 'queued')"
            )
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)
    # 从旧 JSON 文件迁移数据
    data_dir = _get_db_path().parent
    await _run_in_thread(rss_migrate_from_json, data_dir)
    await _run_in_thread(tasks_migrate_from_json, data_dir)


# ── 核心 CRUD ──────────────────────────────────────────────────

async def _run_in_thread(fn, *args):
    return await asyncio.to_thread(fn, *args)


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    # 合并 JSON data 字段到顶层，但保留表列优先级
    try:
        extra = json.loads(d.pop("data", "{}"))
    except (json.JSONDecodeError, TypeError):
        extra = {}
    if not isinstance(extra, dict):
        extra = {}
    extra.update(d)
    return extra


def _sync_columns(row: dict) -> tuple[dict, dict]:
    """分离固定列和 JSON 数据。None 值强制转空串以符合 NOT NULL。"""
    def _str(v):
        return "" if v is None else v
    fixed = {
        "status": _str(row.get("status", "processing")),
        "url": _str(row.get("url", "")),
        "source_type": _str(row.get("source_type", "")),
        "source_value": _str(row.get("source_value", "")),
        "video_title": _str(row.get("video_title", "")),
        "summary": _str(row.get("summary", "")),
        "summary_language": _str(row.get("summary_language", "")),
        "script": _str(row.get("script", "")),
    }
    extra = {k: v for k, v in row.items() if k not in TASK_FIXED_COLUMNS and k not in ("task_id", "created_at", "updated_at", "data")}
    return fixed, extra


def _create_task_sync(conn: sqlite3.Connection, task_id: str, data: dict):
    fixed, extra = _sync_columns(data)
    conn.execute(
        """INSERT INTO tasks (task_id, status, url, source_type, source_value,
           video_title, summary, summary_language, data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (task_id, fixed["status"], fixed["url"], fixed["source_type"],
         fixed["source_value"], fixed["video_title"], fixed["summary"],
         fixed["summary_language"], json.dumps(extra, ensure_ascii=False)),
    )


async def create_task(task_id: str, data: dict):
    def _do():
        conn = _connect()
        try:
            _create_task_sync(conn, task_id, data)
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)


def _update_task_sync(conn: sqlite3.Connection, task_id: str, fields: dict):
    """部分更新：读出现有 data JSON，合并新字段，回写。"""
    row = conn.execute("SELECT data FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        return False
    try:
        current_extra = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        current_extra = {}
    if not isinstance(current_extra, dict):
        current_extra = {}
    fixed, new_extra = _sync_columns(fields)
    current_extra.update(new_extra)
    for fixed_key in TASK_FIXED_COLUMNS:
        current_extra.pop(fixed_key, None)
    # 固定列有值则更新
    set_parts = ["updated_at = datetime('now')"]
    params = []
    for col in TASK_FIXED_COLUMNS:
        if col in fields:
            set_parts.append(f"{col} = ?")
            params.append("" if fields[col] is None else fields[col])
    set_parts.append("data = ?")
    params.append(json.dumps(current_extra, ensure_ascii=False))
    params.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(set_parts)} WHERE task_id = ?", params)
    return True


async def update_task(task_id: str, fields: dict) -> bool:
    """安全更新任务字段。任务不存在返回 False。"""
    def _do():
        conn = _connect()
        try:
            ok = _update_task_sync(conn, task_id, fields)
            if ok:
                conn.commit()
            return ok
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def get_task(task_id: str) -> dict | None:
    def _do():
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def task_exists(task_id: str) -> bool:
    def _do():
        conn = _connect()
        try:
            row = conn.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return row is not None
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def delete_task(task_id: str):
    def _do():
        conn = _connect()
        try:
            conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)


async def delete_tasks(task_ids: list[str]):
    if not task_ids:
        return
    def _do():
        conn = _connect()
        try:
            placeholders = ",".join("?" * len(task_ids))
            conn.execute(f"DELETE FROM tasks WHERE task_id IN ({placeholders})", task_ids)
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)


# ── 查询 ────────────────────────────────────────────────────────

async def list_recent_tasks(limit: int = 50) -> list[dict]:
    """返回最近的任务（含处理中和已完成），用于前端恢复。"""
    def _do():
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def list_history(
    limit: int = 100,
    search: str = "",
    source_type: str = "",
) -> list[dict]:
    """列出已完成的摘要任务，支持搜索和来源过滤。"""
    def _do():
        conn = _connect()
        try:
            where = ["status = 'completed'", "summary != ''"]
            params: list = []
            if source_type:
                where.append("source_type = ?")
                params.append(source_type)
            if search.strip():
                where.append("(video_title LIKE ? OR summary LIKE ? OR script LIKE ? OR url LIKE ?)")
                q = f"%{search.strip()}%"
                params.extend([q, q, q, q])
            # 列表只返回轻量元数据 + 摘要，不返回 script 全文（一次 100 条可达兆级）。
            # 转录全文按需经 get_transcript()/GET /api/task/{id}/transcript 获取。
            # 注意 WHERE 仍可搜索 script，只是不把它放进结果。
            sql = (
                "SELECT task_id, status, url, source_type, source_value, video_title, "
                "summary, summary_language, created_at, updated_at, "
                "(script != '') AS has_transcript "
                f"FROM tasks WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT ?"
            )
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def get_transcript(task_id: str) -> str | None:
    """按需取转录全文（script 列）。任务不存在返回 None。"""
    def _do():
        conn = _connect()
        try:
            row = conn.execute("SELECT script FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                return None
            return row["script"] or ""
        finally:
            conn.close()
    return await _run_in_thread(_do)


# ── 任务队列 CRUD（串行执行，DB 持久化） ────────────────────

async def queue_enqueue(queue_name: str, item_type: str, item_key: str, payload: dict) -> dict:
    """入队。不做去重：同一个任务即使完全相同也直接排进队列，逐个执行
    （用户约定：任何来源的任务都无条件加入统一队列）。item_key 仅保留为
    分类/展示用途，不再用于幂等拦截。"""
    def _do():
        conn = _connect()
        try:
            # 计算新位置
            pos_row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM task_queue WHERE queue_name=?",
                (queue_name,)
            ).fetchone()
            new_pos = pos_row[0] if pos_row else 0
            item_id = str(uuid.uuid4())
            task_id = payload.get("task_id", "") if isinstance(payload, dict) else ""
            conn.execute(
                """INSERT INTO task_queue (id, queue_name, item_type, item_key, payload, status, task_id, position)
                   VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)""",
                (item_id, queue_name, item_type, item_key, json.dumps(payload, ensure_ascii=False), task_id, new_pos),
            )
            conn.commit()
            return {"id": item_id, "status": "queued", "duplicate": False}
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def queue_get_next(queue_name: str) -> dict | None:
    """获取队列中下一个待处理项（status='queued' 中 position 最小的）。"""
    def _do():
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM task_queue WHERE queue_name=? AND status='queued' ORDER BY position LIMIT 1",
                (queue_name,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def queue_claim_next(queue_name: str) -> dict | None:
    """DB 级原子认领下一项，保证跨 worker/进程也只有一个 processing。"""
    def _do():
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT 1 FROM task_queue WHERE queue_name=? AND status='processing' LIMIT 1",
                (queue_name,),
            ).fetchone()
            if active:
                conn.commit()
                return None

            row = conn.execute(
                "SELECT * FROM task_queue WHERE queue_name=? AND status='queued' ORDER BY position LIMIT 1",
                (queue_name,),
            ).fetchone()
            if not row:
                conn.commit()
                return None

            item = dict(row)
            try:
                payload = json.loads(item.get("payload", "{}"))
            except (json.JSONDecodeError, TypeError):
                payload = {}
            task_id = payload.get("task_id") if isinstance(payload, dict) else ""
            conn.execute(
                "UPDATE task_queue SET status='processing', task_id=?, started_at=datetime('now') WHERE id=?",
                (task_id or item["id"], item["id"]),
            )
            conn.commit()
            return item
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def queue_set_processing(item_id: str, task_id: str):
    """将队列项标记为处理中。"""
    def _do():
        conn = _connect()
        try:
            conn.execute(
                "UPDATE task_queue SET status='processing', task_id=?, started_at=datetime('now') WHERE id=?",
                (task_id, item_id),
            )
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)


async def queue_set_completed(item_id: str, result: dict = None):
    """将队列项标记为完成。"""
    def _do():
        conn = _connect()
        try:
            conn.execute(
                "UPDATE task_queue SET status='completed', completed_at=datetime('now'), result=? WHERE id=?",
                (json.dumps(result or {}, ensure_ascii=False), item_id),
            )
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)


async def queue_set_error(item_id: str, error: str):
    """将队列项标记为错误。"""
    def _do():
        conn = _connect()
        try:
            conn.execute(
                "UPDATE task_queue SET status='error', completed_at=datetime('now'), error=? WHERE id=?",
                (error, item_id),
            )
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)


async def queue_set_cancelled(item_id: str, result: dict = None):
    """将队列项标记为取消。"""
    def _do():
        conn = _connect()
        try:
            conn.execute(
                "UPDATE task_queue SET status='cancelled', completed_at=datetime('now'), result=? WHERE id=?",
                (json.dumps(result or {}, ensure_ascii=False), item_id),
            )
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)


async def queue_remove(item_id: str):
    """从队列中移除一项。"""
    def _do():
        conn = _connect()
        try:
            conn.execute("DELETE FROM task_queue WHERE id=?", (item_id,))
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)


async def queue_remove_by_task_id(queue_name: str, task_id: str) -> int:
    """根据 task_id 从指定队列中移除一项。返回删除数量。"""
    def _do():
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM task_queue WHERE queue_name=? AND task_id=?", (queue_name, task_id))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def queue_recover_stale(queue_name: str) -> int:
    """恢复启动时的残留 processing 项。返回修复数量。"""
    def _do():
        conn = _connect()
        try:
            stale = conn.execute(
                "SELECT id, task_id FROM task_queue WHERE queue_name=? AND status='processing'",
                (queue_name,)
            ).fetchall()
            fixed = 0
            for row in stale:
                item_id, task_id = row[0], row[1]
                if task_id:
                    task_row = conn.execute(
                        "SELECT json_extract(data, '$.status') FROM tasks WHERE task_id=?",
                        (task_id,)
                    ).fetchone()
                    task_status = task_row[0] if task_row else None
                    if task_status in (None, 'completed', 'error', 'cancelled'):
                        conn.execute(
                            "UPDATE task_queue SET status='error', error='服务器重启，任务已失效' WHERE id=?",
                            (item_id,)
                        )
                    else:
                        conn.execute(
                            "UPDATE task_queue SET status='queued' WHERE id=?",
                            (item_id,)
                        )
                else:
                    conn.execute(
                        "UPDATE task_queue SET status='error', error='服务器重启，任务已失效' WHERE id=?",
                        (item_id,)
                    )
                fixed += 1
            conn.commit()
            return fixed
        finally:
            conn.close()
    return await _run_in_thread(_do)


# 队列流安全投影：富化 processing 项时从 tasks 表借用的轻量进度字段。
# 绝不含 script/summary/translation 正文，也绝不含 api_key/model_base_url/model_id。
_QUEUE_PROGRESS_FIELDS = (
    "progress", "current_stage", "progress_key",
    "progress_step_current", "progress_step_total",
    "mode", "task_type", "stage_items", "result_items",
)


def _safe_source_label(payload: dict) -> str:
    """从 payload 提取一个可安全外露的来源标签（不含密钥）。"""
    if not isinstance(payload, dict):
        return ""
    entry = payload.get("entry_data") if isinstance(payload.get("entry_data"), dict) else {}
    return (
        payload.get("video_title")
        or payload.get("original_name")
        or entry.get("title")
        or payload.get("url")
        or payload.get("filename")
        or payload.get("entry_id")
        or ""
    )


def _normalize_single_processing(conn: sqlite3.Connection, queue_name: str):
    """修复历史/跨进程竞态造成的多 processing，只保留最近更新的一项。"""
    rows = conn.execute(
        """
        SELECT q.id, q.task_id, q.position, q.started_at, COALESCE(t.status, '') AS task_status,
               COALESCE(t.updated_at, '') AS task_updated
        FROM task_queue q
        LEFT JOIN tasks t ON t.task_id = q.task_id
        WHERE q.queue_name=? AND q.status='processing'
        ORDER BY task_updated DESC, q.started_at DESC, q.position DESC
        """,
        (queue_name,),
    ).fetchall()
    if len(rows) <= 1:
        return

    keep_id = rows[0]["id"]
    fixed = 0
    for row in rows[1:]:
        item_id = row["id"]
        task_id = row["task_id"] or ""
        task_status = row["task_status"]
        if task_status in ("completed", "error", "cancelled"):
            conn.execute(
                "UPDATE task_queue SET status=?, completed_at=datetime('now') WHERE id=?",
                (task_status, item_id),
            )
        else:
            conn.execute("UPDATE task_queue SET status='queued', started_at='' WHERE id=?", (item_id,))
            if task_id:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status='queued', updated_at=datetime('now'),
                        data=json_set(data, '$.message', 'task.queued', '$.progress', 0)
                    WHERE task_id=? AND status='processing'
                    """,
                    (task_id,),
                )
        fixed += 1
    conn.commit()
    logger.warning("队列 %s 检测到多个 processing，保留 %s，修复 %d 项", queue_name, keep_id, fixed)


def _enrich_processing_item(conn: sqlite3.Connection, item: dict, task_id: str):
    """把 processing 项按 task_id join tasks 表，补上轻量进度字段。"""
    row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        return
    task = _row_to_dict(row) or {}
    for key in _QUEUE_PROGRESS_FIELDS:
        if key in task:
            item[key] = task[key]
    item["task_status"] = task.get("status")
    # ready 标志按 refresh_task_view_state 同一口径派生，正文本身不外露。
    item["summary_ready"] = bool(task.get("summary_ready") or task.get("summary"))
    item["transcript_ready"] = bool(task.get("transcript_ready") or task.get("script"))
    if not item.get("source_label"):
        item["source_label"] = task.get("video_title") or task.get("url") or ""


async def queue_get_state(queue_name: str) -> dict:
    """获取队列状态（安全投影）。前端在刷新/挂载时调用以恢复状态。

    每个 item 只暴露 UI 所需的身份/状态字段；processing 项额外 join tasks 表
    富化轻量进度。绝不外露 payload 中的密钥（api_key/model_base_url/model_id）
    或正文（script/summary/translation）。
    """
    def _do():
        conn = _connect()
        try:
            _normalize_single_processing(conn, queue_name)
            rows = conn.execute(
                "SELECT * FROM task_queue WHERE queue_name=? ORDER BY position",
                (queue_name,)
            ).fetchall()
            items = []
            processing = None
            for row in rows:
                d = dict(row)
                try:
                    payload = json.loads(d.get("payload", "{}"))
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                task_id = payload.get("task_id") or d.get("task_id") or ""
                item = {
                    "id": d["id"],
                    "queue_name": d["queue_name"],
                    "task_id": task_id,
                    "status": d["status"],
                    "position": d["position"],
                    "job_kind": d.get("item_type", ""),
                    "item_type": d.get("item_type", ""),
                    "item_key": d.get("item_key", ""),
                    "source_label": _safe_source_label(payload),
                    "created_at": d.get("created_at", ""),
                    "started_at": d.get("started_at", ""),
                    "completed_at": d.get("completed_at", ""),
                    "error": d.get("error") or "",
                }
                if d["status"] == "processing" and task_id:
                    _enrich_processing_item(conn, item, task_id)
                    processing = item
                items.append(item)
            return {
                "queue_name": queue_name,
                "items": items,
                "processing": processing,
                "pending_count": sum(1 for i in items if i["status"] == "queued"),
            }
        finally:
            conn.close()
    return await _run_in_thread(_do)


def _queue_row_to_dict(row: sqlite3.Row) -> dict:
    """队列 REST 的安全投影，不返回原始 payload/result。"""
    d = dict(row)
    try:
        payload = json.loads(d.get("payload", "{}"))
    except (json.JSONDecodeError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    task_id = payload.get("task_id") or d.get("task_id") or ""
    return {
        "id": d["id"],
        "queue_name": d["queue_name"],
        "task_id": task_id,
        "status": d["status"],
        "position": d["position"],
        "job_kind": d.get("item_type", ""),
        "item_type": d.get("item_type", ""),
        "item_key": d.get("item_key", ""),
        "source_label": _safe_source_label(payload),
        "created_at": d.get("created_at", ""),
        "started_at": d.get("started_at", ""),
        "completed_at": d.get("completed_at", ""),
        "error": d.get("error") or "",
    }


async def queue_get_item(item_id: str) -> dict | None:
    """按队列项 id 取单项详情。"""
    def _do():
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM task_queue WHERE id=?", (item_id,)).fetchone()
            return _queue_row_to_dict(row) if row else None
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def queue_stats(queue_name: str) -> dict:
    """按状态聚合计数 + 队列长度，轻量(不返回 payload/result 全文)。"""
    def _do():
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM task_queue WHERE queue_name=? GROUP BY status",
                (queue_name,)
            ).fetchall()
            by_status = {r["status"]: r["n"] for r in rows}
            return {
                "queue_name": queue_name,
                "by_status": by_status,
                "total": sum(by_status.values()),
                "queued": by_status.get("queued", 0),
                "processing": by_status.get("processing", 0),
            }
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def queue_list_items(
    queue_name: str,
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """分页列出队列项，可按状态过滤。返回 {items, total}。"""
    def _do():
        conn = _connect()
        try:
            where = ["queue_name = ?"]
            params: list = [queue_name]
            if status:
                where.append("status = ?")
                params.append(status)
            clause = " AND ".join(where)
            total = conn.execute(
                f"SELECT COUNT(*) FROM task_queue WHERE {clause}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM task_queue WHERE {clause} ORDER BY position LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            return {"items": [_queue_row_to_dict(r) for r in rows], "total": total}
        finally:
            conn.close()
    return await _run_in_thread(_do)


async def queue_clear_completed(queue_name: str) -> int:
    """清除已完成/错误的队列项。返回清除数量。"""
    def _do():
        conn = _connect()
        try:
            cur = conn.execute(
                "DELETE FROM task_queue WHERE queue_name=? AND status IN ('completed', 'error', 'cancelled')",
                (queue_name,)
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
    return await _run_in_thread(_do)


# ── RSS 同步操作（供 RSSReader 内部使用） ────────────────────

def rss_load_sync() -> dict:
    """加载所有 RSS 订阅（同步）。"""
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM rss_feeds").fetchall()
        feeds = {}
        for row in rows:
            d = dict(row)
            d["favorite"] = bool(d.get("favorite", 0))
            try:
                d["entries"] = json.loads(d.get("entries", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["entries"] = []
            feeds[d["id"]] = d
        return feeds
    finally:
        conn.close()


def rss_save_sync(feeds: dict):
    """保存所有 RSS 订阅（同步，替换全部数据）。"""
    def _s(v):
        return "" if v is None else v
    conn = _connect()
    try:
        conn.execute("DELETE FROM rss_feeds")
        for feed_id, feed in feeds.items():
            entries_json = json.dumps(feed.get("entries", []) or [], ensure_ascii=False)
            conn.execute(
                """INSERT INTO rss_feeds (id, url, title, type, favorite,
                   added_at, last_checked, last_error, entries)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    _s(feed_id),
                    _s(feed.get("url", "")),
                    _s(feed.get("title", "")),
                    _s(feed.get("type", "")),
                    int(feed.get("favorite", False)),
                    _s(feed.get("added_at", "")),
                    _s(feed.get("last_checked", "")),
                    _s(feed.get("last_error", "")),
                    entries_json,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def rss_migrate_from_json(data_dir: Path):
    """从旧 JSON 文件迁移 RSS 数据到 SQLite。"""
    json_path = data_dir / "rss_feeds.json"
    if not json_path.exists():
        return
    try:
        old_feeds = json.loads(json_path.read_text(encoding="utf-8"))
        if not old_feeds:
            return
        conn = _connect()
        try:
            existing = conn.execute("SELECT COUNT(*) FROM rss_feeds").fetchone()
            if existing and existing[0] > 0:
                return
            for feed_id, feed in old_feeds.items():
                def _s(v): return "" if v is None else v
                entries_json = json.dumps(feed.get("entries", []) or [], ensure_ascii=False)
                conn.execute(
                    """INSERT OR REPLACE INTO rss_feeds (id, url, title, type, favorite,
                       added_at, last_checked, last_error, entries)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        _s(feed_id),
                        _s(feed.get("url", "")),
                        _s(feed.get("title", "")),
                        _s(feed.get("type", "")),
                        int(feed.get("favorite", False)),
                        _s(feed.get("added_at", "")),
                        _s(feed.get("last_checked", "")),
                        _s(feed.get("last_error", "")),
                        entries_json,
                    ),
                )
            conn.commit()
            logger.info(f"从 rss_feeds.json 迁移了 {len(old_feeds)} 个订阅")
            json_path.rename(json_path.with_suffix(".json.bak"))
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"RSS 数据迁移失败: {e}")


def tasks_migrate_from_json(data_dir: Path):
    """从旧 tasks.json 迁移已完成任务到 SQLite。"""
    json_path = data_dir / "tasks.json"
    if not json_path.exists():
        return
    try:
        old_tasks = json.loads(json_path.read_text(encoding="utf-8"))
        if not old_tasks:
            return
        conn = _connect()
        try:
            existing = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
            if existing and existing[0] > 0:
                return  # 已有数据，不覆盖
            count = 0
            for task_id, task in old_tasks.items():
                if task.get("status") != "completed":
                    continue
                fixed, extra = _sync_columns(task)
                conn.execute(
                    """INSERT OR IGNORE INTO tasks
                       (task_id, status, url, source_type, source_value,
                        video_title, summary, summary_language, data, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        task_id,
                        fixed["status"],
                        fixed["url"],
                        fixed["source_type"],
                        fixed["source_value"],
                        fixed["video_title"],
                        fixed["summary"],
                        fixed["summary_language"],
                        json.dumps(extra, ensure_ascii=False),
                        task.get("created_at", "") or "",
                        task.get("updated_at", "") or "",
                    ),
                )
                count += 1
            conn.commit()
            if count:
                logger.info(f"从 tasks.json 迁移了 {count} 条已完成任务")
                json_path.rename(json_path.with_suffix(".json.bak"))
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Tasks 数据迁移失败: {e}")
