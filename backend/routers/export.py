"""导出路由：将转录/摘要/翻译导出为多种文件格式。"""
import logging
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import StreamingResponse

from db import get_task as _db_get_task
from exporter import Exporter
from task_store import PROJECT_ROOT, TEMP_DIR

logger = logging.getLogger(__name__)
router = APIRouter()

exporter = Exporter(PROJECT_ROOT)

TIMESTAMP_PATTERN = re.compile(
    r"^\s*\**\[\d{2}:\d{2}(?::\d{2})?\s*-\s*\d{2}:\d{2}(?::\d{2})?\]\**\s*$"
)
TIMESTAMP_INLINE_PATTERN = re.compile(
    r"\**\[\d{2}:\d{2}(?::\d{2})?\s*-\s*\d{2}:\d{2}(?::\d{2})?\]\**"
)

FORMAT_MAP = {
    "markdown": ("md", "text/markdown"),
    "txt": ("txt", "text/plain; charset=utf-8"),
    "docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "pdf": ("pdf", "application/pdf"),
}


def _load_text_file(path: Path) -> str:
    try:
        if path and path.exists():
            return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error(f"读取文件失败 {path}: {exc}")
    return ""


def _remove_timestamps(text: str) -> str:
    lines = text.splitlines()
    filtered = []
    for line in lines:
        if TIMESTAMP_PATTERN.match(line.strip()):
            continue
        cleaned = TIMESTAMP_INLINE_PATTERN.sub("", line)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        filtered.append(cleaned.rstrip())
    return "\n".join(filtered)


def _remove_metadata(text: str) -> str:
    patterns = [
        r"#\s*Video Transcription\s*",
        r"\*\*Detected Language:\*\*.*",
        r"\*\*Language Probability:\*\*.*",
        r"##\s*Transcription Content\s*",
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    return text


@router.post("/api/export")
async def export_content(
    task_id: str = Form(...),
    content_type: str = Form(...),
    export_format: str = Form("markdown"),
    include_timestamps: bool = Form(False),
    include_header: bool = Form(False),
):
    task = await _db_get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.get("status") != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    content_type = content_type.lower()
    export_format = export_format.lower()

    if content_type not in ("transcript", "summary", "translation"):
        raise HTTPException(status_code=400, detail="不支持的内容类型")
    if export_format not in FORMAT_MAP:
        raise HTTPException(status_code=400, detail="不支持的导出格式")
    if include_timestamps and content_type != "transcript":
        raise HTTPException(status_code=400, detail="仅转录支持时间戳")

    # 获取内容
    content = None
    if content_type == "transcript":
        if include_timestamps:
            raw_file = task.get("raw_script_file")
            if raw_file:
                content = _load_text_file(TEMP_DIR / raw_file)
        if not content:
            path = task.get("script_path")
            content = _load_text_file(Path(path)) if path else task.get("script", "")
    elif content_type == "translation":
        path = task.get("translation_path")
        content = _load_text_file(Path(path)) if path else task.get("translation", "")
        if not content:
            raise HTTPException(status_code=400, detail="无可用翻译结果")
    else:
        path = task.get("summary_path")
        content = _load_text_file(Path(path)) if path else task.get("summary", "")
        if not content:
            raise HTTPException(status_code=400, detail="无可用摘要结果")

    if content_type == "transcript" and not content:
        raise HTTPException(status_code=400, detail="未找到可导出的转录内容")

    # 处理内容
    if content_type == "transcript":
        if not include_header:
            content = _remove_metadata(content)
        if not include_timestamps:
            content = _remove_timestamps(content)

    # 构造文件名
    title = task.get("video_title") or task.get("safe_title") or "export"
    safe = re.sub(r"[^\w\s.\-]", "_", title).strip(" ._-")[:80] or "untitled"
    ext, media_type = FORMAT_MAP[export_format]

    if content_type == "transcript":
        filename = f"{safe}.{ext}"
    else:
        filename = f"{safe}_{content_type}.{ext}"

    if export_format == "markdown":
        buffer = exporter.export_markdown(content)
    elif export_format == "txt":
        buffer = exporter.export_text(content)
    elif export_format == "docx":
        buffer = exporter.export_docx(content)
    else:
        buffer = exporter.export_pdf(content)

    encoded = quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    return StreamingResponse(buffer, media_type=media_type, headers=headers)
