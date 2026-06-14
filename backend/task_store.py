"""任务状态管理：阶段进度、SSE 广播与数据库持久化。

所有任务数据通过 db.py 持久化到 SQLite。
process_urls / active_tasks / sse_connections 为运行时状态。
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from db import (
    get_task as _db_get_task,
    create_task as _db_create_task,
    update_task as _db_update_task,
    delete_task as _db_delete_task,
)

logger = logging.getLogger(__name__)


# ── 项目根目录（兼容 PyInstaller 打包） ──
def _get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def _get_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "ai-transcriber"
        elif sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ai-transcriber"
        else:
            base = Path.home() / ".local" / "share" / "ai-transcriber"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return _get_project_root() / "temp"


PROJECT_ROOT = _get_project_root()
TEMP_DIR = _get_data_dir()
TEMP_DIR.mkdir(exist_ok=True)


def cleanup_stale_temp(max_age_hours: float = 24.0) -> int:
    """清扫过期临时/下载文件，避免数据目录无限膨胀。

    删除范围：上传原件、归一化音频、字幕临时目录，以及下载功能产生的
    视频/音频/字幕文件。保留 transcript_/summary_/raw_/summary-prompt_ 等
    .md 历史记录、数据库、日志和 Whisper 模型缓存。
    """
    import time

    removed = 0
    now = time.time()
    cutoff = max_age_hours * 3600
    transient_prefixes = ("upload_", "subs_")
    download_suffixes = {
        ".mp4", ".mkv", ".webm", ".mov", ".avi",
        ".m4a", ".mp3", ".opus", ".aac", ".flac", ".wav", ".ogg",
        ".vtt", ".srt", ".ass", ".part",
    }
    try:
        for p in TEMP_DIR.iterdir():
            name = p.name
            suffix = p.suffix.lower()
            should_delete = (
                name.startswith(transient_prefixes)
                or name.endswith("_fixed.m4a")
                or (p.is_file() and suffix in download_suffixes)
            )
            if not should_delete:
                continue
            try:
                if now - p.stat().st_mtime < cutoff:
                    continue
                if p.is_dir():
                    import shutil
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"清扫过期临时/下载文件失败: {e}")
    if removed:
        logger.info(f"启动清扫：移除 {removed} 个过期临时/下载文件")
    return removed

# ── 运行时状态（不持久化） ──
processing_urls: set[str] = set()       # 正在处理的 URL（防重）
active_tasks: dict[str, asyncio.Task] = {}  # 活跃 asyncio 任务句柄
sse_connections: dict[str, list[asyncio.Queue]] = {}  # SSE 连接队列
sse_lock = asyncio.Lock()              # 保护 sse_connections 的并发访问


async def update_task(task_id: str, **fields) -> bool:
    """安全更新任务字段。任务不存在返回 False。"""
    if "updated_at" not in fields:
        fields["updated_at"] = None  # 让 DB 层用 datetime('now')
    return await _db_update_task(task_id, fields)


def finish_task(task_id: str, dedup_url: Optional[str] = None):
    """清理运行时句柄（数据已持久化在 DB，这里只清理内存状态）。"""
    active_tasks.pop(task_id, None)
    if dedup_url:
        processing_urls.discard(dedup_url)


async def broadcast_task_update(task_id: str, task_data: dict):
    """向所有 SSE 客户端广播任务状态。受 sse_lock 保护，使用 put_nowait
    配合 maxsize=1 的队列：满时排空旧值再写入，确保每条连接只保留最新状态。"""
    await refresh_task_view_state(task_id)
    task_data = await _db_get_task(task_id) or task_data
    data_json = json.dumps(task_data, ensure_ascii=False)
    async with sse_lock:
        if task_id not in sse_connections:
            return
        queues = list(sse_connections[task_id])
        if not queues:
            del sse_connections[task_id]
            return
        logger.info(
            f"广播任务更新: {task_id}, 状态: {task_data.get('status')}, 连接数: {len(queues)}"
        )
        bad = []
        for queue in queues:
            try:
                queue.put_nowait(data_json)
            except asyncio.QueueFull:
                # 排空旧值，放入最新状态
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(data_json)
                except asyncio.QueueFull:
                    bad.append(queue)
            except Exception:
                bad.append(queue)
        for queue in bad:
            try:
                sse_connections[task_id].remove(queue)
            except ValueError:
                pass
        if task_id in sse_connections and not sse_connections[task_id]:
            del sse_connections[task_id]


# ── 阶段定义 ─────────────────────────────────────────────────
STAGE_DEFINITIONS = {
    "url_summary": [
        "identify_source", "find_subtitles", "read_subtitles",
        "download_audio", "prepare_audio", "transcribe",
        "read_content", "gen_summary_prompt", "gen_summary",
        "optimize_transcript",
    ],
    "local_audio": [
        "read_file", "prepare_audio", "transcribe",
        "read_content", "gen_summary_prompt", "gen_summary",
        "optimize_transcript",
    ],
    "local_text": [
        "read_file", "read_content", "gen_summary_prompt",
        "gen_summary", "optimize_transcript",
    ],
    "download_only": [
        "identify_resource", "download",
    ],
    "retry": [
        "read_content", "gen_summary_prompt", "gen_summary",
        "optimize_transcript",
    ],
}


async def init_task_stages(task_id: str, task_type: str):
    stage_keys = STAGE_DEFINITIONS.get(task_type, STAGE_DEFINITIONS["url_summary"])
    stage_list = [{"name": key} for key in stage_keys]
    await update_task(task_id,
        stages=stage_list,
        skipped_stages=[],
        current_stage="",
        current_stage_index=-1,
        summary_ready=False,
        transcript_ready=False,
        task_type=task_type,
    )
    await refresh_task_view_state(task_id)
    return stage_list


async def skip_task_stages(task_id: str, stage_names):
    task = await _db_get_task(task_id)
    if not task:
        return
    existing = set(task.get("skipped_stages", []))
    existing.update(stage_names or [])
    await update_task(task_id, skipped_stages=sorted(existing))
    await refresh_task_view_state(task_id)


async def refresh_task_view_state(task_id: str):
    task = await _db_get_task(task_id)
    if not task:
        return

    stages = task.get("stages", [])
    skipped = set(task.get("skipped_stages", []))
    current_stage = task.get("current_stage")
    current_index = task.get("current_stage_index", -1)
    completed = task.get("status") == "completed"

    stage_items = []
    for index, stage in enumerate(stages):
        if stage["name"] in skipped:
            state = "skipped"
        elif completed or index < current_index:
            state = "done"
        elif stage["name"] == current_stage:
            state = "current"
        else:
            state = "pending"
        stage_items.append({
            "name": stage["name"],
            "state": state,
        })

    active_stages = [s for s in stages if s["name"] not in skipped]
    active_index = next(
        (i for i, stage in enumerate(active_stages) if stage["name"] == current_stage),
        -1,
    )
    if completed:
        progress_key = "completed"
        progress_step_current = 0
        progress_step_total = 0
    elif active_stages and active_index >= 0:
        progress_key = "step"
        progress_step_current = active_index + 1
        progress_step_total = len(active_stages)
    else:
        progress_key = "waiting"
        progress_step_current = 0
        progress_step_total = 0

    summary_ready = bool(task.get("summary_ready") or task.get("summary"))
    transcript_ready = bool(task.get("transcript_ready") or task.get("script"))

    await update_task(task_id,
        progress_key=progress_key,
        progress_step_current=progress_step_current,
        progress_step_total=progress_step_total,
        stage_items=stage_items,
        result_items=[
            {"key": "summary", "state": "ready" if summary_ready else "waiting"},
            {"key": "transcript", "state": "ready" if transcript_ready else "waiting"},
        ],
    )


async def resolve_stage_index(task_id: str, stage) -> int:
    if isinstance(stage, int):
        return stage
    task = await _db_get_task(task_id)
    if not task:
        return -1
    stages = task.get("stages", [])
    for i, s in enumerate(stages):
        if s["name"] == stage:
            return i
    return -1


async def set_task_stage(task_id: str, stage, stage_progress: float = 0):
    task = await _db_get_task(task_id)
    if not task:
        return
    stages = task.get("stages", [])
    stage_index = await resolve_stage_index(task_id, stage)
    if not stages or stage_index < 0 or stage_index >= len(stages):
        return

    skipped = set(task.get("skipped_stages", []))
    active_stages = [s for s in stages if s["name"] not in skipped]
    total_active = len(active_stages)
    if total_active <= 0:
        return

    active_index = next(
        (i for i, s in enumerate(active_stages) if s["name"] == stages[stage_index]["name"]),
        -1,
    )
    total = (active_index + 1) / total_active * 100.0 if active_index >= 0 else 0.0

    await update_task(task_id,
        current_stage=stages[stage_index]["name"],
        current_stage_index=stage_index,
        progress=round(total, 1),
    )


async def broadcast_stage(task_id: str, stage, stage_progress: float = 0):
    await set_task_stage(task_id, stage, stage_progress)
    task = await _db_get_task(task_id)
    if task:
        await broadcast_task_update(task_id, task)
    await asyncio.sleep(0.05)
