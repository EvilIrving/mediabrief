"""SQLite 数据库层：任务持久化、历史查询。

使用内建 sqlite3 + asyncio.to_thread，不增加额外依赖。
所有任务以 JSON blob 存储，提供 get/update/list/delete 操作。
"""
import json
import logging
import sqlite3
import asyncio
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "temp" / "transcriber.db"
_write_lock = threading.Lock()


def _ensure_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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
            conn.commit()
        finally:
            conn.close()
    await _run_in_thread(_do)
    # 从旧 JSON 文件迁移数据
    await _run_in_thread(rss_migrate_from_json, DB_PATH.parent)
    await _run_in_thread(tasks_migrate_from_json, DB_PATH.parent)


# ── 核心 CRUD ──────────────────────────────────────────────────

async def _run_in_thread(fn, *args):
    return await asyncio.to_thread(fn, *args)


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    # 合并 JSON data 字段到顶层，但不覆盖固定列
    try:
        extra = json.loads(d.pop("data", "{}"))
    except (json.JSONDecodeError, TypeError):
        extra = {}
    d.update(extra)
    return d


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
    }
    extra = {k: v for k, v in row.items() if k not in fixed and k not in ("task_id", "created_at", "updated_at", "data")}
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
    fixed, new_extra = _sync_columns(fields)
    current_extra.update(new_extra)
    # 固定列有值则更新
    set_parts = ["updated_at = datetime('now')"]
    params = []
    for col in ("status", "url", "source_type", "source_value",
                "video_title", "summary", "summary_language"):
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
                where.append("(video_title LIKE ? OR summary LIKE ? OR url LIKE ?)")
                q = f"%{search.strip()}%"
                params.extend([q, q, q])
            sql = f"SELECT * FROM tasks WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_dict(r) for r in rows]
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
