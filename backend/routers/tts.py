"""TTS 路由：摘要语音合成。"""
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_task as _db_get_task
from settings_store import get_app_settings
from tts import synthesize_speech, TtsAuthError, TtsUpstreamError, TtsTimeoutError

logger = logging.getLogger(__name__)
router = APIRouter()


class TtsBody(BaseModel):
    task_id: str
    api_key: str
    speaker: str
    resource_id: str = "seed-tts-2.0"


@router.post("/api/tts/summary")
async def tts_summary(body: TtsBody):
    """摘要语音合成：取任务摘要文本，调豆包 TTS，返回 MP3 音频。"""
    # 1. 任务校验（不绑 completed，摘要可能先于转录完成）
    task = await _db_get_task(body.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 取摘要文本：内存 > 文件
    summary_text = task.get("summary") or ""
    if not summary_text and task.get("summary_path"):
        try:
            summary_text = Path(task["summary_path"]).read_text("utf-8")
        except Exception:
            pass
    if not summary_text:
        raise HTTPException(status_code=400, detail="无可用摘要内容")

    saved = await get_app_settings()
    api_key = body.api_key.strip() or saved.ttsConfig.apiKey
    speaker = body.speaker.strip() or saved.ttsConfig.speaker
    resource_id = body.resource_id.strip() or saved.ttsConfig.resourceId
    if not api_key or not speaker:
        raise HTTPException(status_code=400, detail="TTS 配置不完整")

    # 2. 合成（领域异常 → HTTP 状态码）
    try:
        audio = await synthesize_speech(
            summary_text,
            api_key=api_key,
            speaker=speaker,
            resource_id=resource_id,
        )
    except TtsAuthError as e:
        raise HTTPException(status_code=401, detail=e.message)
    except TtsTimeoutError as e:
        raise HTTPException(status_code=504, detail=e.message)
    except TtsUpstreamError as e:
        raise HTTPException(status_code=502, detail=e.message)

    return Response(content=audio, media_type="audio/mpeg")
