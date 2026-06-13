"""后端统一日志配置。

目标：
- 所有后端入口（uvicorn 直启、start.py 桌面/服务模式）共用同一套日志输出。
- 终端 + 文件双写，文件落到可写目录，方便事后排查。
- 兼容 uvicorn 默认日志，避免它覆盖我们的文件处理器。
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FILE: Path | None = None
_CONFIGURED = False


def _get_log_dir() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "ai-transcriber"
        elif sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ai-transcriber"
        else:
            base = Path.home() / ".local" / "share" / "ai-transcriber"
        log_dir = base / "logs"
    else:
        log_dir = Path(__file__).resolve().parent.parent / "temp" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file() -> Path:
    global _LOG_FILE
    if _LOG_FILE is None:
        _LOG_FILE = _get_log_dir() / "backend.log"
    return _LOG_FILE


def configure_logging(level: int | None = None) -> Path:
    """配置 root logger，并让 uvicorn 日志复用同一套处理器。"""
    global _CONFIGURED

    if level is None:
        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

    log_file = get_log_file()
    if _CONFIGURED:
        return log_file

    formatter = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        mode="a",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    # uvicorn 默认会挂自己的 handler；这里改成向 root 传播，保证也能写入文件。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(level)

    def _sys_excepthook(exc_type, exc, tb):
        logging.getLogger("uncaught").error("Uncaught exception", exc_info=(exc_type, exc, tb))

    def _thread_excepthook(args):
        logging.getLogger("uncaught").error(
            "Uncaught thread exception in %s",
            getattr(args.thread, "name", "thread"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _sys_excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook

    logging.captureWarnings(True)
    _CONFIGURED = True
    return log_file
