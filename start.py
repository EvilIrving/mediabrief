#!/usr/bin/env python3
"""
AI Transcriber — 桌面应用启动入口

启动本地 API 服务后，以原生 WebView 窗口渲染前端界面，
提供完整的桌面软件体验（无需外部浏览器）。
"""

import os
import sys
import time
import atexit
import signal
import threading
import multiprocessing
from pathlib import Path

# ── 关键：PyInstaller 冻结后必须最先调用，否则子进程会重新执行整个 app，
#    造成无限自我启动（fork bomb）。务必在任何其他逻辑之前。 ──
multiprocessing.freeze_support()

# ── 项目根目录检测（支持普通运行和 PyInstaller 打包） ──
if getattr(sys, "frozen", False):
    # PyInstaller 打包后，sys.executable 在打包目录下
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent

BACKEND_DIR = APP_DIR / "backend"

# ── 确保 backend/ 在 sys.path 中（开发模式 uvicorn "main:app" + 预加载都依赖此路径） ──
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

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

# ── SSL 证书：PyInstaller 打包后自带的 CA 证书可能过期/缺失，
#    用 certifi 提供完整的 Mozilla CA bundle ──
if getattr(sys, "frozen", False):
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass

# ── 首次启动：把内嵌的 base 模型播种到可写数据目录 ──
def _seed_bundled_whisper_models():
    """将 bundle 内的 whisper-models/ 复制到可写数据目录（仅缺失时）。

    打包后 .app 内部只读，模型须落到 Application Support 等可写目录，
    base 才能离线即用、其余尺寸也下载到同一处。开发模式无内嵌模型，跳过。
    """
    if not getattr(sys, "frozen", False):
        return
    import shutil
    src = Path(getattr(sys, "_MEIPASS", APP_DIR)) / "whisper-models"
    if not src.is_dir():
        return
    if sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / "ai-transcriber"
    elif sys.platform == "win32":
        data_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ai-transcriber"
    else:
        data_dir = Path.home() / ".local" / "share" / "ai-transcriber"
    dst = data_dir / "whisper-models"
    try:
        for item in src.iterdir():
            target = dst / item.name
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(item, target)
    except Exception as e:
        print(f"⚠️  内嵌模型播种失败（首次转录将尝试联网下载）: {e}")

_seed_bundled_whisper_models()


# ── 桌面服务固定监听地址 ──
# 用户模型/API 配置由前端 Settings 面板管理，不再通过 .env/环境变量覆盖。
HOST = "127.0.0.1"
PORT = 8000


_cleanup_done = threading.Event()


def _shutdown_cleanup():
    """退出前回收所有进行中的任务及其子进程。

    桌面窗口关闭后 uvicorn(守护线程)会被直接抛弃，FastAPI 的 shutdown 钩子
    未必触发；而用 start_new_session 起的 ffmpeg 在独立进程组里，不随主进程退出
    而终止。这里直接调用同进程内的 cancellation.cancel_all() 把它们杀干净，
    等价于开发模式下 Ctrl+C 关闭全部后台任务。可被多条退出路径重复调用(幂等)。
    """
    if _cleanup_done.is_set():
        return
    _cleanup_done.set()
    try:
        import cancellation
        n = cancellation.cancel_all()
        if n:
            print(f"🧹 已终止 {n} 个进行中的任务")
    except Exception:
        pass


def _signal_handler(signum, _frame):
    """收到 SIGINT/SIGTERM(系统退出/Ctrl+C)：清理后强制退出。"""
    _shutdown_cleanup()
    os._exit(0)


def _run_server():
    """在后台线程中运行 uvicorn 服务"""
    import traceback
    try:
        import uvicorn
        from logging_config import configure_logging

        configure_logging()

        config = uvicorn.Config(
            "main:app",
            host=HOST,
            port=PORT,
            log_level="info",
            log_config=None,
            access_log=True,
        )
        server = uvicorn.Server(config)
        server.run()
    except Exception:
        traceback.print_exc()
        try:
            with open(APP_DIR / "server_error.log", "w") as f:
                traceback.print_exc(file=f)
        except Exception:
            pass


def main():
    # 解析命令行参数
    no_window = "--no-window" in sys.argv or "--server" in sys.argv

    url = f"http://{HOST}:{PORT}"
    print(f"🚀 AI Transcriber")
    print(f"   本地服务: {url}")
    if FFMPEG_PATH:
        print(f"   FFmpeg:   {FFMPEG_PATH}")
    else:
        print(f"   ⚠️  FFmpeg 未找到，部分功能可能不可用")
    print("=" * 50)

    # 提前触发重型依赖导入（faster-whisper / ctranslate2 等），避免阻塞 uvicorn 启动
    print("📦 预加载依赖...")
    t0 = time.time()
    try:
        from services import transcriber as _preload_t
        print(f"   ✅ 依赖加载完成 ({time.time()-t0:.1f}s)")
    except Exception as e:
        print(f"   ⚠️  依赖预加载失败: {e}")

    # ── 退出清理：覆盖正常退出(atexit)与系统信号(SIGINT/SIGTERM)两条路径，
    #    确保无论如何关闭，进行中的任务及其子进程(ffmpeg 等)都被回收。 ──
    atexit.register(_shutdown_cleanup)
    for _sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(_sig, _signal_handler)
        except (ValueError, OSError):
            pass  # 非主线程或平台不支持时忽略

    # 启动后端服务线程
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # ── 无窗口模式（--no-window / --server）：仅启动服务，打开浏览器 ──
    if no_window:
        import webbrowser
        print(f"🌐 服务模式，打开浏览器: {url}")
        webbrowser.open(url)
        print("按 Ctrl+C 停止服务")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        print("👋 应用已关闭")
        return

    print(f"🪟 启动桌面窗口...")

    try:
        import webview

        loading_html = f"""
<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background: #0d0b09;
    color: #ddd5cb;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    display: flex; align-items: center; justify-content: center;
    height: 100vh; flex-direction: column; gap: 20px;
  }}
  .logo svg {{ width: 72px; height: 72px; }}
  .title {{ font-size: 18px; font-weight: 650; }}
  .title em {{ color: #c07830; font-style: normal; }}
  .status {{ font-size: 13px; color: #8c7e70; }}
  .dots {{ display: flex; gap: 5px; }}
  .dots span {{ width: 5px; height: 5px; border-radius: 50%; background: #c07830; animation: pulse 1s ease-in-out infinite; }}
  .dots span:nth-child(2) {{ animation-delay: .15s; }}
  .dots span:nth-child(3) {{ animation-delay: .3s; }}
  @keyframes pulse {{ 0%,100% {{ opacity: .3; transform: translateY(0); }} 45% {{ opacity: 1; transform: translateY(-4px); }} }}
</style></head>
<body>
  <div class="logo">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" aria-label="AI Transcribe">
      <rect width="1024" height="1024" fill="#0d0b09"/>
      <path d="M 112,386 L 232,386 L 264,354 L 296,386 L 376,226 L 432,546 L 488,386 L 572,354 L 614,386 L 912,386"
            fill="none" stroke="#d08840" stroke-width="36" stroke-linecap="round" stroke-linejoin="round"/>
      <rect x="112" y="606" width="800" height="48" rx="24" fill="#d08840"/>
      <rect x="112" y="678" width="576" height="48" rx="24" fill="#d08840"/>
      <rect x="112" y="750" width="360" height="48" rx="24" fill="#d08840"/>
    </svg>
  </div>
  <div class="title">AI<em>Transcriber</em></div>
  <div class="dots"><span></span><span></span><span></span></div>
  <div class="status" id="status">正在启动服务…</div>
  <script>
    var appUrl = "{url}";
    var attempts = 0;
    function check() {{
      attempts++;
      fetch(appUrl, {{ mode: 'no-cors' }})
        .then(function() {{ window.location.href = appUrl; }})
        .catch(function() {{
          if (attempts > 15) document.getElementById('status').textContent = '正在初始化，请稍候…';
          if (attempts < 600) setTimeout(check, 500);
        }});
    }}
    check();
  </script>
</body>
</html>"""

        webview.create_window(
            title="AI Transcriber",
            html=loading_html,
            width=1200,
            height=800,
            min_size=(800, 600),
            text_select=True,
            confirm_close=True,
        )
        webview.start(debug=False)
        # 窗口关闭，webview.start() 返回 → 立即回收后台任务，不等进程自然退出。
        _shutdown_cleanup()

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
