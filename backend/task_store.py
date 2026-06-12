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

# ── 运行时状态（不持久化） ──
processing_urls: set[str] = set()       # 正在处理的 URL（防重）
active_tasks: dict[str, asyncio.Task] = {}  # 活跃 asyncio 任务句柄
sse_connections: dict[str, list[asyncio.Queue]] = {}  # SSE 连接队列


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
    """向所有 SSE 客户端广播任务状态。先刷新视图状态再广播。"""
    await refresh_task_view_state(task_id)
    # 重新从 DB 读取最新状态
    task_data = await _db_get_task(task_id) or task_data
    logger.info(
        f"广播任务更新: {task_id}, 状态: {task_data.get('status')}, "
        f"连接数: {len(sse_connections.get(task_id, []))}"
    )
    if task_id in sse_connections:
        to_remove = []
        for queue in sse_connections[task_id]:
            try:
                await queue.put(json.dumps(task_data, ensure_ascii=False))
            except Exception as e:
                logger.warning(f"发送 SSE 消息失败: {e}")
                to_remove.append(queue)
        for queue in to_remove:
            sse_connections[task_id].remove(queue)
        if not sse_connections[task_id]:
            del sse_connections[task_id]


# ── 阶段定义 ─────────────────────────────────────────────────
STAGE_DEFINITIONS = {
    "url_summary": [
        ("识别来源", "正在识别链接", "确认链接有效，并准备本次任务使用的摘要模型。"),
        ("查找字幕", "正在查找字幕", "优先检查平台字幕，字幕存在时直接进入文本处理。"),
        ("读取字幕", "正在读取字幕", "把平台字幕读取为原始转录文本。"),
        ("下载音频", "正在下载音频", "字幕不可用时下载音频，供本地转录使用。"),
        ("准备音频", "正在准备音频", "把音频转换为 Whisper 可处理的格式。"),
        ("转录", "正在本地转录", "使用 Whisper 把音频转成原始文本。"),
        ("阅读内容", "正在阅读内容", "清理原始文本，检测语言，并准备摘要输入。"),
        ("生成摘要prompt", "正在生成摘要prompt", "为当前内容和目标语言构建摘要指令。"),
        ("生成摘要", "正在生成摘要", "调用语言模型生成可先阅读的摘要。"),
        ("优化转录", "摘要已可阅读，正在优化转录文本", "继续润色完整转录文本，完成后任务才结束。"),
    ],
    "local_audio": [
        ("读取文件", "正在读取文件", "读取本地上传文件并确认文件内容可用。"),
        ("准备音频", "正在准备音频", "把本地媒体转换为 Whisper 可处理的音频格式。"),
        ("转录", "正在本地转录", "使用 Whisper 把音频转成原始文本。"),
        ("阅读内容", "正在阅读内容", "清理原始文本，检测语言，并准备摘要输入。"),
        ("生成摘要prompt", "正在生成摘要prompt", "为当前内容和目标语言构建摘要指令。"),
        ("生成摘要", "正在生成摘要", "调用语言模型生成可先阅读的摘要。"),
        ("优化转录", "摘要已可阅读，正在优化转录文本", "继续润色完整转录文本，完成后任务才结束。"),
    ],
    "local_text": [
        ("读取文件", "正在读取文件", "读取文本文件，并把正文作为原始转录内容。"),
        ("阅读内容", "正在阅读内容", "清理原始文本，检测语言，并准备摘要输入。"),
        ("生成摘要prompt", "正在生成摘要prompt", "为当前内容和目标语言构建摘要指令。"),
        ("生成摘要", "正在生成摘要", "调用语言模型生成可先阅读的摘要。"),
        ("优化转录", "摘要已可阅读，正在优化转录文本", "整理文本输出文件，完成后任务才结束。"),
    ],
    "download_only": [
        ("识别资源", "正在识别资源", "解析链接并确认可下载资源。"),
        ("下载", "正在下载", "下载所选媒体或字幕文件。"),
    ],
    "retry": [
        ("阅读内容", "正在阅读内容", "读取已有转录文本并准备重新摘要。"),
        ("生成摘要prompt", "正在生成摘要prompt", "为重新摘要构建新的摘要指令。"),
        ("生成摘要", "正在生成摘要", "调用语言模型生成新的摘要结果。"),
        ("优化转录", "摘要已可阅读，正在优化转录文本", "重新整理完整转录文本，完成后任务才结束。"),
    ],
}


async def init_task_stages(task_id: str, task_type: str):
    stages = STAGE_DEFINITIONS.get(task_type, STAGE_DEFINITIONS["url_summary"])
    stage_list = [
        {"name": s[0], "label": s[1], "detail": s[2] if len(s) > 2 else s[1]}
        for s in stages
    ]
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
            state, state_label = "skipped", "已跳过"
        elif completed or index < current_index:
            state, state_label = "done", "已完成"
        elif stage["name"] == current_stage:
            state, state_label = "current", "进行中"
        else:
            state, state_label = "pending", "等待中"
        stage_items.append({
            "name": stage["name"],
            "label": stage.get("label", stage["name"]),
            "detail": stage.get("detail", stage.get("label", stage["name"])),
            "state": state,
            "state_label": state_label,
        })

    active_stages = [s for s in stages if s["name"] not in skipped]
    active_index = next(
        (i for i, stage in enumerate(active_stages) if stage["name"] == current_stage),
        -1,
    )
    if completed:
        progress_label = "已完成"
    elif active_stages and active_index >= 0:
        progress_label = f"第 {active_index + 1}/{len(active_stages)} 步"
    else:
        progress_label = "等待开始"

    summary_ready = bool(task.get("summary_ready") or task.get("summary"))
    transcript_ready = bool(task.get("transcript_ready") or task.get("script"))
    mode = task.get("mode")

    await update_task(task_id,
        progress_label=progress_label,
        mode_label={"subtitle": "字幕", "whisper": "Whisper"}.get(mode, ""),
        stage_items=stage_items,
        result_items=[
            {"key": "summary", "label": "摘要", "state": "ready" if summary_ready else "waiting",
             "state_label": "可用" if summary_ready else "等待中"},
            {"key": "transcript", "label": "转录文本", "state": "ready" if transcript_ready else "waiting",
             "state_label": "可用" if transcript_ready else "等待中"},
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

    s = stages[stage_index]
    await update_task(task_id,
        current_stage=s["name"],
        current_stage_label=s["label"],
        current_stage_detail=s.get("detail", s["label"]),
        current_stage_index=stage_index,
        progress=round(total, 1),
        message=s["label"],
    )


async def broadcast_stage(task_id: str, stage, stage_progress: float = 0):
    await set_task_stage(task_id, stage, stage_progress)
    task = await _db_get_task(task_id)
    if task:
        await broadcast_task_update(task_id, task)
    await asyncio.sleep(0.05)
