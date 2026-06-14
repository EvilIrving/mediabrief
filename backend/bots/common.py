"""Bot 通用逻辑：URL 提取、超长消息分片、以及「链接→转录→结果」的共享跑法。

所有平台共用这里：复用统一任务队列（process_video），保证 Bot 提交的任务
与网页端共享并发控制、出现在历史记录里，体验一致。Bot 侧通过轮询 DB 任务状态
观察完成，再把摘要 + 转录回传给用户。
"""
from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from db import create_task as _db_create_task, get_task as _db_get_task, get_transcript
from task_queue import queue_manager
from task_store import TEMP_DIR

from .base import LLMConfig

_URL_PATTERN = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)

# 轮询任务状态的间隔与上限（30 分钟），避免管线异常时 Bot 协程永久挂起。
_POLL_INTERVAL_SECONDS = 2.0
_POLL_TIMEOUT_SECONDS = 30 * 60


def extract_url(text: str) -> Optional[str]:
    if not text:
        return None
    match = _URL_PATTERN.search(text)
    return match.group(0).rstrip(").,;") if match else None


def split_long_message(text: str, max_len: int = 4000) -> list[str]:
    """按段落 / 行边界把超长文本切片，尽量不在句子中间断开。"""
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        window = remaining[:max_len]
        # 优先在段落边界切，其次换行，最后兜底硬切。
        split_at = window.rfind("\n\n")
        if split_at < max_len // 2:
            split_at = window.rfind("\n")
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


@dataclass
class BotTaskResult:
    status: str  # "completed" | "error" | "timeout"
    summary: str = ""
    result_path: Optional[Path] = None  # 摘要 + 全文合并的 .md，回传时作为文档发送
    video_title: str = ""
    error: str = ""


async def run_transcription(url: str, llm: LLMConfig) -> BotTaskResult:
    """把链接作为一个标准任务排进统一队列，轮询直到完成，返回结果。

    复用 process_video 队列，与网页端共享并发与历史记录。
    """
    task_id = str(uuid.uuid4())
    await _db_create_task(task_id, {
        "status": "queued",
        "progress": 0,
        "message": "task.queued",
        "script": None,
        "summary": None,
        "error": None,
        "url": url,
        "source_type": "url",
        "source_value": url,
    })

    await queue_manager.enqueue("tasks", "process_video", f"process_video:{url}", {
        "task_id": task_id,
        "url": url,
        "summary_language": llm.summary_language or "zh",
        "api_key": llm.api_key,
        "model_base_url": llm.base_url,
        "model_id": llm.model,
        "whisper_model": llm.whisper_model,
    })

    waited = 0.0
    while waited < _POLL_TIMEOUT_SECONDS:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        waited += _POLL_INTERVAL_SECONDS
        task = await _db_get_task(task_id)
        if not task:
            continue
        status = task.get("status")
        if status == "completed":
            transcript = await get_transcript(task_id) or ""
            summary = task.get("summary", "") or ""
            title = task.get("video_title", "") or ""
            path = _write_result_file(task_id, title, summary, transcript)
            return BotTaskResult(
                status="completed",
                summary=summary,
                result_path=path,
                video_title=title,
            )
        if status in ("error", "cancelled"):
            return BotTaskResult(
                status="error",
                error=task.get("error_message") or task.get("message") or task.get("error") or "处理失败",
            )

    return BotTaskResult(status="timeout", error="处理超时")


def _write_result_file(task_id: str, title: str, summary: str, transcript: str) -> Optional[Path]:
    """把标题 + 摘要 + 转录全文合并成单个 .md 文件，供 Bot 以文档形式回传。

    回传用文件比长文本分片更合适：保留排版、规避平台单条长度上限、便于用户存档。
    """
    if not summary.strip() and not transcript.strip():
        return None
    parts = [f"# {title}\n" if title else ""]
    if summary.strip():
        parts.append(f"## 摘要\n\n{summary.strip()}\n")
    if transcript.strip():
        parts.append(f"## 转录全文\n\n{transcript.strip()}\n")
    body = "\n".join(p for p in parts if p)

    safe_title = re.sub(r"[^\w一-鿿 -]", "", title or "transcript").strip() or "transcript"
    safe_title = safe_title[:60]
    path = TEMP_DIR / f"bot_{task_id}_{safe_title}.md"
    try:
        path.write_text(body, encoding="utf-8")
        return path
    except Exception:
        return None
