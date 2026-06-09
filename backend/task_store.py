import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
TEMP_DIR = PROJECT_ROOT / "temp"
TEMP_DIR.mkdir(exist_ok=True)

TASKS_FILE = TEMP_DIR / "tasks.json"
tasks_lock = threading.Lock()


def load_tasks():
    """加载任务状态"""
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_tasks(tasks_data):
    """保存任务状态"""
    try:
        with tasks_lock:
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存任务状态失败: {e}")


# 启动时加载任务状态，并清理旧会话中的"处理中"任务（服务器重启后这些任务已失效）
tasks = load_tasks()
stale_processing = [tid for tid, t in tasks.items() if t.get("status") == "processing"]
if stale_processing:
    for tid in stale_processing:
        tasks[tid]["status"] = "error"
        tasks[tid]["error"] = "服务器重启，任务已失效"
        tasks[tid]["message"] = "任务因服务器重启而失效，请重新提交"
        logger.info(f"清理失效任务: {tid}")
    save_tasks(tasks)

# 存储正在处理的URL，防止重复处理
processing_urls = set()
# 存储活跃的任务对象（摘要/上传/RSS/下载），用于控制和取消
active_tasks = {}
# 存储SSE连接，用于实时推送状态更新
sse_connections = {}


def finish_task(task_id: str, dedup_url: Optional[str] = None):
    """任务结束（成功或失败）时统一清理活跃任务句柄与去重 URL。"""
    active_tasks.pop(task_id, None)
    if dedup_url:
        processing_urls.discard(dedup_url)


async def broadcast_task_update(task_id: str, task_data: dict):
    """向所有连接的SSE客户端广播任务状态更新"""
    refresh_task_view_state(task_id)
    task_data = tasks.get(task_id, task_data)
    logger.info(
        f"广播任务更新: {task_id}, 状态: {task_data.get('status')}, "
        f"连接数: {len(sse_connections.get(task_id, []))}"
    )
    if task_id in sse_connections:
        connections_to_remove = []
        for queue in sse_connections[task_id]:
            try:
                await queue.put(json.dumps(task_data, ensure_ascii=False))
                logger.debug(f"消息已发送到队列: {task_id}")
            except Exception as e:
                logger.warning(f"发送消息到队列失败: {e}")
                connections_to_remove.append(queue)

        # 移除断开的连接
        for queue in connections_to_remove:
            sse_connections[task_id].remove(queue)

        # 如果没有连接了，清理该任务的连接列表
        if not sse_connections[task_id]:
            del sse_connections[task_id]


# ── 阶段权重定义 ──────────────────────────────────────────────
# 每种任务类型的阶段列表，顺序执行。
# weight 是相对权重，最终总进度会按该任务所有阶段权重归一化到 0–100%。
STAGE_WEIGHTS = {
    "url_summary": [
        ("识别来源", 5, "正在识别链接", "确认链接有效，并准备本次任务使用的摘要模型。"),
        ("查找字幕", 10, "正在查找字幕", "优先检查平台字幕，字幕存在时直接进入文本处理。"),
        ("读取字幕", 20, "正在读取字幕", "把平台字幕读取为原始转录文本。"),
        ("下载音频", 20, "正在下载音频", "字幕不可用时下载音频，供本地转录使用。"),
        ("准备音频", 10, "正在准备音频", "把音频转换为 Whisper 可处理的格式。"),
        ("转录", 25, "正在本地转录", "使用 Whisper 把音频转成原始文本。"),
        ("阅读内容", 5, "正在阅读内容", "清理原始文本，检测语言，并准备摘要输入。"),
        ("生成摘要prompt", 12, "正在生成摘要prompt", "为当前内容和目标语言构建摘要指令。"),
        ("生成摘要", 13, "正在生成摘要", "调用语言模型生成可先阅读的摘要。"),
        ("优化转录", 15, "摘要已可阅读，正在优化转录文本", "继续润色完整转录文本，完成后任务才结束。"),
    ],
    "local_audio": [
        ("读取文件", 5, "正在读取文件", "读取本地上传文件并确认文件内容可用。"),
        ("准备音频", 15, "正在准备音频", "把本地媒体转换为 Whisper 可处理的音频格式。"),
        ("转录", 50, "正在本地转录", "使用 Whisper 把音频转成原始文本。"),
        ("阅读内容", 5, "正在阅读内容", "清理原始文本，检测语言，并准备摘要输入。"),
        ("生成摘要prompt", 12, "正在生成摘要prompt", "为当前内容和目标语言构建摘要指令。"),
        ("生成摘要", 13, "正在生成摘要", "调用语言模型生成可先阅读的摘要。"),
        ("优化转录", 15, "摘要已可阅读，正在优化转录文本", "继续润色完整转录文本，完成后任务才结束。"),
    ],
    "local_text": [
        ("读取文件", 10, "正在读取文件", "读取文本文件，并把正文作为原始转录内容。"),
        ("阅读内容", 30, "正在阅读内容", "清理原始文本，检测语言，并准备摘要输入。"),
        ("生成摘要prompt", 30, "正在生成摘要prompt", "为当前内容和目标语言构建摘要指令。"),
        ("生成摘要", 30, "正在生成摘要", "调用语言模型生成可先阅读的摘要。"),
        ("优化转录", 10, "摘要已可阅读，正在优化转录文本", "整理文本输出文件，完成后任务才结束。"),
    ],
    "download_only": [
        ("识别资源", 15, "正在识别视频资源", "解析链接并确认可下载资源。"),
        ("下载", 85, "正在下载视频", "下载所选视频、音频或字幕文件。"),
    ],
    "retry": [
        ("阅读内容", 15, "正在阅读内容", "读取已有转录文本并准备重新摘要。"),
        ("生成摘要prompt", 35, "正在生成摘要prompt", "为重新摘要构建新的摘要指令。"),
        ("生成摘要", 50, "正在生成摘要", "调用语言模型生成新的摘要结果。"),
        ("优化转录", 20, "摘要已可阅读，正在优化转录文本", "重新整理完整转录文本，完成后任务才结束。"),
    ],
}


def init_task_stages(task_id: str, task_type: str):
    """初始化任务的阶段信息，返回阶段列表。"""
    stages = STAGE_WEIGHTS.get(task_type, STAGE_WEIGHTS["url_summary"])
    stage_list = [
        {
            "name": s[0],
            "weight": s[1],
            "label": s[2],
            "detail": s[3] if len(s) > 3 else s[2],
        }
        for s in stages
    ]
    tasks[task_id].update({
        "stages": stage_list,
        "skipped_stages": [],
        "current_stage": "",
        "current_stage_progress": 0,
        "current_stage_index": -1,
        "completed_weight": 0,
        "summary_ready": False,
        "transcript_ready": False,
        "task_type": task_type,
    })
    refresh_task_view_state(task_id)
    return stage_list


def skip_task_stages(task_id: str, stage_names):
    """记录因任务分支不需要执行的阶段，供进度计算和前端展示使用。"""
    if task_id not in tasks:
        return
    existing = set(tasks[task_id].get("skipped_stages", []))
    existing.update(stage_names or [])
    tasks[task_id]["skipped_stages"] = sorted(existing)
    refresh_task_view_state(task_id)


def refresh_task_view_state(task_id: str):
    """生成前端可直接展示的任务状态文案和阶段链条。"""
    if task_id not in tasks:
        return

    task = tasks[task_id]
    stages = task.get("stages", [])
    skipped = set(task.get("skipped_stages", []))
    current_stage = task.get("current_stage")
    current_index = task.get("current_stage_index", -1)
    current_stage_progress = max(0.0, min(100.0, float(task.get("current_stage_progress") or 0)))
    completed = task.get("status") == "completed"

    stage_items = []
    for index, stage in enumerate(stages):
        if stage["name"] in skipped:
            state = "skipped"
            state_label = "已跳过"
        elif completed or index < current_index:
            state = "done"
            state_label = "已完成"
        elif stage["name"] == current_stage:
            state = "current"
            state_label = "进行中"
        else:
            state = "pending"
            state_label = "等待中"
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
        progress_label = f"第 {active_index + 1}/{len(active_stages)} 步 · 本步 {round(current_stage_progress)}%"
    else:
        progress_label = "等待开始"

    summary_ready = bool(task.get("summary_ready") or task.get("summary"))
    transcript_ready = bool(task.get("transcript_ready") or task.get("script"))
    mode = task.get("mode")
    task["progress_label"] = progress_label
    task["mode_label"] = {"subtitle": "字幕", "whisper": "Whisper"}.get(mode, "")
    task["stage_items"] = stage_items
    task["result_items"] = [
        {
            "key": "summary",
            "label": "摘要",
            "state": "ready" if summary_ready else "waiting",
            "state_label": "可用" if summary_ready else "等待中",
        },
        {
            "key": "transcript",
            "label": "转录文本",
            "state": "ready" if transcript_ready else "waiting",
            "state_label": "可用" if transcript_ready else "等待中",
        },
    ]


def resolve_stage_index(task_id: str, stage) -> int:
    """阶段定位：接受整数下标或阶段名，统一返回下标，未找到返回 -1。"""
    if isinstance(stage, int):
        return stage
    stages = tasks.get(task_id, {}).get("stages", [])
    for i, s in enumerate(stages):
        if s["name"] == stage:
            return i
    return -1


def set_task_stage(task_id: str, stage, stage_progress: float = 0):
    """设置当前阶段和进度，自动计算总进度。stage 可为下标或阶段名。"""
    if task_id not in tasks:
        return
    stages = tasks[task_id].get("stages", [])
    stage_index = resolve_stage_index(task_id, stage)
    if not stages or stage_index < 0 or stage_index >= len(stages):
        return

    stage_progress = max(0.0, min(100.0, float(stage_progress or 0)))
    skipped = set(tasks[task_id].get("skipped_stages", []))
    total_weight = sum(s["weight"] for s in stages if s["name"] not in skipped)
    if total_weight <= 0:
        return

    completed_units = sum(
        s["weight"] for s in stages[:stage_index] if s["name"] not in skipped
    )
    current_weight = stages[stage_index]["weight"]
    if stages[stage_index]["name"] in skipped:
        current_weight = 0
    total_units = completed_units + current_weight * (stage_progress / 100.0)
    total = total_units / total_weight * 100.0

    tasks[task_id].update({
        "current_stage": stages[stage_index]["name"],
        "current_stage_label": stages[stage_index]["label"],
        "current_stage_detail": stages[stage_index].get("detail", stages[stage_index]["label"]),
        "current_stage_progress": round(stage_progress, 1),
        "current_stage_index": stage_index,
        "completed_weight": round(completed_units / total_weight * 100.0, 1),
        "progress": round(total, 1),
        "message": stages[stage_index]["label"],
    })


async def broadcast_stage(task_id: str, stage, stage_progress: float = 0):
    """设置阶段并广播。stage 可为下标或阶段名。"""
    set_task_stage(task_id, stage, stage_progress)
    await broadcast_task_update(task_id, tasks[task_id])
    await asyncio.sleep(0.05)
