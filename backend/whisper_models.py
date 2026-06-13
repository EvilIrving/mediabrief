"""Whisper 模型管理：目录解析、下载、按尺寸缓存 Transcriber 实例。

模型文件统一下载到 *可写* 的数据目录（打包后为 Application Support），
而非默认的 ``~/.cache/huggingface``，便于桌面端管理、内嵌与清理。

下载源遵循中立原则：默认走官方 Hugging Face；用户若在前端设置中填写
``hf_endpoint``（镜像 / 公司代理等），仅在该次下载期间临时生效，不写死。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

from faster_whisper.utils import download_model

from task_store import TEMP_DIR
from transcriber import Transcriber

logger = logging.getLogger(__name__)

# ── 可选模型目录（HF 仓库名）。large 固定指向 large-v3。 ──
CATALOG: dict[str, str] = {
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    # large-v3-turbo：2024.10 发布，解码比 large-v3 快约 8×、int8 仅约 1.5GB 内存，
    # 中/英/日/韩四语全覆盖，是 CPU 部署的精度/速度甜点（2026 仍然成立）。
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
}

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

# 所有模型统一下载到此目录（HF cache 布局：models--Systran--faster-whisper-*）。
MODEL_DIR = Path(os.environ.get("WHISPER_MODEL_DIR") or (TEMP_DIR / "whisper-models"))
MODEL_DIR.mkdir(parents=True, exist_ok=True)

_registry: dict[str, Transcriber] = {}
_registry_lock = threading.Lock()
_download_lock = threading.Lock()


def _hf_cache_dirname(size: str) -> str:
    """HF cache 目录名，对应 download_model(cache_dir=MODEL_DIR) 的落盘布局。"""
    return "models--" + CATALOG[size].replace("/", "--")


def is_downloaded(size: str) -> bool:
    """该尺寸模型是否已存在于本地（无需联网）。"""
    if size not in CATALOG:
        return False
    snap = MODEL_DIR / _hf_cache_dirname(size) / "snapshots"
    if not snap.is_dir():
        return False
    # snapshots/<rev>/model.bin 存在即视为完整
    return any((d / "model.bin").exists() for d in snap.iterdir() if d.is_dir())


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
    """下载指定尺寸模型到 MODEL_DIR。阻塞调用，请在线程中执行。

    hf_endpoint 非空时仅在本次下载临时设置 HF_ENDPOINT，结束后恢复。
    """
    if size not in CATALOG:
        raise ValueError(f"unknown whisper model size: {size}")
    if is_downloaded(size):
        return
    with _download_lock:
        if is_downloaded(size):
            return
        prev = os.environ.get("HF_ENDPOINT")
        endpoint = (hf_endpoint or "").strip()
        try:
            if endpoint:
                os.environ["HF_ENDPOINT"] = endpoint
            logger.info("⬇️  下载 Whisper 模型 %s (endpoint=%s)", size, endpoint or "default")
            download_model(CATALOG[size], cache_dir=str(MODEL_DIR))
            logger.info("✅ Whisper 模型 %s 下载完成", size)
        finally:
            if endpoint:
                if prev is None:
                    os.environ.pop("HF_ENDPOINT", None)
                else:
                    os.environ["HF_ENDPOINT"] = prev


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
        t = Transcriber(model_size=size, download_root=str(MODEL_DIR))
        _registry[size] = t
        return t
