# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — MediaBrief 桌面应用

打包输出：macOS .app
启动入口：start.py（uvicorn 后台线程 + pywebview 桌面窗口）
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# ── 路径常量 ──
ROOT = Path(SPECPATH).parent  # spec 文件在 pyinstaller/ 下，项目根往上一层
STATIC_DIR = ROOT / "static"
BACKEND_DIR = ROOT / "backend"
VERSION_FILE = ROOT / "VERSION"
APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
if not APP_VERSION:
    raise ValueError("VERSION 不能为空")

# ── 收集静态文件 ──
static_datas = []
for f in STATIC_DIR.rglob("*"):
    if f.is_file():
        dest = str(f.parent.relative_to(ROOT))
        static_datas.append((str(f), dest))

# ── 数据文件列表 ──
# 模型/API 配置由前端设置页管理，桌面安装包不携带环境变量模板。
added_files = static_datas + [(str(VERSION_FILE), ".")]
_release_config = Path(
    os.environ.get("MEDIABRIEF_RELEASE_CONFIG_PATH", ROOT / "build" / "release-config.json")
)
if not _release_config.is_file():
    raise FileNotFoundError(
        "缺少 build/release-config.json；正式构建必须通过 scripts/build_macos.sh 注入 AI 配置"
    )
added_files.append((str(_release_config), "."))

# yt-dlp 的 YouTube EJS 解签脚本是包内 .js 数据文件，PyInstaller 不会通过
# hiddenimports 自动收集。缺失时发布包在无开发环境的机器上可能列不到可用格式。
added_files += collect_data_files("yt_dlp")

# mlx_whisper 自带的资产（assets/mel_filters.npz、*.tiktoken 分词表）是包内非 .py
# 数据文件，PyInstaller 默认不收集；缺失会导致转录时无法构建 mel 频谱 / 分词。
added_files += collect_data_files("mlx_whisper")
try:
    import mlx as _mlx_pkg
    _reprlib_fix = Path(_mlx_pkg.__path__[0]) / "_reprlib_fix.py"
    if _reprlib_fix.is_file():
        added_files.append((str(_reprlib_fix), "mlx"))
except Exception as _e:  # noqa: BLE001
    print(f"[spec] 警告：未能收集 mlx._reprlib_fix: {_e}")

# mlx 的数据文件：关键是 Metal 内核 ``mlx/lib/mlx.metallib``——MLX 新版把 Metal 后端
# 拆为独立发行包(mlx-metal)，仅加 hidden import 不够，必须显式收 metallib + dylib，
# 否则打包后 GPU 不可用 / 启动即崩。dylib 由下方 collect_dynamic_libs 收集。
added_files += collect_data_files("mlx")

# onnxruntime 数据/原生库（Silero VAD 推理依赖）。
added_files += collect_data_files("onnxruntime")

# vendored 的 Silero VAD 模型：放到 bundle 的 ``assets/``，与 silero_vad._resolve_asset_path
# 的探测路径(_MEIPASS/assets)一致。缺失则 VAD 不可用（会回退整块转录，但失去抗幻觉）。
_vad_onnx = BACKEND_DIR / "assets" / "silero_vad_v6.onnx"
if _vad_onnx.is_file():
    added_files.append((str(_vad_onnx), "assets"))
else:
    print(f"[spec] 警告：未找到 VAD 模型 {_vad_onnx}，打包后 Silero VAD 将不可用")

# ── 内嵌 base Whisper 模型（mlx-community/whisper-base-mlx）──
# 构建时把 base 模型下载到 pyinstaller/bundled-models/base，打进 bundle 的
# ``whisper-models/base/`` 目录；首次启动由 start.py 复制到可写数据目录，保证
# base 离线即用（is_downloaded 按 config.json + weights.npz 判定），只承担
# 默认大模型确实无法准备时的应急兜底；large-v3-turbo 在首启后台自动准备。
BUNDLED_MODELS_DIR = ROOT / "pyinstaller" / "bundled-models"
_base_dir = BUNDLED_MODELS_DIR / "base"
_base_dir.mkdir(parents=True, exist_ok=True)


def _bundled_base_ready(directory: Path) -> bool:
    return (directory / "config.json").is_file() and (
        (directory / "weights.npz").is_file() or (directory / "weights.safetensors").is_file()
    )


def _download_bundled_base_from_modelscope(directory: Path) -> None:
    import httpx

    repo = "mlx-community/whisper-base-mlx"
    timeout = httpx.Timeout(10.0, read=30.0)
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        for name in ("config.json", "weights.npz"):
            url = f"https://www.modelscope.cn/models/{repo}/resolve/master/{name}"
            dest = directory / name
            part = dest.with_name(dest.name + ".part")
            existing = part.stat().st_size if part.is_file() else 0
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                if existing and resp.status_code == 200:
                    existing = 0
                    part.unlink(missing_ok=True)
                mode = "ab" if existing and resp.status_code == 206 else "wb"
                with part.open(mode) as fh:
                    for chunk in resp.iter_bytes(256 * 1024):
                        if chunk:
                            fh.write(chunk)
            part.replace(dest)


if not _bundled_base_ready(_base_dir):
    try:
        from huggingface_hub import snapshot_download as _snap

        _snap(
            repo_id="mlx-community/whisper-base-mlx",
            local_dir=str(_base_dir),
            allow_patterns=["config.json", "weights.npz", "*.json"],
        )
    except Exception as _hf_err:
        try:
            _download_bundled_base_from_modelscope(_base_dir)
        except Exception as _ms_err:
            raise RuntimeError(
                f"内嵌 base 应急模型失败，拒绝生成不完整发行包: hub={_hf_err}; modelscope={_ms_err}"
            ) from _ms_err

if not _bundled_base_ready(_base_dir):
    raise RuntimeError("内嵌 base 应急模型失败，拒绝生成不完整发行包: 缺少 config/weights")

for _mf in _base_dir.rglob("*"):
    if _mf.is_file() and not _mf.name.endswith(".part"):
        _rel = _mf.parent.relative_to(_base_dir)
        _dest = ("whisper-models/base" if str(_rel) == "." else f"whisper-models/base/{_rel}")
        added_files.append((str(_mf), _dest))

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
    # ── mlx / mlx-whisper（Apple Silicon ASR）──
    # 只列推理路径用到的子模块；不列 mlx_whisper.torch_whisper（仅权重转换用，
    # 会拖入 torch ~440MB），torch 已在 excludes 中排除。
    "mlx",
    "mlx.core",
    "mlx.nn",
    "mlx.utils",
    # core.so 初始化会 import 这个纯 Python 模块；漏收时打包版只报
    # "Encountered an error while initializing the extension"。
    "mlx._reprlib_fix",
    "mlx_whisper",
    "mlx_whisper.audio",
    "mlx_whisper.decoding",
    "mlx_whisper.load_models",
    "mlx_whisper.transcribe",
    "mlx_whisper.whisper",
    "mlx_whisper.tokenizer",
    "mlx_whisper.timing",
    "huggingface_hub",
    # ── Silero 前置 VAD ──
    "onnxruntime",
    "silero_vad",
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

# ── 收集 mlx 原生库（libmlx.dylib / libjaccl.dylib 等，在 mlx/lib/ 下） ──
# collect_dynamic_libs 抓 .dylib/.so；metallib(Metal 内核)不是动态库，已由上面
# collect_data_files("mlx") 收进。两者缺一，打包后都跑不起 Metal 后端。
binaries = []
binaries += collect_dynamic_libs("mlx")
binaries += collect_dynamic_libs("mlx_whisper")
# onnxruntime 的原生库（capi/*.dylib），Silero VAD 推理所需。
binaries += collect_dynamic_libs("onnxruntime")

# 兜底：显式把 mlx/lib 下的 dylib + metallib 收齐，防 collect_* 在某些版本漏收。
try:
    import mlx
    _mlx_lib = Path(mlx.__path__[0]) / "lib"
    if _mlx_lib.is_dir():
        for _f in _mlx_lib.iterdir():
            if _f.suffix == ".dylib":
                binaries.append((str(_f), "mlx/lib"))
            elif _f.suffix == ".metallib":
                added_files.append((str(_f), "mlx/lib"))
except Exception as _e:  # noqa: BLE001
    print(f"[spec] 警告：mlx 原生库兜底收集失败: {_e}")

# ── macOS 专用配置 ──
if sys.platform == "darwin":
    # .app bundle 信息
    BUNDLE_ID = "com.mediabrief.desktop"
    BUNDLE_NAME = "MediaBrief"
    BUNDLE_ICON = str(ROOT / "pyinstaller" / "icon.icns")
    info_plist = {
        "CFBundleName": BUNDLE_NAME,
        "CFBundleDisplayName": BUNDLE_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": APP_VERSION,
        "CFBundleShortVersionString": APP_VERSION,
        "NSHighResolutionCapable": True,
        "LSBackgroundOnly": False,
        "LSMultipleInstancesProhibited": True,
    }
else:
    BUNDLE_NAME = "MediaBrief"
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
        # torch 仅被 mlx_whisper.torch_whisper（权重转换）引用，推理路径用不到；
        # 排除以省下 ~440MB 安装体积。
        "torch",
        "torchvision",
        "torchaudio",
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
    name="mediabrief",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    # 仅支持 Apple Silicon (arm64)，不支持 Intel Mac。
    # mlx / mlx-metal 是 Apple Silicon 专用（Metal 后端），无 Intel/universal2 wheel，
    # 必须在 arm64 机器上构建。
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
