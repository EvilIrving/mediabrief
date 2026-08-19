"""依赖/服务层：共享处理器单例与上传配置。

路由与编排层都从这里取得处理器实例，避免在 main.py 里集中初始化、
被各处直接引用而造成耦合。
"""
from config import settings
from providers import ASRBackend, SummarizerBackend
from whisper_models import get_transcriber
from video_processor import VideoProcessor
from summarizer import Summarizer
from translator import Translator
from rss_reader import RSSReader
from release_config import get_release_llm_config
from media_recovery_service import MediaRecoveryService, build_recovery_model
from task_store import TEMP_DIR

# ── 处理器单例 ────────────────────────────────────────────────
# transcriber/summarizer 以 Protocol 类型暴露，调用方依赖接口而非具体实现，
# 便于将来按配置替换为远程 ASR / 其他模型供应商。
video_processor = VideoProcessor()
# 默认转写器是 large-v3-turbo 的惰性门闩；首启下载完成前只阻塞真正的转录阶段。
transcriber: ASRBackend = get_transcriber(settings.whisper_model_size)
_release_llm = get_release_llm_config()
summarizer: SummarizerBackend = Summarizer(
    api_key=_release_llm.api_key,
    base_url=_release_llm.base_url,
    model=_release_llm.model,
    thinking=True,
)
translator = Translator()
rss_reader = RSSReader(data_dir=TEMP_DIR)
media_recovery = MediaRecoveryService(
    model=build_recovery_model(
        api_key=_release_llm.recovery_api_key,
        base_url=_release_llm.recovery_base_url,
        model=_release_llm.recovery_model,
    ),
    video_processor=video_processor,
)

# ── 本地上传：允许的类型与大小上限，集中在 config.settings 调整 ──
UPLOAD_ALLOWED_EXT = settings.upload_allowed_ext
UPLOAD_MAX_MB = settings.upload_max_mb
