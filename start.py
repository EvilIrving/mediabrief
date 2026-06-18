#!/usr/bin/env python3
"""
MediaBrief — 桌面应用启动入口

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

# ── yt-dlp 运行时自更新：必须在任何 import yt_dlp 之前启用可写副本覆盖 ──
# 让打包应用里的 yt-dlp 不被「构建时版本」永久冻结：启用已下好的可写副本（若有），
# 并按周在后台拉取最新 stable（透明、不暴露任何参数；详见 yt_dlp_updater.py）。
try:
    import yt_dlp_updater
    yt_dlp_updater.schedule_update()
except Exception as _e:
    print(f"⚠️  yt-dlp 自更新初始化失败（将用随包版本）: {_e}")

# ── 检测内置 FFmpeg / FFprobe ──
def _find_tool(tool: str) -> str | None:
    """查找 ffmpeg / ffprobe 可执行文件，优先使用打包内置的版本。

    打包后内置二进制与 exe 同级（macOS: Contents/MacOS/；Windows: 同目录）；
    开发模式落在 ffmpeg_bin/（build_ffmpeg.sh 产物名带 -arm64 后缀）。
    """
    import shutil
    exe = f"{tool}.exe" if sys.platform == "win32" else tool
    if getattr(sys, "frozen", False):
        candidates = [APP_DIR / exe, APP_DIR / "bin" / exe]
    else:
        candidates = [
            APP_DIR / "ffmpeg_bin" / exe,
            APP_DIR / "ffmpeg_bin" / f"{tool}-arm64",
            APP_DIR / "bin" / exe,
        ]
    for p in candidates:
        if p.exists() and shutil.which(str(p)):
            return str(p)
    # fallback: system PATH
    return shutil.which(tool)

FFMPEG_PATH = _find_tool("ffmpeg")
FFPROBE_PATH = _find_tool("ffprobe")
if FFMPEG_PATH:
    os.environ["PATH"] = str(Path(FFMPEG_PATH).parent) + os.pathsep + os.environ.get("PATH", "")
    # 把绝对路径显式交给后端：yt-dlp 用 ffmpeg_location、直接子进程用绝对路径，
    # 不再依赖 PATH（打包后尤其 Windows 上 PATH 查找极易 FileNotFoundError）。
    os.environ.setdefault("AIT_FFMPEG", FFMPEG_PATH)
    os.environ.setdefault("AIT_FFMPEG_LOCATION", str(Path(FFMPEG_PATH).parent))
if FFPROBE_PATH:
    os.environ.setdefault("AIT_FFPROBE", FFPROBE_PATH)

# ── 检测内置 Deno（YouTube nsig 签名解算所需的 JS 运行时） ──
# yt-dlp 解 YouTube nsig 签名走 EJS 方案（platforms/youtube.py 的
# remote_components=["ejs:github"]），需要本机有 Deno 才能执行解算脚本。
# 终端用户机器上通常没有 Deno，缺失时 YouTube 可用 format 会被清空，
# 表现为 “Requested format is not available”。这里查找打包内置的 deno，
# 并把其所在目录注入 PATH —— yt-dlp 的 deno provider 通过 PATH 发现它
# （macOS 用 basename + PATH 查找，Windows frozen 还会查 exe 同级目录）。
def _find_deno() -> str | None:
    """查找 Deno 可执行文件，优先使用打包内置的版本。"""
    exe = "deno.exe" if sys.platform == "win32" else "deno"
    if getattr(sys, "frozen", False):
        candidates = [APP_DIR / exe, APP_DIR / "bin" / exe]
    else:
        candidates = [APP_DIR / "deno_bin" / exe, APP_DIR / "bin" / exe]

    import shutil
    for p in candidates:
        if p.exists() and shutil.which(str(p)):
            return str(p)
    # fallback: 系统 PATH 上已安装的 deno
    return shutil.which("deno")

DENO_PATH = _find_deno()
if DENO_PATH:
    os.environ["PATH"] = str(Path(DENO_PATH).parent) + os.pathsep + os.environ.get("PATH", "")

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


# ── 首次启动：后台确保默认模型(large-v3-turbo)就绪 ──
# 内嵌只播种 base；默认模型在此后台下载，下载期间任务优雅回退到 base，
# 完成后后续任务自动用上默认模型。网络不可达时静默放弃，不影响 base 转录。
def _ensure_default_model():
    try:
        from whisper_models import ensure_default_model_async
        ensure_default_model_async()
    except Exception as e:
        print(f"⚠️  默认模型后台准备失败（将用内嵌 base 回退）: {e}")

_ensure_default_model()


# ── 确保 faster-whisper 的 VAD 模型可被定位 ──
def _ensure_vad_asset():
    """保证 silero_vad_v6.onnx 能被 faster-whisper 找到。

    faster_whisper.vad 通过 ``get_assets_path()`` = ``dirname(__file__)/assets``
    定位 VAD 模型。PyInstaller 把该数据文件收进 ``Contents/Resources``，靠
    ``Frameworks/faster_whisper -> ../Resources/faster_whisper`` 这个符号链接才
    使期望路径可达。分发时(某些解压器/拷贝方式)若符号链接丢失，期望路径就会失效，
    转录时报 ``ONNXRuntimeError NO_SUCHFILE: silero_vad_v6.onnx File doesn't exist``。
    这里绕过符号链接、直接探测 Resources 下的真实文件，必要时把 get_assets_path
    指向它，确保即使链接损坏也能加载。
    """
    if not getattr(sys, "frozen", False):
        return
    asset = "silero_vad_v6.onnx"
    meipass = Path(getattr(sys, "_MEIPASS", APP_DIR))
    # 候选目录：期望路径(可能是符号链接) → Resources 下的真实目录(macOS .app)
    candidates = [
        meipass / "faster_whisper" / "assets",
        meipass.parent / "Resources" / "faster_whisper" / "assets",
    ]
    found = next((d for d in candidates if (d / asset).is_file()), None)
    if not found:
        return
    try:
        from faster_whisper.utils import get_assets_path
        # 期望路径已能拿到文件(符号链接完好)，无需干预
        if (Path(get_assets_path()) / asset).is_file():
            return
        import faster_whisper.vad as _fw_vad
        _fw_vad.get_assets_path = lambda _p=str(found): _p
        print(f"🔧 VAD 模型符号链接缺失，已重定向至: {found}")
    except Exception as e:
        print(f"⚠️  VAD 模型定位兜底失败: {e}")

_ensure_vad_asset()


# ── 桌面服务固定监听地址 ──
# 用户模型/API 配置由前端 Settings 面板管理，不再通过 .env/环境变量覆盖。
HOST = "127.0.0.1"
PORT = 8000


_cleanup_done = threading.Event()
_uvicorn_server = None
_server_thread = None


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
        server = _uvicorn_server
        if server is not None:
            server.should_exit = True
    except Exception:
        pass
    try:
        import cancellation
        n = cancellation.cancel_all()
        if n:
            print(f"🧹 已终止 {n} 个进行中的任务")
    except Exception:
        pass
    try:
        thread = _server_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
    except Exception:
        pass


def _signal_handler(signum, _frame):
    """收到 SIGINT/SIGTERM(系统退出/Ctrl+C)：清理后强制退出。"""
    _shutdown_cleanup()
    os._exit(0)


def _run_server():
    """在后台线程中运行 uvicorn 服务"""
    global _uvicorn_server
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
        _uvicorn_server = server
        server.run()
    except Exception:
        traceback.print_exc()
        try:
            with open(APP_DIR / "server_error.log", "w") as f:
                traceback.print_exc(file=f)
        except Exception:
            pass
    finally:
        _uvicorn_server = None


def main():
    # 解析命令行参数
    no_window = "--no-window" in sys.argv or "--server" in sys.argv

    # ── 尽早配置日志：让启动阶段的诊断（FFmpeg/Deno 检测、依赖预加载、
    #    yt-dlp 报错）全部落到日志文件。打包成无控制台的 .app/exe 后，
    #    print() 会丢失，文件日志是终端用户唯一能回传的排查依据。
    #    configure_logging 幂等，_run_server 里再次调用不会重复挂 handler。 ──
    import logging
    log_file = None
    try:
        from logging_config import configure_logging
        log_file = configure_logging()
    except Exception as e:
        print(f"⚠️  日志系统初始化失败: {e}")
    logger = logging.getLogger("startup")

    def _report(msg: str, level: int = logging.INFO):
        """同时写控制台（开发可见）与日志文件（打包后唯一可回传）。"""
        print(msg)
        logger.log(level, msg)

    url = f"http://{HOST}:{PORT}"
    _report(f"🚀 MediaBrief")
    _report(f"   本地服务: {url}")
    if log_file:
        _report(f"   日志文件: {log_file}")
    if FFMPEG_PATH:
        _report(f"   FFmpeg:   {FFMPEG_PATH}")
    else:
        _report(f"   ⚠️  FFmpeg 未找到，部分功能可能不可用", logging.WARNING)
    if DENO_PATH:
        _report(f"   Deno:     {DENO_PATH}")
    else:
        _report(f"   ⚠️  Deno 未找到，YouTube 签名解算可能失败（Requested format is not available）", logging.WARNING)
    _report("=" * 50)

    # 提前触发重型依赖导入（faster-whisper / ctranslate2 等），避免阻塞 uvicorn 启动
    _report("📦 预加载依赖...")
    t0 = time.time()
    try:
        from services import transcriber as _preload_t
        _report(f"   ✅ 依赖加载完成 ({time.time()-t0:.1f}s)")
    except Exception as e:
        _report(f"   ⚠️  依赖预加载失败: {e}", logging.ERROR)

    # ── 退出清理：覆盖正常退出(atexit)与系统信号(SIGINT/SIGTERM)两条路径，
    #    确保无论如何关闭，进行中的任务及其子进程(ffmpeg 等)都被回收。 ──
    atexit.register(_shutdown_cleanup)
    for _sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(_sig, _signal_handler)
        except (ValueError, OSError):
            pass  # 非主线程或平台不支持时忽略

    # 启动后端服务线程
    global _server_thread
    server_thread = threading.Thread(target=_run_server, daemon=True)
    _server_thread = server_thread
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
        _shutdown_cleanup()
        print("👋 应用已关闭")
        return

    print(f"🪟 启动桌面窗口...")

    try:
        import webview

        loading_html = f"""
<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><style>
  :root {{
    --bg: oklch(17% 0.004 75);
    --surface: oklch(22% 0.005 75);
    --surface-2: oklch(27% 0.006 75);
    --surface-3: oklch(32% 0.007 75);
    --border-color: oklch(38% 0.008 75);
    --border-light: oklch(44% 0.009 75);
    --accent: oklch(58% 0.13 60);
    --accent-h: oklch(63% 0.13 60);
    --accent-text: oklch(68% 0.13 60);
    --text: oklch(88% 0.004 75);
    --text-muted: oklch(60% 0.006 75);
    --text-dim: oklch(42% 0.006 75);
    --r: 12px;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: oklch(97% 0.004 85);
      --surface: oklch(99% 0.003 85);
      --surface-2: oklch(96% 0.004 85);
      --surface-3: oklch(93% 0.005 85);
      --border-color: oklch(88% 0.007 85);
      --border-light: oklch(84% 0.008 85);
      --accent: oklch(53% 0.13 60);
      --accent-h: oklch(48% 0.13 60);
      --accent-text: oklch(44% 0.11 60);
      --text: oklch(20% 0.006 85);
      --text-muted: oklch(45% 0.007 85);
      --text-dim: oklch(65% 0.006 85);
    }}
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    min-height: 100vh;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
    display: flex;
    flex-direction: column;
  }}
  .navbar {{
    display: flex; align-items: center; justify-content: space-between;
    gap: 18px; padding: 12px 28px;
    border-bottom: 1px solid var(--border-color);
  }}
  .nav-logo {{ display: flex; align-items: center; gap: 9px; }}
  .nav-logo svg {{ width: 26px; height: 26px; flex: 0 0 auto; }}
  .nav-logo-text {{ font-size: 15px; font-weight: 650; letter-spacing: 0; }}
  .nav-logo-text em {{ color: var(--accent-text); font-style: normal; }}
  .nav-status {{ font-size: 12px; color: var(--text-muted); }}
  main {{
    width: 100%; max-width: 1024px; margin: 0 auto;
    padding: 36px 24px 56px; flex: 1;
    display: flex; align-items: center; justify-content: center;
  }}
  .panel {{
    width: min(100%, 720px);
    background: var(--surface);
    border: 1.5px dashed var(--border-light);
    border-radius: var(--r);
    padding: 56px 24px;
    display: flex; flex-direction: column; align-items: center;
    gap: 14px; text-align: center;
  }}
  .mark {{
    width: 64px; height: 64px; border-radius: 16px;
    background: var(--surface-2);
    border: 1px solid var(--border-color);
    display: grid; place-items: center;
  }}
  .mark svg {{ width: 44px; height: 44px; }}
  .title {{ font-size: 18px; font-weight: 650; line-height: 1.3; }}
  .status {{ font-size: 13px; color: var(--text-muted); min-height: 21px; }}
  .progress {{
    width: min(240px, 80%); height: 6px; overflow: hidden;
    border-radius: 999px; background: var(--surface-3); margin-top: 4px;
  }}
  .progress span {{
    display: block; width: 42%; height: 100%; border-radius: inherit;
    background: var(--accent);
    animation: progress 1.25s ease-in-out infinite;
  }}
  @keyframes progress {{
    0% {{ transform: translateX(-110%); }}
    100% {{ transform: translateX(260%); }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .progress span {{ animation: none; transform: none; width: 35%; }}
  }}
</style></head>
<body>
  <header class="navbar">
    <div class="nav-logo">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" aria-label="MediaBrief">
        <rect width="1024" height="1024" fill="var(--bg)"/>
        <path d="M 112,386 L 232,386 L 264,354 L 296,386 L 376,226 L 432,546 L 488,386 L 572,354 L 614,386 L 912,386"
              fill="none" stroke="var(--accent-h)" stroke-width="36" stroke-linecap="round" stroke-linejoin="round"/>
        <rect x="112" y="606" width="800" height="48" rx="24" fill="var(--accent-h)"/>
        <rect x="112" y="678" width="576" height="48" rx="24" fill="var(--accent-h)"/>
        <rect x="112" y="750" width="360" height="48" rx="24" fill="var(--accent-h)"/>
      </svg>
      <div class="nav-logo-text">Media<em>Brief</em></div>
    </div>
    <div class="nav-status">Desktop</div>
  </header>
  <main>
    <section class="panel" aria-live="polite">
      <div class="mark">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" aria-hidden="true">
          <path d="M 112,386 L 232,386 L 264,354 L 296,386 L 376,226 L 432,546 L 488,386 L 572,354 L 614,386 L 912,386"
                fill="none" stroke="var(--accent-h)" stroke-width="36" stroke-linecap="round" stroke-linejoin="round"/>
          <rect x="112" y="606" width="800" height="48" rx="24" fill="var(--accent-h)"/>
          <rect x="112" y="678" width="576" height="48" rx="24" fill="var(--accent-h)"/>
          <rect x="112" y="750" width="360" height="48" rx="24" fill="var(--accent-h)"/>
        </svg>
      </div>
      <div class="title">MediaBrief</div>
      <div class="status" id="status">正在启动服务…</div>
      <div class="progress"><span></span></div>
    </section>
  </main>
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
            title="MediaBrief",
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
        _shutdown_cleanup()

    print("👋 应用已关闭")


if __name__ == "__main__":
    main()
