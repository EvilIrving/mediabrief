"""Whisper 模型管理：目录解析、下载、按尺寸缓存 Transcriber 实例。

ASR 引擎为 mlx-whisper（Apple MLX），模型权重取自 mlx-community 仓库。
每个尺寸下载到 *可写* 数据目录下的独立子目录 ``MODEL_DIR/<size>/``
（而非默认 ``~/.cache/huggingface`` 的 HF cache 布局），便于桌面端管理、
内嵌与清理，也让 ``is_downloaded`` 不必推算 HF 缓存目录结构。

下载源由宿主管理：默认先官方 Hugging Face，失败后立刻换 ModelScope
（国内可达的权重 CDN）。不使用 hf-mirror：它的 Hub API 在国内能通，但权重会
302 到 ``us.aws.cdn.hf.co``，普通网络经常读超时。
开发设置里的 ``hf_endpoint`` 仍可强制只用一个源，不写死进仓库。
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
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

# 官方源失败后由宿主自动换 ModelScope，用户不用填 Endpoint。
OFFICIAL_DOWNLOAD_ENDPOINT = ""
MODELSCOPE_DOWNLOAD_ENDPOINT = "https://www.modelscope.cn"
DEFAULT_DOWNLOAD_ENDPOINTS: tuple[str, ...] = (
    OFFICIAL_DOWNLOAD_ENDPOINT,
    MODELSCOPE_DOWNLOAD_ENDPOINT,
)
_MODELSCOPE_RESOLVE = "https://www.modelscope.cn/models/{repo}/resolve/{revision}/{name}"
_MODELSCOPE_FILES = (
    "https://www.modelscope.cn/api/v1/models/{repo}/repo/files"
    "?Revision={revision}&Recursive=1"
)
_HTTP_CONNECT_TIMEOUT = 10.0
_HTTP_READ_TIMEOUT = 30.0
_CHUNK = 256 * 1024

# 大模型准备失败时优先用 base；它默认不随包，只能回退到真实存在的本地权重。
FALLBACK_MODELS = ("base", "small", "medium", "large-v3")

# 所有模型统一下载到此目录，每个尺寸落到独立子目录 MODEL_DIR/<size>/。
MODEL_DIR = Path(os.environ.get("WHISPER_MODEL_DIR") or (TEMP_DIR / "whisper-models"))
MODEL_DIR.mkdir(parents=True, exist_ok=True)

_registry: dict[str, Transcriber] = {}
_registry_lock = threading.Lock()
_download_lock = threading.Lock()
_default_worker_lock = threading.Lock()
_default_ready = threading.Event()
_default_degraded = threading.Event()
_default_retry_now = threading.Event()
_default_worker: Optional[threading.Thread] = None
_default_state_lock = threading.Lock()
_default_state: dict[str, object] = {
    "status": "pending",
    "error": None,
    "attempt": 0,
    "next_retry_at": None,
    "endpoint": None,
    "tried_endpoints": (),
}


def normalize_download_endpoint(endpoint: Optional[str]) -> str:
    return (endpoint or "").strip().rstrip("/")


def download_endpoint_label(endpoint: str) -> str:
    if not endpoint:
        return "official"
    if is_modelscope_source(endpoint):
        return "modelscope"
    return endpoint


def is_modelscope_source(endpoint: Optional[str]) -> bool:
    text = normalize_download_endpoint(endpoint).lower()
    if not text or text == "official":
        return False
    if text == "modelscope":
        return True
    host = urlparse(text if "://" in text else f"https://{text}").hostname or ""
    return host == "modelscope.cn" or host.endswith(".modelscope.cn")


def download_endpoints_for(explicit: Optional[str] = None) -> tuple[str, ...]:
    """显式源只用这一个；默认路径官方失败后立刻换 ModelScope。"""
    specified = normalize_download_endpoint(explicit)
    if specified:
        return (specified,)
    return DEFAULT_DOWNLOAD_ENDPOINTS


def next_download_endpoint(attempt: int, endpoints: tuple[str, ...]) -> str:
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    if not endpoints:
        raise ValueError("download endpoints required")
    return endpoints[(attempt - 1) % len(endpoints)]


def completed_endpoint_cycle(attempt: int, endpoints: tuple[str, ...]) -> bool:
    return attempt > 0 and bool(endpoints) and attempt % len(endpoints) == 0


def model_dir(size: str) -> Path:
    """该尺寸模型的本地目录（含 config.json + weights.*）。"""
    return MODEL_DIR / size


def bundled_model_dir(size: str) -> Optional[Path]:
    """返回包内模型目录；开发模式和精简包均为 None。"""
    if size not in CATALOG or not getattr(sys, "frozen", False):
        return None
    root = Path(getattr(sys, "_MEIPASS", "")) / "whisper-models" / size
    if not (root / "config.json").is_file():
        return None
    return root if any((root / name).is_file() for name in _WEIGHT_FILES) else None


def is_downloaded(size: str) -> bool:
    """该尺寸模型是否已存在于本地（无需联网）。"""
    if size not in CATALOG:
        return False
    d = model_dir(size)
    if not (d / "config.json").is_file():
        return False
    # turbo=weights.safetensors / 其余=weights.npz，任一存在即视为完整。
    return any((d / w).is_file() for w in _WEIGHT_FILES)


def is_available(size: str) -> bool:
    """模型是否可以无网络直接加载。"""
    return is_downloaded(size) or bundled_model_dir(size) is not None


def _set_default_state(status: str, **fields) -> None:
    with _default_state_lock:
        _default_state.update(status=status, **fields)


def _downloaded_bytes(size: str) -> int:
    directory = model_dir(size)
    if not directory.exists():
        return 0
    total = 0
    try:
        for path in directory.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
    except OSError:
        pass
    return total


def default_model_status() -> dict:
    """返回首启默认模型的真实准备状态，供 UI 和诊断统一使用。"""
    ready = is_downloaded(DEFAULT_MODEL)
    if ready:
        _default_ready.set()
        _default_degraded.clear()
        _set_default_state("ready", error=None, next_retry_at=None)
    with _default_state_lock:
        state = dict(_default_state)
    total_bytes = APPROX_SIZE_MB[DEFAULT_MODEL] * 1024 * 1024
    downloaded_bytes = _downloaded_bytes(DEFAULT_MODEL)
    progress = 100 if ready else min(99, int(downloaded_bytes * 100 / total_bytes))
    return {
        "model": DEFAULT_MODEL,
        "ready": ready,
        "degraded": _default_degraded.is_set() and not ready,
        "status": state["status"],
        "progress": progress,
        "downloaded_bytes": downloaded_bytes,
        "total_bytes": total_bytes,
        "error": state.get("error"),
        "attempt": state.get("attempt", 0),
        "next_retry_at": state.get("next_retry_at"),
        "endpoint": state.get("endpoint"),
        "tried_endpoints": list(state.get("tried_endpoints") or ()),
    }


def list_models() -> list[dict]:
    """供前端展示：每个尺寸的下载状态与近似体积。"""
    return [
        {
            "size": size,
            "downloaded": is_available(size),
            "builtin": bundled_model_dir(size) is not None,
            "approx_mb": APPROX_SIZE_MB.get(size, 0),
            "default": size == DEFAULT_MODEL,
        }
        for size in CATALOG
    ]


def _hub_reachable(timeout: float = 3.0) -> bool:
    """国内普通网络连不上 huggingface.co；先探端口，避免 snapshot_download 长时间挂死。"""
    import socket

    try:
        sock = socket.create_connection(("huggingface.co", 443), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def _modelscope_needed_files(repo_id: str, client: httpx.Client) -> tuple[str, list[str]]:
    """从仓库文件列表挑出推理所需文件；revision 以 master / main 依次试。"""
    for revision in ("master", "main"):
        url = _MODELSCOPE_FILES.format(repo=repo_id, revision=revision)
        try:
            resp = client.get(url)
            resp.raise_for_status()
            files = ((resp.json().get("Data") or {}).get("Files")) or []
        except Exception:
            continue
        names = {item.get("Name") for item in files if item.get("Type") == "blob"}
        if "config.json" not in names:
            continue
        weights = [name for name in _WEIGHT_FILES if name in names]
        if not weights:
            continue
        return revision, ["config.json", weights[0]]
    return "master", ["config.json", "weights.safetensors"]


def _http_download_file(client: httpx.Client, url: str, dest: Path) -> None:
    """直链下载，支持 .part 断点续传。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    existing = part.stat().st_size if part.is_file() else 0
    headers = {}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    with client.stream("GET", url, headers=headers) as resp:
        resp.raise_for_status()
        if existing and resp.status_code == 200:
            # 服务端忽略 Range，整段重来。
            existing = 0
            part.unlink(missing_ok=True)
        mode = "ab" if existing and resp.status_code == 206 else "wb"
        with part.open(mode) as fh:
            for chunk in resp.iter_bytes(_CHUNK):
                if chunk:
                    fh.write(chunk)
    part.replace(dest)


def _download_from_modelscope(size: str) -> None:
    repo_id = CATALOG[size]
    dest_dir = model_dir(size)
    timeout = httpx.Timeout(_HTTP_CONNECT_TIMEOUT, read=_HTTP_READ_TIMEOUT)
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        revision, names = _modelscope_needed_files(repo_id, client)
        logger.info("⬇️  从 ModelScope 下载 Whisper 模型 %s (%s@%s)", size, repo_id, revision)
        for name in names:
            url = _MODELSCOPE_RESOLVE.format(repo=repo_id, revision=revision, name=name)
            _http_download_file(client, url, dest_dir / name)
    if not is_downloaded(size):
        raise RuntimeError(f"ModelScope download incomplete for {size}")


def download(size: str, hf_endpoint: Optional[str] = None) -> None:
    """下载指定尺寸模型到 MODEL_DIR/<size>/。阻塞调用，请在线程中执行。

    hf_endpoint 非空时仅在本次下载临时设置 HF_ENDPOINT，结束后恢复。
    ModelScope 走直链，不经过 huggingface_hub。
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
            if is_modelscope_source(endpoint):
                _download_from_modelscope(size)
                logger.info("✅ Whisper 模型 %s 下载完成", size)
                return
            if not endpoint and not _hub_reachable():
                raise RuntimeError("huggingface.co unreachable")
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
            if endpoint and not is_modelscope_source(endpoint):
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

    默认模型在首启时立即下载。下载失败会
    自动退避重试；Hub 源用 snapshot_download 临时文件续传，ModelScope 用 .part
    续传。任务若需要
    本地转录，会等待默认模型就绪，不能在用户不知情时降级到 base。
    """
    global _default_worker
    if is_downloaded(DEFAULT_MODEL):
        _default_ready.set()
        _default_degraded.clear()
        _set_default_state("ready", error=None, next_retry_at=None)
        return

    def _worker():
        endpoints = download_endpoints_for(hf_endpoint)
        attempt = 0
        tried: list[str] = []
        while not is_downloaded(DEFAULT_MODEL):
            attempt += 1
            endpoint = next_download_endpoint(attempt, endpoints)
            label = download_endpoint_label(endpoint)
            if label not in tried:
                tried.append(label)
            _set_default_state(
                "degraded" if _default_degraded.is_set() else "downloading",
                error=None, attempt=attempt, next_retry_at=None,
                endpoint=label, tried_endpoints=tuple(tried),
            )
            try:
                download(DEFAULT_MODEL, endpoint or None)
            except Exception as e:
                if not completed_endpoint_cycle(attempt, endpoints):
                    _set_default_state(
                        "retrying",
                        error=str(e), attempt=attempt, next_retry_at=None,
                        endpoint=label, tried_endpoints=tuple(tried),
                    )
                    logger.warning(
                        "默认模型 %s 从 %s 下载失败，立即切换下一个源（第 %s 次）: %s",
                        DEFAULT_MODEL, label, attempt, e,
                    )
                    continue
                delay = min(300, 10 * (2 ** min(attempt // max(len(endpoints), 1) - 1, 5)))
                retry_at = int(time.time() + delay)
                _default_degraded.set()
                _set_default_state(
                    "degraded",
                    error=str(e), attempt=attempt, next_retry_at=retry_at,
                    endpoint=label, tried_endpoints=tuple(tried),
                )
                logger.warning(
                    "默认模型 %s 全部源均失败，%s 秒后自动续传（第 %s 次）: %s",
                    DEFAULT_MODEL, delay, attempt, e,
                )
                _default_retry_now.wait(delay)
                _default_retry_now.clear()
                continue
            _default_ready.set()
            _default_degraded.clear()
            _set_default_state(
                "ready", error=None, attempt=attempt, next_retry_at=None,
                endpoint=label, tried_endpoints=tuple(tried),
            )
            return

    with _default_worker_lock:
        if _default_worker is not None and _default_worker.is_alive():
            return
        _default_worker = threading.Thread(
            target=_worker, name="ensure-default-model", daemon=True,
        )
        _default_worker.start()


def retry_default_model_async() -> None:
    """立即唤醒失败后的重试等待；没有下载线程时重新启动。"""
    _default_retry_now.set()
    ensure_default_model_async()


def wait_for_default_model(cancel_token=None) -> bool:
    """等待最佳模型或明确降级条件；返回是否已取得最佳模型。"""
    ensure_default_model_async()
    while not _default_ready.is_set() and not _default_degraded.wait(0.5):
        if cancel_token is not None:
            cancel_token.check()
    return _default_ready.is_set()


def _resolve_available_size(size: Optional[str]) -> str:
    """规范模型名；模型缺失不能在这里静默改成 base。"""
    return size if size in CATALOG else DEFAULT_MODEL


def _model_after_default_wait(ready: bool) -> str:
    """只降级到已下载或真实随包的模型，避免隐式网络加载。"""
    if ready:
        return DEFAULT_MODEL
    selected = next((size for size in FALLBACK_MODELS if is_available(size)), None)
    if selected is None:
        raise RuntimeError(
            "默认转录模型下载失败，且没有可用的本地模型；"
            "请联网重试，或先在设置中下载 base 等转录模型"
        )
    logger.warning(
        "默认模型连续准备失败，本次明确降级使用本地模型 %s；后台仍在恢复 %s",
        selected, DEFAULT_MODEL,
    )
    return selected


class _DefaultModelTranscriber:
    """默认模型的惰性门闩：字幕路径不阻塞，真正转录时等待下载完成。"""

    model_size = DEFAULT_MODEL

    async def transcribe(
        self,
        audio_path: str,
        language=None,
        progress_callback=None,
        strategy=None,
        _segments_callback=None,
        _speech_ranges_callback=None,
    ) -> str:
        import asyncio
        import cancellation

        ready = await asyncio.to_thread(wait_for_default_model, cancellation.current())
        selected = _model_after_default_wait(ready)
        delegate = _get_local_transcriber(selected)
        if strategy is not None and strategy.model_id != selected:
            strategy = replace(strategy, model_id=selected)
        return await delegate.transcribe(
            audio_path,
            language=language,
            progress_callback=progress_callback,
            strategy=strategy,
            _segments_callback=_segments_callback,
            _speech_ranges_callback=_speech_ranges_callback,
        )

    async def transcribe_with_quality(
        self,
        audio_path: str,
        *,
        audio_profile,
        strategy,
        progress_callback=None,
    ):
        import asyncio
        import cancellation

        ready = await asyncio.to_thread(wait_for_default_model, cancellation.current())
        selected = _model_after_default_wait(ready)
        delegate = _get_local_transcriber(selected)
        if strategy.model_id != selected:
            strategy = replace(strategy, model_id=selected)
        return await delegate.transcribe_with_quality(
            audio_path,
            audio_profile=audio_profile,
            strategy=strategy,
            progress_callback=progress_callback,
        )

    def get_detected_language(self, transcript_text=None):
        delegate = _registry.get(DEFAULT_MODEL)
        if delegate is None:
            return None
        return delegate.get_detected_language(transcript_text)


_default_transcriber = _DefaultModelTranscriber()


def _get_local_transcriber(size: str) -> Transcriber:
    """创建已确定尺寸的真实 Transcriber，不执行模型降级。"""
    cached = _registry.get(size)
    if cached is not None:
        return cached
    with _registry_lock:
        cached = _registry.get(size)
        if cached is not None:
            return cached
        local_path = model_dir(size) if is_downloaded(size) else bundled_model_dir(size)
        path = str(local_path) if local_path is not None else CATALOG[size]
        transcriber = Transcriber(model_size=size, model_path=path)
        _registry[size] = transcriber
        return transcriber


def get_transcriber(size: Optional[str] = None) -> Transcriber:
    """按尺寸取得（必要时创建并缓存）Transcriber。

    默认模型尚未下载时返回惰性门闩：字幕任务不受影响，真正进入转录阶段才
    等待首启后台下载完成。准备失败时只降级到真实存在的本地模型。
    """
    size = _resolve_available_size(size)
    if size == DEFAULT_MODEL and not is_downloaded(size):
        return _default_transcriber  # type: ignore[return-value]
    return _get_local_transcriber(size)
