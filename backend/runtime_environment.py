"""统一运行时画像：启动诊断和恢复 Agent 读同一份事实。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import whisper_models
import yt_dlp_updater


def _binary(name: str, env_key: str) -> Optional[str]:
    configured = (os.environ.get(env_key) or "").strip()
    if configured and Path(configured).exists():
        return configured
    return shutil.which(name)


def _tool_version(binary: Optional[str], *args: str) -> Optional[str]:
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, *args], capture_output=True, text=True, timeout=5, check=False,
        )
        first_line = (result.stdout or result.stderr).splitlines()
        return first_line[0].strip() if first_line else None
    except (OSError, subprocess.SubprocessError):
        return None


def _tool_snapshot(name: str, env_key: str, *version_args: str) -> dict[str, Any]:
    path = _binary(name, env_key)
    return {
        "name": name,
        "available": bool(path),
        "path": path,
        "version": _tool_version(path, *version_args) if path else None,
    }


def _mlx_snapshot() -> dict[str, Any]:
    try:
        import mlx
        import mlx_whisper

        return {
            "available": True,
            "version": (
                f"mlx-whisper {getattr(mlx_whisper, '__version__', '?')} "
                f"/ mlx {getattr(mlx, '__version__', '?')}"
            ),
        }
    except Exception as exc:
        return {"available": False, "version": None, "error": type(exc).__name__}


def collect_runtime_environment() -> dict[str, Any]:
    """FFmpeg / Deno / MLX / yt-dlp / Whisper 默认模型的同一份快照。"""
    return {
        "platform": sys.platform,
        "frozen": bool(getattr(sys, "frozen", False)),
        "ffmpeg": _tool_snapshot("ffmpeg", "AIT_FFMPEG", "-version"),
        "ffprobe": _tool_snapshot("ffprobe", "AIT_FFPROBE", "-version"),
        "deno": _tool_snapshot("deno", "AIT_DENO", "--version"),
        "mlx": _mlx_snapshot(),
        "yt_dlp": yt_dlp_updater.update_status(),
        "whisper": whisper_models.default_model_status(),
    }


def runtime_observation_summary(snapshot: Optional[dict[str, Any]] = None) -> str:
    """给 Agent 的短观察，不带路径和密钥。"""
    state = snapshot or collect_runtime_environment()
    whisper = state.get("whisper") or {}
    ytdlp = state.get("yt_dlp") or {}
    mlx = state.get("mlx") or {}
    parts = [
        f"ffmpeg={bool((state.get('ffmpeg') or {}).get('available'))}",
        f"ffprobe={bool((state.get('ffprobe') or {}).get('available'))}",
        f"deno={bool((state.get('deno') or {}).get('available'))}",
        f"mlx={bool(mlx.get('available'))}",
        f"yt_dlp={ytdlp.get('current_version') or 'unknown'}",
        f"yt_dlp_update={ytdlp.get('status') or 'unknown'}",
        f"whisper={whisper.get('status') or 'unknown'}",
        f"whisper_ready={bool(whisper.get('ready'))}",
        f"whisper_endpoint={whisper.get('endpoint') or 'unknown'}",
        f"whisper_tried={','.join(whisper.get('tried_endpoints') or ()) or 'none'}",
    ]
    error = whisper.get("error")
    if error:
        parts.append(f"whisper_error={str(error)[:180]}")
    return "; ".join(parts)
