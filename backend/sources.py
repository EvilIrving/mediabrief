"""来源提取层：把"从一个媒体 URL 取得原始转录文本"的分支逻辑收敛到一处。

此前 ``process_video_task``（普通 URL）和 ``run_rss_summarize_task``（RSS enclosure）
各自复制了同一套 "音频探测 → 查找字幕 → 字幕快速通道 / 下载音频走 Whisper" 的流程。
任何分支改动都得改两处，且容易不一致。

这里抽出 ``extract_media_source``：输入一个媒体 URL，输出统一的 ``ExtractResult``。
新增输入类型（如某播客 API、整张播放列表）时，只需复用本函数或新增一个并列的
提取器，而无需再复制 40 行编排代码。HTTP/任务编排细节仍留在 ``pipeline.py``。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ExtractResult:
    """媒体来源提取结果，供 ``run_post_extract_pipeline`` 直接消费。"""

    raw_script: str
    # 提取过程得到的标题（字幕标题或 Whisper 下载标题）；调用方可选择是否采用。
    extracted_title: Optional[str]
    # 已知的源语言（字幕路径有 sub_lang；Whisper 路径为 None，由下游从转录解析）。
    detected_language: Optional[str]
    # "subtitle" 或 "whisper"，用于前端展示与进度。
    mode: str


async def extract_media_source(
    task_id: str,
    url: str,
    *,
    video_processor,
    transcriber,
    temp_dir: Path,
    broadcast_stage,
    skip_stages,
    set_mode,
    enclosure_type: str = "",
    prefetched_title: Optional[str] = None,
    fetch_title_when_audio_only: bool = False,
    is_audio_only,
) -> ExtractResult:
    """统一的"字幕快速通道 / Whisper 慢速通道"提取流程。

    依赖（video_processor / transcriber / 各阶段回调）以参数注入，使本模块不直接
    耦合 services 与 task_store，便于单测与替换。各回调语义：
    - ``broadcast_stage(stage, pct)``  广播阶段进度（协程）
    - ``skip_stages([...])``           标记跳过的阶段
    - ``set_mode(mode, message)``      记录 subtitle/whisper 模式与提示文案
    """
    subtitle_text = None
    sub_title = prefetched_title
    sub_lang = None
    sub_duration = 0

    if is_audio_only(url, enclosure_type):
        # 纯音频：跳过字幕探测
        logger.info(f"检测到音频源，跳过字幕查找: {url}")
        skip_stages(["查找字幕", "读取字幕"])
        if fetch_title_when_audio_only:
            sub_title = await video_processor.get_video_title(url)
    else:
        await broadcast_stage("查找字幕", 50)
        subtitle_text, sub_title, sub_lang, sub_duration = await video_processor.fetch_subtitles(
            url, temp_dir
        )

    if subtitle_text:
        # ── 快速路径：有字幕 ─────────────────────────────────
        set_mode("subtitle", f"字幕获取成功（{sub_lang}）")
        skip_stages(["下载音频", "准备音频", "转录"])
        if not is_audio_only(url, enclosure_type):
            await broadcast_stage("查找字幕", 100)
        await broadcast_stage("读取字幕", 100)
        return ExtractResult(
            raw_script=subtitle_text,
            extracted_title=sub_title,
            detected_language=sub_lang,
            mode="subtitle",
        )

    # ── 慢速路径：下载音频 → Whisper ────────────────────────
    set_mode("whisper", None)
    skip_stages(["读取字幕"])
    if not is_audio_only(url, enclosure_type):
        await broadcast_stage("查找字幕", 100)

    await broadcast_stage("下载音频", 30)
    audio_path, video_title = await video_processor.download_and_convert(
        url,
        temp_dir,
        prefetched_title=sub_title or None,
        prefetched_duration=sub_duration or 0,
    )
    await broadcast_stage("下载音频", 100)
    await broadcast_stage("准备音频", 100)

    await broadcast_stage("转录", 50)
    raw_script = await transcriber.transcribe(audio_path)
    await broadcast_stage("转录", 100)

    # 转录已完成，下载的中间音频不再需要，立即删除以免 TEMP_DIR 无限膨胀。
    try:
        Path(audio_path).unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"清理中间音频失败（不影响结果）: {e}")

    return ExtractResult(
        raw_script=raw_script,
        extracted_title=video_title,
        detected_language=None,
        mode="whisper",
    )
