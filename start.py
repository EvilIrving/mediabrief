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
import logging
import signal
import socket
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
    os.environ.setdefault("AIT_DENO", DENO_PATH)

# ── SSL 证书：PyInstaller 打包后自带的 CA 证书可能过期/缺失，
#    用 certifi 提供完整的 Mozilla CA bundle ──
if getattr(sys, "frozen", False):
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass

# ── 首次启动：把可选内嵌模型播种到可写数据目录 ──
def _seed_bundled_whisper_models():
    """将 bundle 内的 whisper-models/ 复制到可写数据目录（仅缺失时）。

    打包后 .app 内部只读，模型须落到 Application Support 等可写目录，
    内嵌开关默认关闭；包内没有 whisper-models/ 时直接跳过。
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

def _start_runtime_preparation() -> None:
    """模型播种和默认大模型下载都在后台进行，不能挡住主窗口。"""
    def _prepare():
        _seed_bundled_whisper_models()
        try:
            from whisper_models import ensure_default_model_async
            ensure_default_model_async()
        except Exception as e:
            print(f"⚠️  默认模型后台准备启动失败: {e}")

    threading.Thread(target=_prepare, name="runtime-preparation", daemon=True).start()


# 注：Phase 1 移除了 faster-whisper 的 Silero VAD 资产定位兜底（引擎已换成
# mlx-whisper）。长音频抗幻觉/重复改由 transcriber 的分块阈值兜底；Phase 2 若
# 引入 Silero 前置 VAD，再以新形式补回资产处理。


# ── 桌面服务监听地址 ──
# 端口由系统分配，避免用户机器上 8000 被占用时整个应用无法启动。
HOST = "127.0.0.1"
PORT = 0


from desktop_shutdown import (
    detect_ui_lang,
    normalize_ui_lang,
    quit_localization,
    should_confirm_close,
)

# 窗口已关后再等 uvicorn，Dock 图标会多挂几秒。cancel_all 已杀掉
# ffmpeg 进程组；uvicorn 线程是 daemon，进程退出会带走。短等只为让端口松开。
_SERVER_JOIN_TIMEOUT = 0.5

_ui_lang = detect_ui_lang()
_cleanup_lock = threading.Lock()
_cleanup_done = threading.Event()
_uvicorn_server = None
_server_thread = None
_listen_socket: socket.socket | None = None
_server_failed = threading.Event()


def _create_listen_socket() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((HOST, 0))
    listener.listen(128)
    listener.set_inheritable(True)
    return listener


def _has_active_work() -> bool:
    try:
        import cancellation
        return should_confirm_close(cancellation.active_count())
    except Exception:
        return True


def _prepare_quit_dialog(window) -> None:
    """空闲直接关；有任务才弹确认。文案跟界面语言走。"""
    try:
        window.confirm_close = _has_active_work()
    except Exception:
        window.confirm_close = True
    try:
        window.localization.update(quit_localization(_ui_lang))
    except Exception:
        pass


def _shutdown_cleanup():
    """退出前回收所有进行中的任务及其子进程。

    桌面窗口关闭后 uvicorn(守护线程)会被直接抛弃，FastAPI 的 shutdown 钩子
    未必触发；而用 start_new_session 起的 ffmpeg 在独立进程组里，不随主进程退出
    而终止。这里直接调用同进程内的 cancellation.cancel_all() 把它们杀干净，
    等价于开发模式下 Ctrl+C 关闭全部后台任务。可被多条退出路径重复调用(幂等)。
    """
    if _cleanup_done.is_set():
        return
    with _cleanup_lock:
        if _cleanup_done.is_set():
            return
        try:
            # 先杀 ffmpeg 等孤儿进程组，再通知服务退出。
            try:
                import cancellation
                cancellation.begin_shutdown()
                n = cancellation.cancel_all()
                if n:
                    print(f"🧹 已终止 {n} 个进行中的任务")
            except Exception:
                pass
            try:
                server = _uvicorn_server
                if server is not None:
                    server.should_exit = True
            except Exception:
                pass
            try:
                listener = _listen_socket
                if listener is not None:
                    listener.close()
            except OSError:
                pass
            try:
                from single_instance import release_instance_lock
                release_instance_lock("launcher")
            except Exception:
                pass
            try:
                thread = _server_thread
                if (
                    thread is not None
                    and thread.is_alive()
                    and thread is not threading.current_thread()
                ):
                    thread.join(timeout=_SERVER_JOIN_TIMEOUT)
            except Exception:
                pass
        finally:
            _cleanup_done.set()


def _signal_handler(signum, _frame):
    """收到 SIGINT/SIGTERM(系统退出/Ctrl+C)：清理后强制退出。"""
    _shutdown_cleanup()
    os._exit(0)


def _run_server():
    """在后台线程中运行 uvicorn 服务"""
    global _uvicorn_server
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
        listener = _listen_socket
        server.run(sockets=[listener] if listener is not None else None)
    except Exception:
        logging.getLogger("startup").exception("本地服务启动失败")
        _server_failed.set()
    finally:
        _uvicorn_server = None


def _start_server_thread() -> None:
    global _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        return
    _server_failed.clear()
    _server_thread = threading.Thread(target=_run_server, name="local-api", daemon=True)
    _server_thread.start()


class _StartupApi:
    """加载页只拿到可操作状态，不把内部异常直接暴露给普通用户。"""

    def __init__(self):
        self._window = None

    def bind_window(self, window):
        self._window = window

    def set_ui_lang(self, lang):
        """界面语言变了：下次退出确认跟界面走，不跟系统语言死绑。"""
        global _ui_lang
        _ui_lang = normalize_ui_lang(lang)
        try:
            if self._window is not None:
                self._window.localization.update(quit_localization(_ui_lang))
        except Exception:
            pass
        return _ui_lang

    def state(self):
        return {"failed": _server_failed.is_set()}

    def retry(self):
        global _listen_socket, PORT
        if _listen_socket is None or _listen_socket.fileno() < 0:
            _listen_socket = _create_listen_socket()
            PORT = int(_listen_socket.getsockname()[1])
            try:
                from single_instance import update_instance_lock_metadata
                update_instance_lock_metadata(
                    "launcher", port=PORT, url=f"http://{HOST}:{PORT}",
                )
            except Exception:
                pass
        _start_server_thread()
        return {"url": f"http://{HOST}:{PORT}"}

    def open_url(self, url):
        """设置里的「检查更新」只打开下载页；拒绝其它地址。"""
        if not isinstance(url, str):
            return False
        allowed = (
            "https://evilirving.github.io/mediabrief",
            "https://github.com/EvilIrving/mediabrief",
        )
        if not url.startswith(allowed):
            return False
        try:
            import webbrowser
            webbrowser.open(url)
            return True
        except Exception:
            return False

    def open_logs(self):
        try:
            import subprocess
            from logging_config import get_log_file

            log_dir = get_log_file().parent
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(log_dir)])
            elif sys.platform == "win32":
                os.startfile(str(log_dir))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(log_dir)])
            return True
        except Exception:
            return False


def main():
    # 解析命令行参数
    no_window = "--no-window" in sys.argv or "--server" in sys.argv

    # ── 尽早配置日志：让启动阶段的诊断（FFmpeg/Deno 检测、依赖预加载、
    #    yt-dlp 报错）全部落到日志文件。打包成无控制台的 .app/exe 后，
    #    print() 会丢失，文件日志是终端用户唯一能回传的排查依据。
    #    configure_logging 幂等，_run_server 里再次调用不会重复挂 handler。 ──
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

    # 启动器先持锁，后端 startup 在同一进程中登记第二个 owner；连续双击时
    # 第二个进程在触碰数据库、端口和模型目录前就退出。
    try:
        from single_instance import acquire_instance_lock
        from task_store import TEMP_DIR
        acquire_instance_lock(TEMP_DIR, owner="launcher")
    except RuntimeError as e:
        _report(str(e), logging.WARNING)
        return

    global PORT, _listen_socket
    _listen_socket = _create_listen_socket()
    PORT = int(_listen_socket.getsockname()[1])
    url = f"http://{HOST}:{PORT}"
    try:
        from single_instance import update_instance_lock_metadata
        update_instance_lock_metadata("launcher", port=PORT, url=url)
    except Exception:
        pass
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

    _start_runtime_preparation()

    # ── 退出清理：覆盖正常退出(atexit)与系统信号(SIGINT/SIGTERM)两条路径，
    #    确保无论如何关闭，进行中的任务及其子进程(ffmpeg 等)都被回收。 ──
    atexit.register(_shutdown_cleanup)
    for _sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(_sig, _signal_handler)
        except (ValueError, OSError):
            pass  # 非主线程或平台不支持时忽略

    # 启动后端服务线程
    _start_server_thread()

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

        startup_api = _StartupApi()

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
  .actions {{ display: none; gap: 10px; margin-top: 8px; }}
  .actions.visible {{ display: flex; }}
  button {{
    appearance: none; border: 1px solid var(--border-light); border-radius: 8px;
    background: var(--surface-2); color: var(--text); padding: 8px 14px;
    font: inherit; cursor: pointer;
  }}
  button.primary {{ background: var(--accent); border-color: var(--accent); color: white; }}
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
      <div class="actions" id="actions">
        <button class="primary" onclick="retryStartup()">重试</button>
        <button onclick="openLogs()">打开日志目录</button>
      </div>
    </section>
  </main>
  <script>
    var appUrl = "{url}";
    var attempts = 0;
    function inspectFailure() {{
      if (!window.pywebview || !window.pywebview.api) return;
      window.pywebview.api.state().then(function(state) {{
        if (!state.failed) return;
        document.getElementById('status').textContent = '启动失败，请重试或打开日志目录。';
        document.getElementById('actions').classList.add('visible');
      }});
    }}
    function retryStartup() {{
      document.getElementById('status').textContent = '正在重试…';
      document.getElementById('actions').classList.remove('visible');
      attempts = 0;
      window.pywebview.api.retry().then(function(result) {{
        appUrl = result.url;
        setTimeout(check, 300);
      }});
    }}
    function openLogs() {{ window.pywebview.api.open_logs(); }}
    function check() {{
      attempts++;
      fetch(appUrl, {{ mode: 'no-cors' }})
        .then(function() {{ window.location.href = appUrl; }})
        .catch(function() {{
          if (attempts > 15) document.getElementById('status').textContent = '正在初始化，请稍候…';
          inspectFailure();
          if (attempts < 600) setTimeout(check, 500);
        }});
    }}
    check();
  </script>
</body>
</html>"""

        window = webview.create_window(
            title="MediaBrief",
            html=loading_html,
            width=1200,
            height=800,
            min_size=(800, 600),
            text_select=True,
            confirm_close=True,
            localization=quit_localization(_ui_lang),
            js_api=startup_api,
        )
        startup_api.bind_window(window)
        window.events.closing += lambda: _prepare_quit_dialog(window)
        # 窗口一关就清后台，不等 start() 回到主线程。
        window.events.closed += _shutdown_cleanup
        webview.start(debug=False, localization=quit_localization(_ui_lang))
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
