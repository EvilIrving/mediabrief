# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — AI Transcriber 桌面应用

打包输出：macOS .app 或 Windows/Linux 可执行目录
启动入口：start.py（uvicorn 后台线程 + pywebview 桌面窗口）
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

# ── 路径常量 ──
ROOT = Path(SPECPATH).parent  # spec 文件在 pyinstaller/ 下，项目根往上一层
STATIC_DIR = ROOT / "static"
BACKEND_DIR = ROOT / "backend"

# ── 收集静态文件 ──
static_datas = []
for f in STATIC_DIR.rglob("*"):
    if f.is_file():
        dest = str(f.parent.relative_to(ROOT))
        static_datas.append((str(f), dest))

# ── 数据文件列表 ──
# 模型/API 配置由前端设置页管理，桌面安装包不携带环境变量模板。
added_files = static_datas

# yt-dlp 的 YouTube EJS 解签脚本是包内 .js 数据文件，PyInstaller 不会通过
# hiddenimports 自动收集。缺失时发布包在无开发环境的机器上可能列不到可用格式。
added_files += collect_data_files("yt_dlp")

# faster-whisper 自带的 VAD 模型等数据文件（assets/silero_vad_v6.onnx）也是包内
# 非 .py 数据文件，PyInstaller 默认不收集。缺失会导致转录时报
# ONNXRuntimeError NO_SUCHFILE: silero_vad_v6.onnx File doesn't exist。
added_files += collect_data_files("faster_whisper")

# ── 内嵌 base Whisper 模型 ──
# 构建时把 base 模型下载到 pyinstaller/bundled-models（HF cache 布局），
# 打进 bundle 的 ``whisper-models/`` 目录；首次启动由 start.py 复制到
# 可写数据目录，保证 base 离线即用。其余尺寸经前端「下载」按需获取。
BUNDLED_MODELS_DIR = ROOT / "pyinstaller" / "bundled-models"
try:
    from faster_whisper.utils import download_model as _dl_model
    BUNDLED_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    _dl_model("Systran/faster-whisper-base", cache_dir=str(BUNDLED_MODELS_DIR))
    for _mf in BUNDLED_MODELS_DIR.rglob("*"):
        if _mf.is_file():
            _dest = "whisper-models/" + str(_mf.parent.relative_to(BUNDLED_MODELS_DIR))
            added_files.append((str(_mf), _dest))
except Exception as _e:  # noqa: BLE001
    print(f"[spec] 警告：内嵌 base 模型失败，将依赖首次联网下载: {_e}")

# ── 隐藏导入（PyInstaller 可能遗漏的） ──
hidden_imports = [
    # ── 后端应用（start.py 通过 uvicorn 运行时加载，静态分析看不到） ──
    "main",
    "pipeline",
    "services",
    "task_store",
    "video_processor",
    "transcriber",
    "summarizer",
    "translator",
    "rss_reader",
    "exporter",
    "llm_sanitize",
    # routers 包（__init__.py 会自动拉取子模块）
    "routers",
    # ── uvicorn workers ──
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # ── faster-whisper / ctranslate2 ──
    "ctranslate2",
    "ctranslate2.converters",
    "ctranslate2.models",
    "ctranslate2.specs",
    "faster_whisper",
    "faster_whisper.vad",
    "faster_whisper.tokenizer",
    # ── 导出库 ──
    "markdown",
    "bs4",
    "docx",
    "fpdf",
    "reportlab",
    # ── yt-dlp extras ──
    "yt_dlp.extractor",
    "yt_dlp.postprocessor",
    # ── SSL 证书 ──
    "certifi",
    # ── trafilatura ──
    "trafilatura",
]

# ── 收集 certifi CA bundle ──
try:
    import certifi as _certifi
    _certifi_pem = _certifi.where()
    added_files.append((_certifi_pem, "certifi"))
except ImportError:
    pass

# ── 收集 ctranslate2 原生库（.dylib 在隐藏目录 .dylibs/ 下，PyInstaller 可能遗漏） ──
binaries = []
import glob as _glob
_ct2_dir = None
try:
    import ctranslate2
    _ct2_dir = Path(ctranslate2.__file__).parent
except ImportError:
    pass
if _ct2_dir and _ct2_dir.exists():
    _dylibs_dir = _ct2_dir / ".dylibs"
    if _dylibs_dir.exists():
        for _f in _dylibs_dir.iterdir():
            if _f.is_file():
                binaries.append((str(_f), "."))

# ── macOS 专用配置 ──
if sys.platform == "darwin":
    # .app bundle 信息
    BUNDLE_ID = "com.ai-transcriber.desktop"
    BUNDLE_NAME = "AI Transcriber"
    BUNDLE_ICON = str(ROOT / "pyinstaller" / "icon.icns")
    info_plist = {
        "CFBundleName": BUNDLE_NAME,
        "CFBundleDisplayName": BUNDLE_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSBackgroundOnly": False,
    }
else:
    BUNDLE_NAME = "AI Transcriber"
    info_plist = {}
    BUNDLE_ICON = None  # .icns is macOS-only

# ── Analysis ──
a = Analysis(
    [str(ROOT / "start.py")],
    pathex=[str(ROOT), str(BACKEND_DIR)],
    binaries=binaries,
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "pandas",
        "numpy.testing",
        "scipy",
        "PIL",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ── EXE / COLLECT / BUNDLE ──
# 全平台统一使用 one-dir 模式：启动快（无需每次解压），
# 且 macOS 上每个嵌套 .dylib/.so 都可被单独签名（公证所需）。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ai-transcriber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    # 仅支持 Apple Silicon (arm64)，不支持 Intel Mac。
    # ctranslate2 等依赖只有单架构 wheel，无法 universal2，须在 arm64 机器上构建。
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=BUNDLE_NAME,
)

if sys.platform == "darwin":
    # 原生 .app bundle：COLLECT 产物 + .icns + Info.plist
    app = BUNDLE(
        coll,
        name=f"{BUNDLE_NAME}.app",
        icon=BUNDLE_ICON,
        bundle_identifier=BUNDLE_ID,
        info_plist=info_plist,
    )
