## 修复 macOS 打包四件致命/严重缺陷 · 2026-06-13 20:04 · pi

修复了之前 review 中发现的 4 个问题：

### ① DB 路径在 frozen 时指向只读 .app bundle（P0 — 起不来）
- `db.py` 的 `DB_PATH` 改用延迟函数 `_get_db_path()`，通过延迟 import 从 `task_store.TEMP_DIR` 获取路径，避免循环依赖
- 同改 `logging_config.py` 非 frozen 分支也用 `TEMP_DIR`
- 原因：`task_store.py` 已有正确的 `_get_data_dir()`（frozen → `~/Library/Application Support`），但 `db.py` 直接 `from task_store import TEMP_DIR` 会循环依赖（task_store 先 import db）

### ② Homebrew ffmpeg 动态链接无法分发（P0 — 别人 Mac 上跑不起来）
- 结论：macOS arm64 静态 ffmpeg 目前没有公开下载源（evermeet 不做 arm64，BtbN 无 macOS，ffbinaries 只有 x86_64）
- 方案：新增 `scripts/build_ffmpeg.sh`，从 ffmpeg 7.1.1 源码编译最小化静态二进制（只启用了需要的 demuxer/decoder/encoder，3.3MB，仅链接 macOS 系统库）
- `build_macos.sh` 不再编译，改为检查缓存是否存在且无 Homebrew 依赖，否则报错提示先跑 `build_ffmpeg.sh`

### ③ 注入的 ffmpeg 未签名（P1 — 公证 reject）
- `sign_and_package.sh` 的 find 模式新增 `-name "ffmpeg"`

### ④ CORS 全开 `*` + credentials（P2 — 安全风险）
- `main.py` allow_origins 从 `["*"]` 改为白名单 4 个 origin（127.0.0.1/localhost × 8000/5173）

### 其他
- `ffmpeg_bin/ffmpeg-arm64` 已替换为静态编译版本，`otool -L` 仅系统 dylib
- 后端导入测试通过，45 routes 正常

### 修复：uvicorn 启动失败

**现象**：`uvicorn main:app` 启动时 traceback 指向 `routers/export.py` line 10，报 `ModuleNotFoundError`。因 traceback 被截断，未直接显示根因。

**根因**：`exporter.py` 依赖的 5 个包 (`beautifulsoup4` / `python-docx` / `fpdf2` / `markdown` / `reportlab`) 在 `requirements.txt` 中有声明但 venv 中未安装。`from bs4 import BeautifulSoup` 失败，导致整个 import 链中断。

**修复**：`pip install beautifulsoup4 python-docx fpdf2 markdown reportlab` 到 venv。

### 前端：page-header-wrap

将 `static/index.html` 中 Transcribe 页面的 `page-topbar`、`videoForm`、`upload-section` 三个区域包入 `<div class="page-header-wrap">`，同时把 `errorBanner` 移到 wrapper 外部（紧随其后）。

## 转录链路深度健壮性加固（打包面向小白）· 2026-06-14 · opus

针对「打包后跑在不懂技术的用户机器上、最易报错的下载/转码/转录三个环节」做深度分析，
结合 2026 年 yt-dlp / faster-whisper / PyInstaller 官方文档与社区实战，落地三块改动。
分支 `feature/transcription-chain-robustness`，前序 batch A/B/C 先归一为一个基底 commit。

### ① yt-dlp 运行时自更新（解冻打包版本）· commit 17b09e7
- **问题**：打包后 bundle 内 yt-dlp 被构建时版本永久冻结；yt-dlp 主要靠更新追赶站点
  反爬变化，数月后 YouTube 等会成片失败，冻结环境无 pip、`-U` 不可用，用户无法自救。
- **方案**：新增 `backend/yt_dlp_updater.py`——在可写数据目录维护一份 yt-dlp 纯 Python
  包并置于 `sys.path` 最前覆盖随包版本；启动节流（每周一次）后台从 PyPI 拉最新 **stable**
  的 wheel（纯 stdlib 解包，无需 pip），下次启动生效；任何失败静默回退到随包版本。
- `start.py` 在任何 `import yt_dlp` 前调 `schedule_update()`；`build_*` 打包前
  `pip install -U yt-dlp`。对用户透明、不暴露参数；「请下新安装包」留作未来应用更新功能。

### ② 默认模型 large-v3-turbo + 抗幻觉调参 · commit 5ecc923
- **2026 重评估**：Parakeet/Canary 不支持中日韩且依赖 CUDA；SenseVoice 要换运行时且
  时间戳弱。`large-v3-turbo` 为 CPU+CJK 甜点（比 large-v3 快约 8×、int8 约 1.5GB、四语
  全覆盖），引擎仍用 faster-whisper/CT2，零架构改动。
- `whisper_models`：DEFAULT_MODEL=large-v3-turbo，BUILTIN_MODEL=base 作内嵌离线回退；
  `ensure_default_model_async` 首启后台下载，`_resolve_available_size` 就绪前优雅回退 base。
- `pipeline` 默认路径走 `get_transcriber()` 每次重解析，下载完成后自动切 turbo。
- `transcriber` VAD/阈值对齐 WhisperX/Calm-Whisper：min_silence 900→500、speech_pad
  300→400、no_speech 0.7→0.6、compression_ratio 2.3→2.4，补 turbo 短/噪片段短板。

### ③ FFmpeg/FFprobe 链路加固 · commit 343d9b0
- **P0-1 ffprobe 未打包/定位**：旧实现只定位 ffmpeg，时长校验用 `ffprobe … shell=True`，
  缺 ffprobe 时静默吞异常 → 校验失效 → 损坏/截断音频被直送 Whisper。
  现 `build_ffmpeg.sh` 产出并校验 `ffprobe-arm64`，`build_macos.sh` 注入 .app，
  `start.py` 定位并导出 `AIT_FFMPEG/AIT_FFPROBE/AIT_FFMPEG_LOCATION`（Windows 早已注入）。
- **P0-2 未显式传 ffmpeg_location**：后处理仅靠 PATH，打包后（尤其 Windows）易
  FileNotFoundError。`video_processor` 模块级解析绝对路径并注入 yt-dlp `ffmpeg_location`；
  新增 `_run_media_proc`（进程组+取消令牌+库路径 *_ORIG 清理+超时），删除两处 `shell=True`，
  normalize/probe/重封装统一走它；`routers/core` 诊断页报告实际绝对路径并新增 ffprobe。
- **验证**：全部 py_compile 通过，后端 50 路由导入正常；实测生成 m4a→ffprobe 探测时长
  1.000000→normalize 产出成功；dev 模式正确回退系统 ffmpeg/ffprobe 并剔除 DYLD_LIBRARY_PATH。
- **待办**：在 arm64 构建机跑 `build_ffmpeg.sh` 实测 ffprobe 静态产出。
