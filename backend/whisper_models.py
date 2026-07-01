"""Whisper 模型管理：目录解析、下载、按尺寸缓存 Transcriber 实例。

ASR 引擎为 mlx-whisper（Apple MLX），模型权重取自 mlx-community 仓库。
每个尺寸下载到 *可写* 数据目录下的独立子目录 ``MODEL_DIR/<size>/``
（而非默认 ``~/.cache/huggingface`` 的 HF cache 布局），便于桌面端管理、
内嵌与清理，也让 ``is_downloaded`` 不必推算 HF 缓存目录结构。

下载源遵循中立原则：默认走官方 Hugging Face；用户若在前端设置中填写
``hf_endpoint``（镜像 / 公司代理等），仅在该次下载期间临时生效，不写死。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

from huggingface_hub import snapshot_download

from task_store import TEMP_DIR
from transcriber import Transcriber

logger = logging.getLogger(__name__)

# ── 可选模型目录（mlx-community HF 仓库名）。large 固定指向 large-v3。 ──
CATALOG: dict[str, str] = {
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    # large-v3-turbo：解码比 large-v3 快约 8×，fp16 权重约 1.6GB，中/英/日/韩四语
    # 全覆盖。在 Apple Silicon 上吃 Metal GPU，是质量/速度的甜点（2026 实测 22.9× 实时）。
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}

# mlx-community 各仓库的权重文件名：turbo 为 safetensors，其余为 npz。
# is_downloaded 按「config.json + 任一权重存在」判定（Codex 修正）。
_WEIGHT_FILES = ("weights.safetensors", "weights.npz")

# 近似下载体积（MB），仅用于前端展示，无需精确。
APPROX_SIZE_MB: dict[str, int] = {
    "base": 145,
    "small": 250,
    "medium": 1500,
    "large-v3-turbo": 1600,
    "large-v3": 3000,
}

# 默认转录模型：质量/速度的最优解，首次使用时按需下载。
DEFAULT_MODEL = "large-v3-turbo"

# 内嵌随包播种的模型：体积小、保证离线可用，作为默认模型尚未就绪时的回退。
# （打包时只内嵌它，避免安装包过大；large-v3-turbo 首启后台下载。）
BUILTIN_MODEL = "base"

# 所有模型统一下载到此目录，每个尺寸落到独立子目录 MODEL_DIR/<size>/。
MODEL_DIR = Path(os.environ.get("WHISPER_MODEL_DIR") or (TEMP_DIR / "whisper-models"))
MODEL_DIR.mkdir(parents=True, exist_ok=True)

_registry: dict[str, Transcriber] = {}
_registry_lock = threading.Lock()
_download_lock = threading.Lock()


def model_dir(size: str) -> Path:
    """该尺寸模型的本地目录（含 config.json + weights.*）。"""
    return MODEL_DIR / size


def is_downloaded(size: str) -> bool:
    """该尺寸模型是否已存在于本地（无需联网）。"""
    if size not in CATALOG:
        return False
    d = model_dir(size)
    if not (d / "config.json").is_file():
        return False
    # turbo=weights.safetensors / 其余=weights.npz，任一存在即视为完整。
    return any((d / w).is_file() for w in _WEIGHT_FILES)


def list_models() -> list[dict]:
    """供前端展示：每个尺寸的下载状态与近似体积。"""
    return [
        {
            "size": size,
            # BUILTIN_MODEL 内嵌打包，无需下载，始终视为可用。
            "downloaded": size == BUILTIN_MODEL or is_downloaded(size),
            "builtin": size == BUILTIN_MODEL,
            "approx_mb": APPROX_SIZE_MB.get(size, 0),
            "default": size == DEFAULT_MODEL,
        }
        for size in CATALOG
    ]


def download(size: str, hf_endpoint: Optional[str] = None) -> None:
    """下载指定尺寸模型到 MODEL_DIR/<size>/。阻塞调用，请在线程中执行。

    hf_endpoint 非空时仅在本次下载临时设置 HF_ENDPOINT，结束后恢复。
    """
    if size not in CATALOG:
        raise ValueError(f"unknown whisper model size: {size}")
    if is_downloaded(size):
        return
    with _download_lock:
        if is_downloaded(size):
            return
        prev_endpoint = os.environ.get("HF_ENDPOINT")
        prev_http_proxy = os.environ.get("HTTP_PROXY")
        prev_https_proxy = os.environ.get("HTTPS_PROXY")
        endpoint = (hf_endpoint or "").strip()
        try:
            if endpoint:
                os.environ["HF_ENDPOINT"] = endpoint
            # httpx（huggingface_hub 内部使用）在 TUN 模式下不走系统网卡，
            # 需显式设置 HTTP 代理才能被 Clash 接管。
            if not prev_http_proxy and not prev_https_proxy:
                for port in (7890, 7897, 1080):
                    import socket
                    try:
                        s = socket.create_connection(("127.0.0.1", port), timeout=0.3)
                        s.close()
                        os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{port}"
                        os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{port}"
                        break
                    except OSError:
                        pass
            logger.info("⬇️  下载 Whisper 模型 %s (endpoint=%s)", size, endpoint or "default")
            snapshot_download(
                repo_id=CATALOG[size],
                local_dir=str(model_dir(size)),
                # 只取推理所需文件，跳过 README/.gitattributes 等。
                allow_patterns=["config.json", "weights.safetensors", "weights.npz", "*.json"],
            )
            logger.info("✅ Whisper 模型 %s 下载完成", size)
        finally:
            if endpoint:
                if prev_endpoint is None:
                    os.environ.pop("HF_ENDPOINT", None)
                else:
                    os.environ["HF_ENDPOINT"] = prev_endpoint
            if not prev_http_proxy:
                os.environ.pop("HTTP_PROXY", None)
            if not prev_https_proxy:
                os.environ.pop("HTTPS_PROXY", None)


def ensure_default_model_async(hf_endpoint: Optional[str] = None) -> None:
    """后台（非阻塞）确保默认模型 large-v3-turbo 已就绪。

    打包只内嵌 BUILTIN_MODEL(base)；默认模型在首启时后台下载，
    下载期间的任务会优雅回退到 base（见 get_transcriber），下载完成后
    后续任务自动用上默认模型。网络不可达时静默放弃，不影响 base 转录。
    """
    if is_downloaded(DEFAULT_MODEL):
        return

    def _worker():
        try:
            download(DEFAULT_MODEL, hf_endpoint)
        except Exception as e:  # 网络问题等：不影响 base 回退，仅记录
            logger.warning("默认模型 %s 后台下载失败（将继续用 %s 回退）: %s",
                           DEFAULT_MODEL, BUILTIN_MODEL, e)

    threading.Thread(target=_worker, name="ensure-default-model", daemon=True).start()


def _resolve_available_size(size: Optional[str]) -> str:
    """把请求的尺寸解析为「当前本地可用」的尺寸。

    - 未知尺寸 → 默认模型；
    - 默认/请求模型尚未下载（如首启 turbo 仍在后台下载）→ 回退到内嵌的 base，
      保证任务不被「模型缺失」卡死。用户显式下载过的模型仍按其选择使用。
    """
    size = size if size in CATALOG else DEFAULT_MODEL
    if size == BUILTIN_MODEL or is_downloaded(size):
        return size
    logger.info("模型 %s 尚未就绪，本次回退到内嵌模型 %s", size, BUILTIN_MODEL)
    return BUILTIN_MODEL


def get_transcriber(size: Optional[str] = None) -> Transcriber:
    """按尺寸取得（必要时创建并缓存）Transcriber。

    模型文件缺失时不在此处联网下载（避免阻塞）——回退到内嵌的 base；
    默认模型的获取由 ensure_default_model_async 在后台完成，其余尺寸经前端
    「下载」流程显式获取。
    """
    size = _resolve_available_size(size)
    cached = _registry.get(size)
    if cached is not None:
        return cached
    with _registry_lock:
        cached = _registry.get(size)
        if cached is not None:
            return cached
        # 已下载用本地目录；未下载（如 dev 未播种 base）传 HF 仓库名，
        # 让 mlx 在首次转录时自动拉取，保证开箱即用。
        path = str(model_dir(size)) if is_downloaded(size) else CATALOG[size]
        t = Transcriber(model_size=size, model_path=path)
        _registry[size] = t
        return t
