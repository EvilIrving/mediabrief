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
