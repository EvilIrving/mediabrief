"""yt-dlp 运行时自更新：让打包应用里的 yt-dlp 不被「构建时版本」永久冻结。

背景：yt-dlp 的发布主要是为了追赶各站点（尤其 YouTube）的反爬变化，stable 版
也会随时间「变质」而成片失败。但打包成 .app/.exe 后，bundle 内的 yt-dlp 版本就被
冻结了——用户无法自救，且 PyInstaller 冻结环境里没有 pip，``yt-dlp -U`` 也用不了。

策略（对用户完全透明、不暴露任何参数）：
- 维护一份**可写目录**里的 yt-dlp（纯 Python 包），并把它**置于 sys.path 最前**，
  从而覆盖 bundle 内随包冻结的那份；
- 启动时**节流（每周一次）**在后台拉取 PyPI 上最新 *stable* 的 wheel（纯 stdlib，
  无需 pip），解出 ``yt_dlp/`` 覆盖到该可写目录；
- 当次启动仍用「已就绪」的版本（首启用 bundle 内构建时的最新 stable），新版本下次
  启动生效——既拿到修复，又不阻塞启动、不破坏可复现性；
- 任何失败（网络不可达等）都静默放弃，回退到 bundle 内版本，绝不影响主流程。

软件层面的「请下载新安装包」属于未来的应用更新功能，不在此处。
"""
from __future__ import annotations

import io
import importlib.metadata
import json
import logging
import os
import shutil
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_UPDATE_INTERVAL_SEC = 7 * 24 * 3600  # 每周最多检查一次
_PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
_HTTP_TIMEOUT = 20
try:
    _BUNDLED_VERSION = importlib.metadata.version("yt-dlp")
except importlib.metadata.PackageNotFoundError:
    _BUNDLED_VERSION = "unknown"

_state_lock = threading.Lock()
_worker_lock = threading.Lock()
_update_thread: threading.Thread | None = None
_retry_wake = threading.Event()
_state: dict[str, object] = {
    "status": "idle",
    "bundled_version": _BUNDLED_VERSION,
    "current_version": "",
    "downloaded_version": None,
    "last_check": None,
    "error": None,
    "pending_restart": False,
    "attempt": 0,
    "next_retry_at": None,
}


def _set_state(status: str, **fields) -> None:
    with _state_lock:
        _state.update(status=status, **fields)


def _data_dir() -> Path:
    """可写数据目录（与 start.py 的播种目录保持一致）。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ai-transcriber"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ai-transcriber"
    return Path.home() / ".local" / "share" / "ai-transcriber"


def _runtime_dir() -> Path:
    return _data_dir() / "yt-dlp-runtime"


def _stamp_file() -> Path:
    return _runtime_dir() / ".last_check"


def activate() -> None:
    """若可写目录内已有可用的 yt_dlp 包，则把它置于 sys.path 最前。

    必须在任何 ``import yt_dlp`` *之前* 调用。
    """
    rt = _runtime_dir()
    if (rt / "yt_dlp" / "__init__.py").is_file():
        p = str(rt)
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
        logger.info("yt-dlp 运行时覆盖已启用: %s", rt)


def _should_check() -> bool:
    stamp = _stamp_file()
    if not stamp.is_file():
        return True
    try:
        return (time.time() - stamp.stat().st_mtime) > _UPDATE_INTERVAL_SEC
    except OSError:
        return True


def _touch_stamp() -> None:
    try:
        _runtime_dir().mkdir(parents=True, exist_ok=True)
        _stamp_file().write_text(str(int(time.time())), encoding="utf-8")
    except OSError as e:
        logger.debug("写入 yt-dlp 更新时间戳失败: %s", e)


def update_status() -> dict:
    """返回当前实际版本和最近更新结果，供应用诊断展示。"""
    with _state_lock:
        state = dict(_state)
    state["current_version"] = _installed_version() or state.get("current_version") or "unknown"
    stamp = _stamp_file()
    if stamp.is_file():
        try:
            state["last_check"] = int(stamp.stat().st_mtime)
        except OSError:
            pass
    return state


def _installed_version() -> str:
    try:
        import yt_dlp.version as v  # type: ignore
        return getattr(v, "__version__", "")
    except Exception:
        return ""


def _fetch_latest_to_runtime() -> None:
    """下载 PyPI 最新 stable 的 yt-dlp wheel，解出 yt_dlp/ 覆盖到可写目录。"""
    _set_state("checking", error=None, pending_restart=False)
    with urllib.request.urlopen(_PYPI_URL, timeout=_HTTP_TIMEOUT) as resp:
        meta = json.load(resp)

    latest = meta["info"]["version"]
    # 已是最新则只更新时间戳，避免无谓下载（无论运行的是 bundle 还是可写副本）。
    if latest == _installed_version():
        logger.info("yt-dlp 已是最新 stable %s，跳过下载", latest)
        _touch_stamp()
        _set_state(
            "ready", current_version=latest, downloaded_version=latest,
            last_check=int(time.time()), error=None, pending_restart=False,
            next_retry_at=None,
        )
        return

    wheel_url = next(
        (f["url"] for f in meta["releases"].get(latest, []) if f["filename"].endswith(".whl")),
        None,
    )
    if not wheel_url:
        logger.warning("未找到 yt-dlp %s 的 wheel，放弃更新", latest)
        raise RuntimeError(f"未找到 yt-dlp {latest} wheel")

    _set_state("downloading", downloaded_version=latest, error=None)
    with urllib.request.urlopen(wheel_url, timeout=_HTTP_TIMEOUT) as resp:
        wheel_bytes = resp.read()

    rt = _runtime_dir()
    staging = rt.parent / "yt-dlp-runtime.staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    # wheel 即 zip；只取 yt_dlp/ 包（纯 Python，无需编译/依赖解析）。
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as zf:
        for name in zf.namelist():
            if name.startswith("yt_dlp/") and not name.endswith("/"):
                zf.extract(name, staging)

    if not (staging / "yt_dlp" / "__init__.py").is_file():
        shutil.rmtree(staging, ignore_errors=True)
        logger.warning("yt-dlp wheel 解包异常，放弃更新")
        raise RuntimeError(f"yt-dlp {latest} wheel 内容不完整")

    # 带回滚的目录交换：更新失败时继续保留上一个已验证的运行时版本。
    rt.mkdir(parents=True, exist_ok=True)
    old_pkg = rt / "yt_dlp"
    backup_pkg = rt / "yt_dlp.previous"
    if backup_pkg.exists():
        shutil.rmtree(backup_pkg, ignore_errors=True)
    try:
        if old_pkg.exists():
            old_pkg.replace(backup_pkg)
        (staging / "yt_dlp").replace(old_pkg)
    except Exception:
        if old_pkg.exists():
            shutil.rmtree(old_pkg, ignore_errors=True)
        if backup_pkg.exists():
            backup_pkg.replace(old_pkg)
        raise
    if backup_pkg.exists():
        shutil.rmtree(backup_pkg, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    _touch_stamp()
    _set_state(
        "ready", downloaded_version=latest, last_check=int(time.time()),
        error=None, pending_restart=True, next_retry_at=None,
    )
    logger.info("yt-dlp 已更新到 stable %s（下次启动生效）", latest)


def schedule_update(*, force: bool = False) -> None:
    """启用已就绪的可写副本，并按需在后台拉取最新 stable（非阻塞）。"""
    global _update_thread
    try:
        activate()
    except Exception as e:
        logger.debug("启用 yt-dlp 运行时覆盖失败: %s", e)

    current = _installed_version()
    _set_state("ready", current_version=current or "unknown")
    if not force and not _should_check():
        return

    def _run_update():
        attempt = 0
        while True:
            attempt += 1
            try:
                _fetch_latest_to_runtime()
                return
            except Exception as e:  # 保留当前可用版本，并在后台自动恢复
                delay = min(300, 15 * (2 ** min(attempt - 1, 5)))
                _set_state(
                    "retrying", error=str(e), last_check=int(time.time()),
                    attempt=attempt, next_retry_at=int(time.time() + delay),
                )
                logger.info("yt-dlp 更新失败，%s 秒后自动重试: %s", delay, e)
                _retry_wake.wait(delay)
                _retry_wake.clear()

    with _worker_lock:
        if _update_thread is not None and _update_thread.is_alive():
            return
        _update_thread = threading.Thread(
            target=_run_update, name="yt-dlp-updater", daemon=True,
        )
        _update_thread.start()


def retry_update_async() -> None:
    """忽略每周节流，立即在后台重新检查；仍保留当前可用版本。"""
    _retry_wake.set()
    schedule_update(force=True)
