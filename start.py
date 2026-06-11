#!/usr/bin/env python3
"""
AI视频转录器 — 桌面应用启动入口

启动本地 API 服务后，以原生 WebView 窗口渲染前端界面，
提供完整的桌面软件体验（无需外部浏览器）。
"""

import os
import sys
import time
import signal
import threading
from pathlib import Path

# ── 项目根目录检测（支持普通运行和 PyInstaller 打包） ──
if getattr(sys, "frozen", False):
    # PyInstaller 打包后，sys.executable 在打包目录下
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent

BACKEND_DIR = APP_DIR / "backend"

# ── 加载 .env 配置 ──
def _load_dotenv_simple(dotenv_path: Path) -> None:
    """简易 .env 加载器（避免打包后 dotenv 路径问题）"""
    if not dotenv_path.exists():
        return
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = val

_load_dotenv_simple(APP_DIR / ".env")

# ── 检测内置 FFmpeg ──
def _find_ffmpeg() -> str | None:
    """查找 FFmpeg 可执行文件，优先使用打包内置的版本"""
    candidates = []
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            candidates = [
                APP_DIR / "ffmpeg",
                APP_DIR / "bin" / "ffmpeg",
            ]
        elif sys.platform == "win32":
            candidates = [
                APP_DIR / "ffmpeg.exe",
                APP_DIR / "bin" / "ffmpeg.exe",
            ]
        else:
            candidates = [
                APP_DIR / "ffmpeg",
                APP_DIR / "bin" / "ffmpeg",
            ]
    else:
        candidates = [
            APP_DIR / "ffmpeg_bin" / "ffmpeg",
            APP_DIR / "bin" / "ffmpeg",
        ]

    import shutil
    for p in candidates:
        if p.exists() and shutil.which(str(p)):
            return str(p)
    # fallback: system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    return system_ffmpeg

FFMPEG_PATH = _find_ffmpeg()
if FFMPEG_PATH:
    os.environ["PATH"] = str(Path(FFMPEG_PATH).parent) + os.pathsep + os.environ.get("PATH", "")

# ── 默认环境变量 ──
os.environ.setdefault("HOST", "127.0.0.1")
os.environ.setdefault("PORT", "8000")
os.environ.setdefault("WHISPER_MODEL_SIZE", "base")
os.environ.setdefault("UPLOAD_MAX_MB", "200")
os.environ.setdefault("OPENAI_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))


def _run_server():
    """在后台线程中运行 uvicorn 服务"""
    import uvicorn
    import logging

    logging.basicConfig(level=logging.INFO)

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    # 开发模式：切换到 backend/ 目录确保 flat import 正常
    # 打包模式：PyInstaller 已处理模块导入，无需切换目录
    if BACKEND_DIR.exists():
        os.chdir(str(BACKEND_DIR))

    config = uvicorn.Config(
        "main:app",
        host=host,
        port=port,
        log_level="info",
        # 桌面应用不需要热重载
    )
    server = uvicorn.Server(config)
    server.run()


def main():
    # 解析命令行参数
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    print(f"🚀 AI视频转录器")
    print(f"   本地服务: http://{host}:{port}")
    if FFMPEG_PATH:
        print(f"   FFmpeg:   {FFMPEG_PATH}")
    else:
        print(f"   ⚠️  FFmpeg 未找到，部分功能可能不可用")
    print("=" * 50)

    # 启动后端服务线程
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # 等待服务就绪
    url = f"http://{host}:{port}"
    print(f"⏳ 等待服务启动...")
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(url, timeout=0.5)
            break
        except Exception:
            time.sleep(0.3)
    else:
        print("⚠️  服务可能启动较慢，窗口即将打开...")

    print(f"🪟 启动桌面窗口...")

    try:
        import webview

        webview.create_window(
            title="AI视频转录器",
            url=url,
            width=1200,
            height=800,
            min_size=(800, 600),
            text_select=True,
            confirm_close=False,
        )
        webview.start(debug=False)

    except ImportError:
        # 如果未安装 pywebview，回退到浏览器
        print("⚠️  pywebview 未安装，正在使用默认浏览器打开...")
        import webbrowser
        webbrowser.open(url)
        print("按 Ctrl+C 停止服务")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    print("👋 应用已关闭")


if __name__ == "__main__":
    main()
