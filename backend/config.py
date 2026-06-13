"""集中配置层：保存应用内固定默认值。

模型/API Key/Base URL 等用户配置由前端 Settings 面板随请求传入；
后端不再从环境变量或 .env 中读取这些配置作为 fallback。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """运行时固定配置。冻结为不可变，避免被某处偷偷改写造成隐性耦合。"""

    # ── 本地上传 ──
    upload_max_mb: int = 200
    upload_allowed_ext: frozenset[str] = frozenset(
        {".txt", ".md", ".mp3", ".mp4", ".m4a", ".wav", ".webm", ".mkv", ".ogg", ".flac"}
    )

    # ── 转录（Whisper / ASR 后端）──
    whisper_model_size: str = "base"

    # ── LLM 调用保护 ──
    llm_timeout_sec: float = 300.0
    llm_request_timeout_sec: float = 120.0
    llm_max_retries: int = 1

    @property
    def upload_max_bytes(self) -> int:
        return self.upload_max_mb * 1024 * 1024


settings = Settings()
