"""Provider 接口层：用 Protocol 定义 ASR / LLM 后端的契约。

目的：把"管线对后端的依赖"从"具体实现"（mlx-whisper、OpenAI SDK）解耦为
"结构化接口"。任何满足该 Protocol 的对象都能被注入管线，无需改动编排代码——
这就是把后端做得 flexible / 可替换的关键。

现有的 ``Transcriber`` 和 ``Summarizer`` 已在结构上满足这些 Protocol（鸭子类型），
因此无需改动它们即可获得类型层面的可替换性。未来要接入"远程 Whisper API"
或"另一家模型供应商"时，只要实现对应 Protocol 并在 ``build_asr_backend`` /
服务装配处替换即可。
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional, Protocol, runtime_checkable

from media_contracts import AudioProfile, TranscriptionOutcome, TranscriptionStrategy


@runtime_checkable
class ASRBackend(Protocol):
    """语音转文字后端契约。mlx-whisper、远程转写 API 等都可实现它。"""

    async def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
        strategy: Optional[TranscriptionStrategy] = None,
    ) -> str:
        """把音频转成 Markdown 格式的原始转录文本。"""
        ...

    async def transcribe_with_quality(
        self,
        audio_path: str,
        *,
        audio_profile: AudioProfile,
        strategy: TranscriptionStrategy,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> TranscriptionOutcome: ...

    def get_detected_language(self, transcript_text: Optional[str] = None) -> Optional[str]:
        """从转录文本解析检测到的语言代码（无共享状态）。"""
        ...


@runtime_checkable
class SummarizerBackend(Protocol):
    """文本优化 + 摘要后端契约。任何 OpenAI 兼容/自研实现都可满足。"""

    def optimize_transcript(
        self, raw_transcript: str, video_title: Optional[str] = None
    ) -> str: ...

    def summarize(
        self, transcript: str, target_language: str = "zh", video_title: Optional[str] = None
    ) -> str: ...

    def summary_two_step(
        self, transcript: str, target_language: str = "zh", video_title: Optional[str] = None
    ) -> dict: ...

    def is_available(self) -> bool: ...


def build_asr_backend(name: str = "mlx-whisper", **kwargs) -> ASRBackend:
    """ASR 后端工厂：按名称构建转写后端，便于通过配置切换实现。

    目前只内置 mlx-whisper（Apple Silicon 本地转写）；新增远程后端时在此分派即可，
    调用方无需改动。
    """
    if name in ("mlx-whisper", "mlx", "whisper", "local"):
        from transcriber import Transcriber

        return Transcriber(**kwargs)
    raise ValueError(f"未知的 ASR 后端: {name!r}")
