#!/usr/bin/env python3
"""
AI Transcriber — 桌面应用启动入口

启动本地 API 服务后，以原生 WebView 窗口渲染前端界面，
提供完整的桌面软件体验（无需外部浏览器）。
"""

import os
import sys
import time
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

# ── SSL 证书：PyInstaller 打包后自带的 CA 证书可能过期/缺失，
#    用 certifi 提供完整的 Mozilla CA bundle ──
if getattr(sys, "frozen", False):
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass

# ── 默认环境变量 ──
os.environ.setdefault("HOST", "127.0.0.1")
os.environ.setdefault("PORT", "8000")
os.environ.setdefault("WHISPER_MODEL_SIZE", "base")
os.environ.setdefault("UPLOAD_MAX_MB", "200")


def _run_server():
    """在后台线程中运行 uvicorn 服务"""
    import traceback
    try:
        import uvicorn
        import logging

        logging.basicConfig(level=logging.INFO)

        host = os.getenv("HOST", "127.0.0.1")
        port = int(os.getenv("PORT", "8000"))

        config = uvicorn.Config(
            "main:app",
            host=host,
            port=port,
            log_level="info",
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
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    no_window = "--no-window" in sys.argv or "--server" in sys.argv

    url = f"http://{host}:{port}"
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
          if (attempts > 15) document.getElementById('status').textContent = '首次启动需下载模型，请耐心等候…';
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
