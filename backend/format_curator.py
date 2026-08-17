"""Tool ``present_download_list``：Detect 返回 → 页面可解析的下载列表。

宿主 Detect 之后调 ``execute``；Harness 接入时也调同一函数。这里不发起模型请求。
"""
from __future__ import annotations

from typing import Any

_AUTO_VIDEO = "bestvideo+bestaudio/best"
_AUTO_AUDIO = "bestaudio/best"

_CODEC_RULES = (
    (("avc", "h264"), "h264"),
    (("hvc", "hev", "hevc", "h265"), "hevc"),
    (("av01", "av1"), "av1"),
    (("vp09", "vp9"), "vp9"),
    (("vp08", "vp8"), "vp8"),
    (("mp4a", "aac"), "aac"),
    (("opus",), "opus"),
    (("mp3",), "mp3"),
    (("flac",), "flac"),
)


def codec_family(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if not s or s == "none":
        return ""
    for needles, name in _CODEC_RULES:
        if any(n in s for n in needles):
            return name
    token = s.split(".")[0]
    return token if token and len(token) <= 12 else ""


def resolution_label(height: int | None) -> str:
    h = int(height or 0)
    if h >= 2160:
        return "4K"
    if h >= 1440:
        return "1440p"
    if h >= 1080:
        return "1080p"
    if h >= 720:
        return "720p"
    if h >= 480:
        return "480p"
    if h >= 360:
        return "360p"
    if h >= 240:
        return "240p"
    return f"{h}p" if h > 0 else ""


def fps_label(fps: float | None) -> str:
    if not fps or fps <= 0:
        return ""
    for std in (24, 25, 30, 48, 50, 60, 120):
        if abs(fps - std) < 0.5:
            return f"{std}fps"
    return f"{round(fps)}fps"


def bitrate_label(abr: float | None) -> str:
    if not abr or abr <= 0:
        return ""
    return f"{round(abr)}kbps"


def is_auto_format(entry: dict, kind: str) -> bool:
    fid = entry.get("id") or ""
    if fid in ("best", _AUTO_VIDEO, _AUTO_AUDIO):
        return True
    return kind == "audio" and fid == "bestaudio"


def format_label(entry: dict, kind: str) -> str:
    if is_auto_format(entry, kind):
        return ""
    if kind == "video":
        parts = [
            resolution_label(entry.get("height")),
            (entry.get("ext") or "").strip(),
            fps_label(entry.get("fps")),
            codec_family(entry.get("vcodec")),
        ]
    else:
        parts = [
            (entry.get("ext") or "").strip(),
            bitrate_label(entry.get("abr")),
            codec_family(entry.get("acodec")),
        ]
    return " ".join(p for p in parts if p)


def display_key(entry: dict, kind: str) -> tuple:
    if is_auto_format(entry, kind):
        return ("auto",)
    if kind == "video":
        return (
            int(entry.get("height") or 0),
            codec_family(entry.get("vcodec")),
            (entry.get("ext") or ""),
            round(float(entry.get("fps") or 0)),
        )
    return (
        round(float(entry.get("abr") or 0)),
        codec_family(entry.get("acodec")),
        (entry.get("ext") or ""),
    )


def collapse_formats(entries: list[dict], kind: str) -> list[dict]:
    """同一人眼标签只留一条，并写上本地标签。"""
    kept: list[dict] = []
    seen: dict[tuple, int] = {}
    for raw in entries:
        entry = dict(raw)
        key = display_key(entry, kind)
        if key in seen:
            prev = kept[seen[key]]
            if (entry.get("filesize") or 0) > (prev.get("filesize") or 0):
                entry["label"] = format_label(entry, kind)
                kept[seen[key]] = entry
            continue
        entry["label"] = format_label(entry, kind)
        seen[key] = len(kept)
        kept.append(entry)
    return kept


_KEEP_HEIGHTS = (2160, 1440, 1080, 720, 360)


def _keep_height_rung(height: int, available: set[int]) -> bool:
    if height in _KEEP_HEIGHTS:
        return True
    # 源最高档不在常用梯上时也留（例如只有 480p）
    return height == max(available) if available else False


def one_per_height(entries: list[dict]) -> list[dict]:
    """每个清晰度只留一条，避免 1080p 同时摆 h264/vp9/av1。"""
    autos: list[dict] = []
    chosen: dict[int, dict] = {}
    order: list[int] = []
    for raw in entries:
        entry = dict(raw)
        if is_auto_format(entry, "video"):
            autos.append(entry)
            continue
        height = int(entry.get("height") or 0)
        if height not in chosen:
            order.append(height)
            chosen[height] = entry
        else:
            chosen[height] = _preferred_video(chosen[height], entry)
    available = set(chosen)
    out = []
    for height in order:
        if not _keep_height_rung(height, available):
            continue
        item = chosen[height]
        if not (item.get("label") or "").strip():
            item["label"] = format_label(item, "video")
        out.append(item)
    return autos + out


def _preferred_video(left: dict, right: dict) -> dict:
    left_size = int(left.get("filesize") or 0)
    right_size = int(right.get("filesize") or 0)
    if left_size and right_size and left_size != right_size:
        return left if left_size < right_size else right
    rank = {"hevc": 3, "av1": 2, "h264": 1, "vp9": 0}
    left_rank = rank.get(codec_family(left.get("vcodec")), 0)
    right_rank = rank.get(codec_family(right.get("vcodec")), 0)
    return left if left_rank >= right_rank else right


TOOL_ID = "present_download_list"


def tool_spec() -> dict[str, Any]:
    from llm_tools import host_function_tool

    return host_function_tool(
        TOOL_ID,
        "Turn a Detect catalog into the download page list. "
        "Input is the raw video_formats and audio_formats from Detect. "
        "Output is a parseable payload the UI can render. Does not call a model.",
        capability="read",
        timeout_sec=5,
        properties={
            "video_formats": {
                "type": "array",
                "description": "Detect video_formats array",
                "items": {"type": "object"},
            },
            "audio_formats": {
                "type": "array",
                "description": "Detect audio_formats array",
                "items": {"type": "object"},
            },
        },
        required=["video_formats", "audio_formats"],
    )


def present_download_list(
    video_formats: list[dict] | None = None,
    audio_formats: list[dict] | None = None,
) -> dict[str, list[dict]]:
    """Detect 返回 → 页面可解析 payload。宿主和 Harness 走同一函数。"""
    return {
        "video": one_per_height(collapse_formats(list(video_formats or []), "video")),
        "audio": collapse_formats(list(audio_formats or []), "audio"),
    }


def execute(arguments: dict[str, Any] | None = None) -> dict[str, list[dict]]:
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("invalid_arguments")
    return present_download_list(
        arguments.get("video_formats") or [],
        arguments.get("audio_formats") or [],
    )
