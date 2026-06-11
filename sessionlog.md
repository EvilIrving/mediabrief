## 修复启动报错 + 前端布局调整 · 2026-06-12 · pi

### 修复：uvicorn 启动失败

**现象**：`uvicorn main:app` 启动时 traceback 指向 `routers/export.py` line 10，报 `ModuleNotFoundError`。因 traceback 被截断，未直接显示根因。

**根因**：`exporter.py` 依赖的 5 个包 (`beautifulsoup4` / `python-docx` / `fpdf2` / `markdown` / `reportlab`) 在 `requirements.txt` 中有声明但 venv 中未安装。`from bs4 import BeautifulSoup` 失败，导致整个 import 链中断。

**修复**：`pip install beautifulsoup4 python-docx fpdf2 markdown reportlab` 到 venv。

### 前端：page-header-wrap

将 `static/index.html` 中 Transcribe 页面的 `page-topbar`、`videoForm`、`upload-section` 三个区域包入 `<div class="page-header-wrap">`，同时把 `errorBanner` 移到 wrapper 外部（紧随其后）。
