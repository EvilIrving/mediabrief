<div align="center">

# AI Transcriber

[English](README.md) | 中文 | [日本語](README_JA.md) | [한국어](README_KO.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/EvilIrving/ai-transcriber)](https://github.com/EvilIrving/ai-transcriber/stargazers)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/)

粘贴 YouTube、Bilibili、抖音、Apple Podcasts 等 30+ 平台的链接，或者拖入本地音视频文件、纯文本。有字幕时直接提取，没有时走 Whisper 转录，最后由 LLM 做文本清洗和摘要。RSS 自动化（支持 YouTube 频道）也已内置，适合处理播客等周期性内容。

<video src="docs/img/demo.mp4" controls muted autoplay loop width="100%" style="max-width:720px"></video>

![首页 — 粘贴链接，摘要实时流式生成](docs/img/home.png)
![RSS — 订阅 Feed 与 YouTube 频道](docs/img/rss.png)
![历史 — 所有摘要自动保存、可搜索](docs/img/history.png)

</div>

## ✨ 功能特性

- **多平台**：YouTube、Bilibili、抖音、Apple Podcasts、SoundCloud 及 30+ 平台
- **本地文件**：拖入 `.mp3`、`.mp4`、`.m4a`、`.wav`、`.webm`、`.mkv`、`.ogg`、`.flac`，或 `.txt`（跳过转录直接摘要）。音视频经 FFmpeg 转码后由 Whisper 处理
- **字幕优先**：有原生字幕时直接提取，不用下载音频。没有字幕才走 Whisper，大多数 YouTube 视频都能命中这个快速路径
- **Whisper 兜底**：无字幕时用 Faster-Whisper（CTranslate2）做语音转文字
- **LLM 文本清洗**：错别字修正、句子补全和分段
- **多语言摘要**：10+ 种语言，源语言与目标语言不同时自动翻译
- **摘要优先交付**：摘要与文本优化并行处理，可以先看摘要，全文同步在后台继续清洗
- **两步摘要**（可选）：LLM 先生成定制的摘要提示词，再据此生成最终摘要。长内容效果更好
- **无需重新处理的重试**：用已保存的原始文本重新生成摘要和优化后的文稿，不用重新下载或转录
- **多语言界面**：English、中文、日本語、한국어
- **浅色 / 深色主题**：一键切换
- **自带模型**：在页面里配任意 OpenAI 兼容接口（OpenAI、OpenRouter、本地 LLM 等）。输入 API 地址和 Key，点 Fetch 拉取模型列表，选一个即可
- **统一任务队列**：粘贴的链接、上传的文件、下载、RSS 条目——所有任务都汇入首页的同一个队列，逐个执行。可实时查看进度、打开已完成结果、随时取消；同一个任务也可以重复排队
- **RSS 订阅**：订阅 RSS 或 YouTube 频道，刷新条目，一键摘要或下载
- **媒体下载**：检测可用格式，下载视频、音频或字幕
- **多格式导出**：MD、TXT、DOCX、PDF
- **服务端历史**：所有摘要自动存入后端 SQLite。在 History 标签页搜索、按来源过滤、管理历史
- **移动端适配**：响应式布局

## 🚀 快速开始

### 环境要求

- Python 3.8+
- FFmpeg（链接下载与本地上传音视频转码均需）
- 任意OpenAI兼容服务商的API Key（OpenAI、OpenRouter等）—— 直接在页面UI中配置，无需服务器环境变量

### 安装方法


#### 方法一：自动安装

```bash
# 克隆项目
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber

# 运行安装脚本
chmod +x install.sh
./install.sh
```

#### 方法二：Docker部署

```bash
# 克隆项目
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber

# 使用Docker Compose（最简单）
docker-compose up -d

# 或者直接使用Docker
docker build -t ai-video-transcriber .
docker run -p 8000:8000 ai-video-transcriber
```

镜像基于 **Python 3.12**（Debian Bookworm），构建时会先升级 `pip` / `setuptools` / `wheel`，再按 `requirements.txt` 安装，与本地在新版 Python 下创建虚拟环境后 `pip install -r requirements.txt` 的解析方式一致。

#### 方法三：手动安装

1. **安装Python依赖**（建议使用虚拟环境）
```bash
# 创建并启用虚拟环境（macOS推荐，避免 PEP 668 系统限制）
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2. **安装FFmpeg**
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# CentOS/RHEL
sudo yum install ffmpeg
```

### 启动服务

```bash
# 激活虚拟环境
source venv/bin/activate

# 启动服务（浏览器模式）
python3 start.py --no-window

# 或桌面模式（需安装 pywebview）
python3 start.py
```

服务启动后，打开浏览器访问 `http://localhost:8000`

> **桌面模式**：安装了 `pywebview` 后，`python3 start.py` 会打开原生桌面窗口。用 `--no-window` 或 `--server` 可强制浏览器模式。

> 界面由 `static/dist/` 中预构建的 React 产物提供（已随仓库发布），**运行**应用无需 Node.js。

### 前端开发

Web 界面是位于 `frontend/` 的 React + TypeScript SPA。仅在**修改**界面时才需要：

```bash
cd frontend
pnpm install

# 生产构建 → 输出到 static/dist/（随后运行 start.py）
pnpm build

# 或带 HMR 的开发服务器（将 /api 代理到 :8000 的 FastAPI）
pnpm dev
```

在 macOS 上用独立的 Chrome App 窗口打开开发界面：

```bash
open -na "Google Chrome" --args --app="http://localhost:5173"
```

## 📖 使用指南

1. **选择输入方式：链接或本地文件**
   - **视频/播客链接**：在输入框粘贴 YouTube、Bilibili 等支持的链接
   - **本地上传**：将文件拖到虚线框内，或点击选择文件。点击同一 **Transcribe** 按钮开始处理；上传与链接共用 `POST /api/process-video`（multipart 带 `file` 字段），便于反向代理只放行该路径时仍可使用上传
2. **选择摘要语言**: 在输入框旁的下拉菜单中选择输出语言
3. **（可选）配置AI模型**: 点击 **AI Settings** 展开配置面板
   - 填写 **API Base URL**（如 `https://openrouter.ai/api/v1`）和 **API Key**
   - 点击 **Fetch** 自动拉取该服务商的可用模型列表
   - 选择你想用的模型
4. **开始处理**: 点击 **Transcribe** 按钮。**链接任务**下进度条会显示当前模式：
   - **⚡ Subtitle**（绿色）——检测到原生字幕，秒级提取完成
   - **🎙 Whisper**（橙色）——无字幕，下载音频后转录
   **本地上传**时：音视频会先经 FFmpeg 转码再由 Whisper 转录；纯 **`.txt`** 文件不下载、不跑 Whisper，直接进入文本优化与摘要（语言不一致时同样会翻译）。
5. **查看结果**: 查看优化后的转录文本和AI摘要
   - 若转录语言 ≠ 所选摘要语言，会自动显示 **翻译** 标签页
6. **查看与管理历史**: 打开 **历史** 标签页，浏览后端 SQLite 中的摘要，按标题/内容/来源搜索和过滤，展开查看或删除记录。
7. **RSS 任务**: 打开 **RSS** 标签页，订阅 Feed 或粘贴 YouTube 频道链接、刷新条目，并对单条内容执行摘要或下载。入队后任务统一在 **转录** 标签页的任务队列里执行，可在那里查看进度并取消——RSS 页面本身只负责入队。
8. **下载媒体**: 打开 **下载** 标签页，检测可用的视频、音频、字幕格式，并下载所需文件。
9. **导出结果**：点击导出按钮，将转录、翻译或摘要保存为 Markdown、TXT、DOCX 或 PDF

## 🛠️ 技术架构

### 后端技术栈
- **FastAPI** — 异步 Web 框架，含 SSE 流式推送；按域拆分路由（core / transcribe / downloads / rss）
- **yt-dlp** — 视频/音频/字幕提取，支持 1800+ 站点；内置 JS 挑战求解器应对 YouTube 反爬
- **FFmpeg** — 音频转码（单声道 16kHz，供 Whisper 使用）
- **Faster-Whisper** — CTranslate2 加速的语音转文字
- **OpenAI SDK** — 摘要、文本优化、翻译
- **trafilatura** — 网页正文提取（RSS 条目仅有链接时回退抓取）
- **aiofiles** — 异步文件读写

### 前端技术栈
- **React + TypeScript** — 组件化 SPA，客户端页面路由（React Router，`HashRouter`）
- **Vite** — 构建工具；产物输出到 `static/dist/`，由 FastAPI 提供
- **Tailwind CSS v4** — 在原有 oklch 设计变量之上叠加的工具类样式（亮/暗双主题）
- **Marked** — 客户端 Markdown 渲染
- **内联 SVG 图标** — Lucide 符号雪碧图（无图标字体依赖）


### 项目结构
```
ai-transcriber/
├── backend/                     # 后端代码
│   ├── main.py                 # FastAPI 应用装配、中间件与路由注册
│   ├── services.py             # 共享单例（处理器、上传配置）
│   ├── pipeline.py             # 编排层：转录后管线、任务执行器
│   ├── task_store.py           # 任务状态机、阶段权重、SSE 广播
│   ├── video_processor.py      # yt-dlp 封装：下载、格式检测、字幕提取
│   ├── platforms/              # 各平台下载适配器（YouTube、Bilibili 等）
│   ├── feeds/                  # 各平台订阅源适配器（YouTube 频道 → RSS）
│   ├── transcriber.py          # Faster-Whisper 转录
│   ├── summarizer.py           # LLM 摘要生成（单步 / 两步）
│   ├── translator.py           # LLM 翻译（含语言检测）
│   ├── exporter.py             # 多格式导出引擎（MD / TXT / DOCX / PDF）
│   ├── llm_sanitize.py         # LLM 输出后处理（去除套话等）
│   ├── db.py                   # SQLite 数据库层（任务、历史、RSS 订阅）
│   ├── rss_reader.py           # RSS/Atom 解析与 SQLite 持久化
│   └── routers/
│       ├── __init__.py
│       ├── core.py             # 静态页面、健康检查、模型列表代理
│       ├── transcribe.py       # 链接/上传任务、状态、SSE、下载、重试
│       ├── downloads.py        # 视频/音频/字幕下载端点
│       ├── export.py           # 导出转录/摘要/翻译为 MD / TXT / DOCX / PDF
│       └── rss.py              # RSS 订阅、条目列表、任务创建
├── frontend/                   # React + TypeScript SPA（源码）
│   ├── src/
│   │   ├── main.tsx            # 入口
│   │   ├── App.tsx             # Providers + HashRouter + 页面路由
│   │   ├── index.css          # 设计变量 + 移植的组件样式 + Tailwind
│   │   ├── lib/               # api.ts、types.ts、markdown.ts
│   │   ├── context/          # Theme、Settings、TaskHandoff 等 Provider
│   │   ├── i18n/             # UI 语言字典与 Provider
│   │   ├── components/       # Navbar、Footer、IconSprite、ErrorBanner、Markdown
│   │   └── features/         # transcribe / download / rss / history 页面
│   ├── vite.config.ts         # base=/static/dist/，outDir=../static/dist，/api 代理
│   └── package.json
├── static/                     # 由 FastAPI 提供
│   ├── dist/                   # 构建后的 SPA（pnpm build 产物，随仓库发布）
│   ├── icon_dark.svg           # 应用图标
│   └── index.html              # 旧版纯 JS 界面（仅作回退）
├── scripts/
│   ├── build_macos.sh          # macOS .app 打包脚本
│   ├── build_windows.ps1       # Windows .exe 打包脚本
│   └── sign_and_package.sh     # macOS 签名、公证、DMG 打包
├── pyinstaller/
│   └── ai_transcriber.spec     # PyInstaller 打包配置
├── temp/                       # SQLite 数据库 + 临时文件（转录、摘要、下载）
├── Docker相关文件              # Docker 部署
│   ├── Dockerfile              # Docker 镜像配置
│   ├── docker-compose.yml      # Docker Compose 配置
│   └── .dockerignore           # Docker 忽略规则
├── requirements.txt            # Python 依赖
├── install.sh                  # 一键安装脚本（macOS/Linux）
├── install.ps1                 # 一键安装脚本（Windows PowerShell）
├── install.bat                 # 一键安装脚本（Windows CMD）
├── start.py                    # 启动入口（uvicorn 服务 + pywebview 桌面窗口）
├── start.bat                   # Windows 快捷启动
├── podcast_rss_feeds.md        # 精选播客 RSS 合集
├── recommended_rss_feeds.json  # 预构建 RSS 导入模板
└── README_ZH.md                # 本文件
```

## ⚙️ 配置选项

### 应用内设置

API Base URL、API Key、模型、摘要语言和双步摘要开关都在页面 **AI Settings** 面板中配置。后端不再读取 `.env` 或环境变量作为模型/API 配置 fallback。

### Whisper模型大小选项

| 模型 | 参数量 | 多语言 | 速度 | 内存占用 |
|------|--------|--------|------|----------|
| base | 74 M | ✓ | 快 | ~150 MB |
| small | 244 M | ✓ | 中 | ~750 MB |
| medium | 769 M | ✓ | 慢 | ~1.5 GB |
| **large-v3-turbo**（默认） | 809 M | ✓ | 快 | ~1.6 GB |
| large-v3 | 1550 M | ✓ | 很慢 | ~3 GB |

**默认模型为 `large-v3-turbo`**——在 CPU 上对四种界面语言（含中日韩）有最优的速度/精度/内存平衡，首次使用时自动下载；轻量的 `base` 模型随包内嵌作为离线回退，在默认模型后台下载完成前使用。yt-dlp 也会通过节流的每周后台自更新保持最新，避免各平台解析器随时间失效。

## 🔧 常见问题

### Q: 为什么摘要比转录先出来？
A: 管线会并行生成摘要与优化转录文本。摘要只需要原始文本的轻度清理版本，因此更快完成；完整转录在后台继续优化。

### Q: 可以换模型或语言而不重新处理整个视频吗？
A: 可以。点击 **Retry** 按钮仅重新运行优化 + 摘要步骤，基于已保存的原始转录——无需重新下载或转录。

### Q: 支持哪些视频平台？
A: 支持所有yt-dlp支持的平台，包括但不限于：YouTube、抖音、Bilibili、优酷、爱奇艺、腾讯视频等。

### Q: 本地上传支持哪些格式？大小有限制吗？
A: 允许的扩展名包括 `.txt`、`.mp3`、`.mp4`、`.m4a`、`.wav`、`.webm`、`.mkv`、`.ogg`、`.flac`。默认单文件上限 **200 MB**。

### Q: AI优化功能不可用怎么办？
A: AI功能需要任意OpenAI兼容服务商的API Key（OpenAI、OpenRouter等）。请直接在页面 **AI Settings** 面板中填写并选择模型，无需重启服务。

### Q: 出现 500 报错/白屏，是代码问题吗？
A: 多数情况下是环境配置问题，请按以下清单排查：
- 是否已激活虚拟环境：`source venv/bin/activate`
- 依赖是否安装在虚拟环境中：`pip install -r requirements.txt`
- 是否在页面 **AI Settings** 面板中配置了 API Base URL、API Key 和模型
- 是否已安装 FFmpeg：macOS `brew install ffmpeg` / Debian/Ubuntu `sudo apt install ffmpeg`
- 8000 端口是否被占用；如被占用请关闭旧进程或更换端口

### Q: 如何处理长视频？
A: 系统可以处理任意长度的视频，但处理时间会相应增加。建议对于超长视频使用较小的Whisper模型。

### Q: 如何使用Docker部署？
A: Docker提供了最简单的部署方式：

**前置条件：**
- 从 https://www.docker.com/products/docker-desktop/ 安装Docker Desktop
- 确保Docker服务正在运行

**快速开始：**
```bash
# 克隆项目
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber

# 使用Docker Compose启动（推荐）
docker-compose up -d

# 或手动构建运行
docker build -t ai-video-transcriber .
docker run -p 8000:8000 ai-video-transcriber
```

**常见Docker问题：**
- **端口冲突**：如果8000端口被占用，可改用 `-p 8001:8000`
- **权限拒绝**：确保Docker Desktop正在运行且有适当权限
- **构建失败**：检查磁盘空间（需要约2GB空闲空间）和网络连接
- **容器无法启动**：通过 `docker logs <容器ID>` 查看具体错误日志

**Docker常用命令：**
```bash
# 查看运行中的容器
docker ps

# 检查容器日志
docker logs ai-video-transcriber-ai-video-transcriber-1

# 停止服务
docker-compose down

# 修改后重新构建
docker-compose build --no-cache
```

### Q: 内存需求是多少？
A: 内存使用量根据部署方式和工作负载而有所不同：

**Docker部署：**
- **基础内存**：空闲容器约128MB
- **处理过程中**：根据视频长度和Whisper模型，需要500MB - 2GB
- **Docker镜像大小**：约1.6GB磁盘空间
- **推荐配置**：4GB+内存以确保流畅运行

**传统部署：**
- **基础内存**：FastAPI服务器约50-100MB
- **Whisper模型内存占用**：
  - `base`：约150MB（内嵌离线回退）
  - `small`：约750MB
  - `medium`：约1.5GB
  - `large-v3-turbo`：约1.6GB（默认）
  - `large-v3`：约3GB
- **峰值使用**：基础 + 模型 + 视频处理（额外约500MB）

**内存优化建议：**
```bash
# 使用更小的Whisper模型减少内存占用

# Docker部署时可限制容器内存
docker run -m 1g -p 8000:8000 ai-video-transcriber

# 监控内存使用情况
docker stats ai-video-transcriber-ai-video-transcriber-1
```

### Q: 开发模式下 Ctrl+C 关不掉，或重启时"Address already in use"？
A: 这是 `concurrently` + `uvicorn --reload` 的常见问题。解决方法：
- 运行 `pnpm stop` 强制杀掉 8000 和 5173 端口
- 如果 Ctrl+C 卡住，可能是 Whisper 预热线程在阻止退出 —— 用 `pnpm stop`
- 开发脚本已排除 `temp/*` 目录的文件监听，避免迁移产生的 bak 文件触发 reload 循环

### Q: YouTube下载报"Sign in to confirm you're not a bot"？
A: 这是YouTube的反爬虫验证。本项目已内置浏览器cookies自动提取功能：
- 默认自动从 **Chrome** 读取YouTube cookies（需在Chrome中登录过YouTube）
- 如需使用浏览器 cookies，请在运行环境中设置 `COOKIES_BROWSER=brave`、`COOKIES_BROWSER=edge` 等 yt-dlp 相关变量
- 或手动导出cookies.txt并配置：`COOKIES_FILE=/path/to/cookies.txt`
- 首次下载时yt-dlp会自动从GitHub下载JS挑战求解脚本（后续缓存）

### Q: YouTube下载报"Requested format is not available"？
A: 这是YouTube新版JS挑战导致的。项目已配置 Deno/Node.js 自动求解，确保系统已安装 **Deno** 或 **Node.js**（macOS: `brew install deno`）。

### Q: 网络连接错误或超时怎么办？
A: 如果在视频下载或API调用过程中遇到网络相关错误，请尝试以下解决方案：

**常见网络问题：**
- 视频下载失败，出现"无法提取"或超时错误
- API调用返回连接超时或DNS解析失败
- Docker镜像拉取失败或极其缓慢

**解决方案：**
1. **切换VPN/代理**：尝试连接到不同的VPN服务器或更换代理设置
2. **检查网络稳定性**：确保你的网络连接稳定
3. **更换网络后重试**：更改网络设置后等待30-60秒再重试
4. **使用备用端点**：如果使用自定义API端点，验证它们在网络环境下可访问
5. **Docker网络问题**：如果容器网络失败，重启Docker Desktop

**快速网络测试：**
```bash
# 测试视频平台访问
curl -I https://www.youtube.com/

# 测试API端点
curl -I https://api.deepseek.com

# 测试Docker Hub访问
docker pull hello-world
```

如果问题持续存在，尝试切换到不同的网络或VPN位置。

## 🖥️ macOS 桌面应用

```bash
# 一次性环境准备
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt pyinstaller pywebview
brew install librsvg

# 构建
bash scripts/build_macos.sh

# 运行（内嵌 base 模型；默认的 large-v3-turbo 首次启动时后台下载）
open "dist/AI Transcriber.app"

# API Key / 模型配置
# 启动后在页面 AI Settings 面板中填写并选择模型

# 签名与公证（分发用，需 Apple Developer ID）
bash scripts/sign_and_package.sh notarize
```

> **首次运行建议**：从终端启动 — `"dist/AI Transcriber.app/Contents/MacOS/ai-transcriber"`。如进程数爆炸，`pkill -9 -f ai-transcriber` 后重新构建。

## 🎯 支持的语言

### 转录
- 通过Whisper支持100+种语言
- 自动语言检测
- 主要语言具有高准确率

### 摘要生成
- 英语
- 中文（简体）
- 日语
- 韩语
- 西班牙语
- 法语
- 德语
- 葡萄牙语
- 俄语
- 阿拉伯语
- 以及更多...

## 📈 性能提示

- **硬件要求**:
  - 最低配置: 4GB内存，双核CPU
  - 推荐配置: 8GB内存，四核CPU
  - 理想配置: 16GB内存，多核CPU，SSD存储

- **处理时间预估**:

  | 视频长度 | 字幕模式 | Whisper模式 | 备注 |
  |---------|---------|------------|------|
  | 1分钟 | ≈5秒 | 30秒–1分钟 | 字幕模式无需下载音频 |
  | 5分钟 | ≈10秒 | 2–5分钟 | YouTube自动字幕触发字幕模式 |
  | 15分钟 | ≈15秒 | 5–15分钟 | 大多数YouTube视频支持字幕模式 |
  | 30分钟+ | ≈20秒 | 15–60分钟 | 纯音频/播客始终使用Whisper |

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

1. Fork项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request 

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 强大的视频下载工具
- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) - 高效的Whisper实现
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化的Python Web框架
- [OpenAI](https://openai.com/) - 智能文本处理API

## 📞 联系方式

如有问题或建议，请提交Issue。

---

## ⭐ Star History

如果您觉得这个项目有帮助，请考虑给它一个星星！
