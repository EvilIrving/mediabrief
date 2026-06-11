# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — AI视频转录器 桌面应用

打包输出：macOS .app 或 Windows/Linux 可执行目录
启动入口：start.py（uvicorn 后台线程 + pywebview 桌面窗口）
"""

import sys
from pathlib import Path

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
added_files = [
    # 只打包 .env.example，不打包含密钥的 .env
    (str(ROOT / ".env.example"), "."),
] + static_datas

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
    # ── trafilatura ──
    "trafilatura",
]

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
    BUNDLE_NAME = "AI视频转录器"
    BUNDLE_ICON = None  # 需要 .icns 格式，暂无
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
    BUNDLE_NAME = "AI视频转录器"
    info_plist = {}
    BUNDLE_ICON = None

# ── Analysis ──
a = Analysis(
    [str(ROOT / "start.py")],
    pathex=[str(ROOT), str(BACKEND_DIR)],
    binaries=[],
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

# ── EXE / COLLECT ──
if sys.platform == "darwin":
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
        console=False,       # macOS GUI 模式，不显示终端
    )
    # macOS: 打包为 .app bundle
    app = BUNDLE(
        exe,
        name=f"{BUNDLE_NAME}.app",
        icon=BUNDLE_ICON,
        bundle_identifier=BUNDLE_ID,
        info_plist=info_plist,
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
else:
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
        console=True,        # Windows/Linux 保留控制台窗口（可看到日志）
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
