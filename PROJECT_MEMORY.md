# Project Memory

## 平台定位：MediaBrief 是 macOS 转录软件 · 2026-08-13 · pi

产品定位为 macOS 专属转录软件，不是“暂不支持 Windows”，而是 Windows 明确不在产品范围。已删除 `install.ps1`、`install.bat`、`start.bat`、`scripts/build_windows.ps1`；AGENTS.md / CLAUDE.md / README ×4 / ProductizationPlan.md / todo.md / .github 模板均已按 macOS-only（Apple Silicon 发行）更新。后端代码中 `sys.platform == "win32"` 的防御分支是健壮性代码，保留不动，不构成平台承诺。
## 应用内 Harness 的架构源文件 · 2026-08-13 · grok

AI Native 层的决策写在根目录 `Harness.md`。对照过 Grok Build（`python-learns/packages/grok-build`）的 loop / Tool 契约 / Dispatch，只借分层，不借编程 Agent。

本产品内置短生命周期命令 Harness，不是通用编程 Harness。同一 Tool 宿主和模型都能调：规则够用时宿主直接执行，需要判断时模型选择。换镜像、续传、定时更新不再是「只能宿主做」；它们应抽成专用 Tool，两个入口走同一实现。

这修正了同日条目「产品化与 AI Native 是同一软件的两层」里「能事先确定的事先由宿主做、不必先问模型」的切法：宿主仍可不问模型就执行，但实现不应独占，模型在诊断中也必须能按同一按钮。`ProductizationPlan.md` 里「不做 Agent Harness」拒绝的是编程 Harness 和通用平台，不是这份应用内 Harness。

## 打包版首启失败的三个发行约束 · 2026-08-13 09:23 · grok

安装后第一条 B 站链接（无字幕）会走本地下载 + Whisper。发行 FFmpeg 用 `--disable-everything`，configure 组件名是 `pcm_s16le` 不是 `s16le`；漏掉时 `-f s16le` 失败，完好 AAC 会被标成 Unusable audio。解码现已改走 wav muxer，构建脚本必须同时启用 `pcm_s16le` 和 `wav`。

`mlx.core` 初始化会 `import mlx._reprlib_fix`。这是 C 扩展拉的纯 Python 模块，PyInstaller 不会自动收；漏了只报 `Encountered an error while initializing the extension`。spec 必须 hiddenimport `mlx._reprlib_fix`。`mlx_whisper.timing` 在 import 时就要 `scipy.signal`，发行包排除完整 scipy，由 `transcriber._ensure_mlx_whisper_import_shims` 提供带 `__version__` 的桩。Hardened Runtime 需要 JIT / unsigned executable memory / disable-library-validation，但缺 `_reprlib_fix` 时加 entitlements 也救不了。

VAD 末窗常比 ffprobe 时长多几毫秒。质量复核必须裁剪时间轴，不能 `raise` 把已经得到的转录整单作废。

## 产品化与 AI Native 是同一软件的两层 · 2026-08-13 · grok

`Plan.md` 和 `ProductizationPlan.md` 不是互相替代的需求。产品层要求装上就能用，环境、模型、库由软件自己管；AI Native 层是应用内轻量命令 Agent，用来处理 yt-dlp 穷举不完的站点失败，以及解释宿主没能自动修好的环境问题。

能事先确定的事先由宿主做：官方 Hugging Face 失败后立刻换 `https://hf-mirror.com`，不要先问用户，也不要先打模型。Agent 通过同一份运行时画像看见 FFmpeg / Deno / MLX / yt-dlp / Whisper 准备状态。不要把已经落地的恢复 Loop、音频策略、启动端口/单实例/模型等待当成没做。也不要把它扩成通用编程 Agent。

这条修正了把两份计划理解成冲突、以及把恢复系统当成产品噪音的判断。

## 首次启动必须自动准备最佳转录环境 · 2026-08-13 02:01 · /root

MediaBrief 的发行版必须在主窗口尽快出现后，立即后台自动准备完整运行环境。`large-v3-turbo` 是正常产品路径：首次启动自动下载并负责断点续传、失败重试和网络恢复后继续，普通用户不需要确认下载、选择模型或进入设置。需要本地转录的任务在模型准备期间应显示明确等待状态，不能因为下载尚未完成而静默使用 `base`。

内置 `base` 仅用于 `large-v3-turbo` 因断网、持续下载失败或设备环境异常而确实无法使用时的应急降级；发生降级必须明确告知用户原因和质量影响。FFmpeg、FFprobe、Deno、MLX、yt-dlp 等组件同样由发行版自动提供、检查和维护，版本状态、更新结果与失败原因应进入统一诊断，不能让用户安装环境或做技术选择。

---

> 早期开发日志（2026-06-08 ~ 07-01，倒序排列），由原 `sessionlog.md` 合并而来。


## MLX 静音/水声幻觉治理 · 2026-07-01 01:20 · Codex

本轮围绕 `mlx_whisper` 在静音、水声、低语音占比音频上反复输出固定短句的问题做了两段处理。第一段已提交为 `d70c094 fix(transcriber): 收紧静音幻觉过滤`，核心判断是项目并非没有关闭跨段上下文，`condition_on_previous_text=False` 原本已经存在，真正差异在于项目阈值仍偏宽，且缺少命令行实验里最有效的重复短句后处理。`backend/transcriber.py` 现在把 `no_speech_threshold` 收紧到 `0.75`，`logprob_threshold` 收紧到 `-0.6`，并新增固定步进短句循环过滤，同时记录 VAD 命中的语音段数和语音秒数，方便之后从 `temp/logs/backend.log` 判断是否真的走了 `clip_timestamps`。

社区调研后保守加入了第二段策略，但这批仍未提交，等待真实音频测试。当前工作区里的 `backend/transcriber.py` 额外增加了低能量静音块硬跳过、VAD 语音占比日志，以及 “我可以做的”“我可以用水煮的”“我会继续来到” 这类已知幻觉短句的固定步进循环删除。选择这些策略是因为它们不依赖慢速 `word_timestamps=True` 精修路径，误删面比通用语义过滤更小，也能覆盖 `no_speech_threshold/logprob_threshold` 无法过滤的高置信度静音幻觉。后续测试重点看两类日志：如果出现 “VAD 失败，回退整块转录”，说明仍可能把噪声整块喂给 MLX；如果 VAD 语音占比很低但仍产生大量文本，下一步应把低语音占比风险块改为更严格的 fail-closed 策略，而不是继续无条件整块回退。

验证过 `venv/bin/python -m pytest backend/tests/test_transcriber_hallucinations.py backend/tests/test_silero_vad.py`，第一批提交时 9 个测试通过，第二批策略加入后 11 个测试通过。后端导入烟测 `cd backend && ../venv/bin/python -c "import main; print('OK')"` 也通过；命令结束时的 Whisper 预热 warning 是短生命周期 import 进程退出导致的后台线程调度失败，不是转录链路本身失败。

## 排障：MLX 转录极慢（base 回退） + max_tokens 4000→8000 · 2026-06-20 18:51 · pi

**现象**：88 分钟音频转录跑了 50+ 分钟还没完，GPU 85°C 持续满载。

**根因**：`whisper_models.py` 的 `is_downloaded()` 检查 `temp/whisper-models/<size>/` 目录，但 Phase 0 测速时下载的模型落在 HF 默认缓存 `~/.cache/huggingface/hub/`，不在 app 的 MODEL_DIR。`_resolve_available_size` 判定 turbo 未就绪 → 回退到 base。base 模型 137MB，MLX 上性能未经测试，实际只有 ~1.5× 实时（预期 20×+）。

**修复**：`snapshot_download(local_dir=MODEL_DIR/<size>)` 把 turbo + base 从 HF 缓存拷到 `temp/whisper-models/`，`is_downloaded` 恢复正常。注意：`snapshot_download` 是真拷贝不是软链，打包给用户不受影响。

**同时改了**：转录/翻译阶段的 LLM max_tokens 从 4000 提到 8000（`prompts/transcript.py`、`prompts/translate.py`、`summarizer.py:284`），解决长中文被截断导致 `finish_reason=length` 的问题。

**相关文档**：`docs/download-task-in-transcribe-fix.md`（RSS 下载任务在转录页展示修复方案，含 DeepSeek challenge-plan 反馈）

---

> 从 `~/.claude/projects` 与 `~/.pi/agent/sessions` 下 86 段真实开发会话还原（2026-06-08 ~ 06-14）。
> 倒序排列（新→旧）。`pi` = pi-agent，`claude` = Claude Code。聚焦决策、根因与坑，省略琐碎调试。

---

## 队列 SSE 单源收敛 + 后端单实例锁 · 2026-06-15 04:14 · pi

本轮按 `plan.md` 把「队列 SSE + 任务 SSE」收敛为「一条安全队列流 + `GET /api/task/{id}` 详情 REST」。关键约束：队列 SSE/REST 只返回轻量投影（id/task_id/status/position/source_label/progress/current_stage/ready flags 等），不再返回 `payload`、`result`、`api_key`、`model_base_url`、`model_id`，也不承载 `script/summary/translation` 正文；正文统一按需 REST 拉取。前端转录页改为队列流驱动列表与唯一 processing 进度，ready 标志翻转时拉详情；下载页脱离队列流，改轮询 `/api/task-status/{id}`。retry 不再 `asyncio.create_task` 旁路，注册为 `job_kind=retry` 进入统一队列。

排查到一个更深的并发根因：刷新后出现两条甚至多条队列项同时显示 `processing`，SQLite 里也确实有多条 `task_queue.status='processing'`。机器上残留过多个旧后端/桌面进程（`uvicorn main:app`、`start.py`），虽然只有一个进程监听 `:8000`，但旧进程仍可能持有自己的 `TaskQueueManager/SerialStrategy` 内存锁。内存锁不能跨进程，所以多个 worker 能各自认领一条任务；3 个任务时常见表现是前两条 processing、第三条 queued。

修复分三层：`db.queue_claim_next()` 用 SQLite `BEGIN IMMEDIATE` 原子认领，DB 层保证同一队列已有 processing 时不能再认领第二条；`queue_get_state()` 增加 `_normalize_single_processing()`，读取队列状态时自愈历史脏数据，只保留一个 processing，其余回 queued/终态；新增 `backend/single_instance.py`，FastAPI startup 对同一数据目录获取 `backend.instance.lock`，第二个后端实例直接启动失败，不能再持有队列 worker。`start.py` 也补了窗口关闭/服务退出时显式设置 `uvicorn.Server.should_exit` 并等待线程，`pnpm stop` 增强清理遗留 uvicorn/start.py。

注意：`frontend/src/lib/api.ts` 和 `frontend/src/lib/types.ts` 当前被 `.gitignore` 的 `lib/` 规则忽略，但本轮前端构建实际依赖了其中的 `taskDetail()`、去掉 `streamUrl()`、安全 `QueueItem` 类型等改动。未来如果要提交这批变更，必须显式处理这两个被忽略文件（调整 ignore 或 `git add -f`），否则源码状态和构建验证会脱节。

验证过：Python 编译、`cd frontend && pnpm build`、后端 import 路由数检查、单实例锁第二进程拒绝测试、队列投影不含密钥断言。当前遗留的旧 `start.py` 进程已手动杀掉。

## 仓库门面整理 + 推广策略 · 2026-06-14 12:44 · claude

- 目标：把 GitHub star 从 2 涨到 1k。之前在 Reddit / Hacker News 发的推广帖被标广告限流。
- 诊断：真正瓶颈不是文案，而是 (1) 没有在线 demo/GIF；(2) 零社会认同（建仓仅 3 周）；(3) 仓库有 AI 生成噪音。
- **修仓库门面**：发现 ZH/JA/KO 三个 README 引用的截图是不存在的 `SCR-2026*.png`（死链，劝退中文读者）；统一截图为 `docs/img/{home,rss,history}.png`、改用讲卖点的 alt 文案；日韩版项目名「AI Video Transcriber」统一为「AI Transcriber」；`sessionlog.md`/`todo.md` 移出 git 追踪。
- **写不被限流的内容**：`docs/blog/zh-transcribe-pipeline.md`，工程复盘体（字幕优先两段式、Whisper 抗幻觉调参、turbo+base 回退、LLM 去噪双层策略、摘要 SSE 先于全文），项目链接只在结尾出现一次。

## Telegram / Slack Bot 集成 · 2026-06-14 02:18 · claude

- 基于 `docs/bot-integration-design.md`，先做 Telegram 再做 Slack。bot token / chat id 等配置走前端 `SettingsDialog.tsx`。
- 关键交互澄清：给了 token 之后「总结完发给谁」→ 需要 chat id 绑定。
- Settings 内容变多 → 拆分 SettingsDialog，避免单组件膨胀。

## CLAUDE.md / AGENTS.md 补充代码风格约定 · 2026-06-14 01:49 · claude

- 给两份 agent 指南补上「如何写代码」的项目共性：命名、变量名、结构分层、何时抽取/复用等，让 AI 改动更贴合本仓风格。

## 转录链路深度健壮性加固（面向小白打包）· 2026-06-14 00:32 · claude

针对「打包后跑在不懂技术的用户机器上、最易报错的下载/转码/转录三个环节」做的三块加固。分支 `feature/transcription-chain-robustness`，前序 batch A/B/C 归一为一个基底 commit。

### ① yt-dlp 运行时自更新（解冻打包版本）· 17b09e7
- 问题：打包后 bundle 内 yt-dlp 版本被永久冻结；yt-dlp 靠更新追站点反爬，数月后 YouTube 成片失败，冻结环境无 pip、`-U` 不可用，用户无法自救。
- 方案：`backend/yt_dlp_updater.py` 在可写数据目录维护一份纯 Python yt-dlp 并置于 `sys.path` 最前覆盖随包版本；启动节流（每周一次）后台从 PyPI 拉最新 **stable** wheel（纯 stdlib 解包，无需 pip），下次启动生效；失败静默回退随包版本。`start.py` 在任何 `import yt_dlp` 前调 `schedule_update()`。

### ② 默认模型 large-v3-turbo + 抗幻觉调参 · 5ecc923
- 2026 重评估：Parakeet/Canary 不支持中日韩且依赖 CUDA；SenseVoice 要换运行时、时间戳弱。`large-v3-turbo` 为 CPU+CJK 甜点（比 large-v3 快约 8×、int8 约 1.5GB、四语全覆盖），引擎仍用 faster-whisper/CT2，零架构改动。
- `whisper_models`：DEFAULT_MODEL=large-v3-turbo，BUILTIN_MODEL=base 内嵌离线回退；`ensure_default_model_async` 首启后台下载，`_resolve_available_size` 就绪前优雅回退 base。`pipeline` 走 `get_transcriber()` 每次重解析，下载完成后自动切 turbo。
- VAD/阈值对齐 WhisperX/Calm-Whisper：min_silence 900→500、speech_pad 300→400、no_speech 0.7→0.6、compression_ratio 2.3→2.4，补 turbo 在短/噪片段的短板。

### ③ FFmpeg/FFprobe 链路加固 · 343d9b0
- P0-1 ffprobe 未打包/定位：旧实现只定位 ffmpeg，时长校验用 `ffprobe … shell=True`，缺 ffprobe 时静默吞异常 → 损坏/截断音频被直送 Whisper。现 `build_ffmpeg.sh` 产出校验 `ffprobe-arm64`，`start.py` 导出 `AIT_FFMPEG/AIT_FFPROBE/AIT_FFMPEG_LOCATION`。
- P0-2 未显式传 `ffmpeg_location`：后处理仅靠 PATH，打包后（尤其 Windows）易 FileNotFoundError。`video_processor` 模块级解析绝对路径注入 yt-dlp；新增 `_run_media_proc`（进程组+取消令牌+库路径清理+超时），删除两处 `shell=True`。

## 打包后小白机最致命链路：下载格式不可用 / 转录 NO_SUCHFILE / 转码失败 · 2026-06-13 21:51~22:37 · claude/pi

这是「在别人电脑上跑不起来」的总爆发，三个独立根因（也是触发上面健壮性加固的直接原因）：

### yt-dlp `Requested format is not available`（player_client × nsig）
- yt-dlp 不同 `player_client` 对 JS 运行时（Deno）和 GitHub 可达性的依赖不同。web 系（`ios`/`web_safari`/`mweb`）需解 nsig 签名 → 依赖 Deno + 从 GitHub 拉 JS 解算脚本。打包分发后无 Deno + 国内 GitHub 不可达 → 签名解不了 → 格式选择失败。
- 解决：优先 `android_vr`/`android`（不需要 nsig，零 JS 运行时也能拿可播放音频），web 系作 fallback；加「无 cookies 模式」自动重试。复现：`PATH= ./ai-transcriber`（剥空运行时模拟小白环境）。

### 转录 `[ONNXRuntimeError] NO_SUCHFILE`
- 路径指向 `.app/.../faster_whisper/assets/silero_vad.onnx`。根因：PyInstaller 打包后 faster-whisper 的 assets 路径解析与开发环境不同，VAD 模型文件没被正确收集/定位。

### 转码 `Postprocessing: audio conversion failed: Invalid argument`
- ffmpeg/ffprobe 在打包环境定位问题，由上面的 FFmpeg 链路加固一并解决。

### 教训（用户反复强调）
- **日志系统是刚需**：前面所有报错用户侧几乎无法感知，全靠用户手动复制日志进来排查。`logging_config.py` 的落盘日志（frozen 时写 Application Support）是排障基础设施。

## macOS 打包四件致命/严重缺陷（日文 review 复核）· 2026-06-13 21:22 · pi

一次彻底的打包 review（部分以日文记录），确认 4 个真实缺陷，其中 2 个「别人 Mac 上根本起不来」：

- 🔴 **DB 路径在 frozen 时指向只读 .app**：`db.py` 的 `DB_PATH = __file__.parent.parent/"temp"/...` 没考虑打包。`task_store.py` 已有正确的 `_get_data_dir()`（frozen → `~/Library/Application Support`），但 `db.py` 直接 `from task_store import TEMP_DIR` 会循环依赖。修复：`db.py`/`logging_config.py` 用延迟函数取 `TEMP_DIR`，单一真实源。
- 🔴 **Homebrew ffmpeg 动态链接无法分发**：依赖 dylib 全指向 `/opt/homebrew/...`，没装 Homebrew 的 Mac 即 dyld 错误。macOS arm64 静态 ffmpeg 无公开源（evermeet 不做 arm64，BtbN 无 macOS，ffbinaries 只有 x86_64）。方案：`scripts/build_ffmpeg.sh` 从 ffmpeg 7.1.1 源码编译最小化静态二进制（3.3MB，仅链接系统库）。
- 🟠 **注入的 ffmpeg 未签名**：公证会 reject。`sign_and_package.sh` 的 find 模式补 `-name "ffmpeg"`。
- 🟠 **CORS 全开 `*` + credentials**：桌面版常驻 `127.0.0.1:8000`，任意恶意网站可 fetch 到本地历史/配置。`main.py` allow_origins 改白名单（127.0.0.1/localhost × 8000/5173）。

## 设置弹窗：模型选择/下载与「按钮全 disabled」连环 bug · 2026-06-13 20:38~21:13 · claude

- 需求：Settings 弹窗加转写模型选择（small/medium/large）+ 下载源 + 下载入口；`HF_ENDPOINT` 填一次要持久化，不用重填。
- **bug：四个模型按钮全 disabled** → 根因 `disabled={!m.downloaded}`，未下载的模型不可选（设计如此，但内嵌的 base 该可选）。
- **按钮太高** → 因为把「下载 button」包在了选择 button 内部，拆到 div 外、保持一行、去图标、改小。
- **打包后仍弹「首次需下载模型」引导页** → 模型已内嵌 base，引导不该出现；用户等 5 分钟无动静（初始化卡住）。

## YouTube 频道订阅 + 平台提取器架构 · 2026-06-13 19:46~19:49 · claude/pi

- **YouTube 频道 feed 归一化**：用户可能输入 `UCxxx` / `/channel/UC` / `/@handle` / `/c/name` / `/user/name`，统一转成 `feeds/videos.xml?channel_id=UC...`。`UC`/`/channel/` 直接提取；`@handle`/`/c/`/`/user/` 需抓频道页 HTML 提取 channelId（不必 YouTube Data API）。
- **YouTube feed 条目无 enclosure**（link 是 watch URL）→ pipeline 要把这类 link 当媒体处理（走下载/字幕），而非当文章正文。
- **平台提取器架构**：不同站点下载常报错，抽象 `backend/platforms/`（`_base.py` + `youtube.py`/`bilibili.py`/`generic.py`），按 URL 域名分派，避免逻辑耦合。

## 队列与取消架构定稿：研究驱动的「杀干净」方案 · 2026-06-13 13:06 · claude（皇冠级决策）

这是全项目最重要的架构决策，由「取消任务要杀干净」这一句需求，经四轮官方文档/源码调研逐步收敛成形。值得完整记录推演链。

### 起点：队列接口残缺盘点
- **取消能力残缺（最严重）**：`DELETE /api/queue/{item_id}` 只删 DB 行，正在 `processing` 的 worker 协程不会被取消；队列路由和转录路由各有一套取消、互不相通；`_db_set_cancelled` 状态存在但 REST 层没人用，取消即物理删除丢审计。
- 没有轻量 stats/length 接口（`get_state` 一次返全部 items 含 payload+result 全文）、没有单项详情接口、入队裸 dict 无校验（未知 `item_type` 一路入队到 worker 才报错）。
- **history 判断是反的**：转录全文**确实有存**（`tasks.script`），真正问题相反——`GET /api/history` 每行都返回完整 `script`+`summary`，列表一次 100 条 = 上兆文本。

### 关键追根：线程在 Python 里杀不掉
追到底发现一个架构硬约束：下载（yt-dlp 库）、转录（faster-whisper C++ 推理）、ffmpeg 全跑在 `asyncio.to_thread` 的**线程**里。`task.cancel()` 只取消「对线程的等待」，线程本身和底层 C++/IO **继续空跑直到自然结束**。所以现状的「取消」是假的——**前端任务消失了、记录删了，但 CPU/GPU 还在为已取消任务满载，下载还在占网络**。这是比接口设计更深的健壮性漏洞。

### 用户拍板「杀干净」→ 四轮调研避免架构膨胀
用户明确「取消要杀干净」，并要求**先查各库官方有没有更好方案再定稿，别每次设想都让架构更复杂**。逐一调研后结论反直觉：

| 阶段 | 官方推荐取消机制 | 要进程隔离吗 |
|---|---|---|
| **Whisper 转录** | `transcribe()` 返回**惰性 generator**，迭代时才解码；`for segment in segments` 里查标志 → `segments.close()`+break。模型保持热复用、零冷启动 | ❌ |
| **yt-dlp 下载** | `progress_hooks` 里 `raise DownloadCancelled`（源码确认专门捕获）；事后清 `.part` | ❌ |
| **ffmpeg 后处理** | 外部子进程，无法进程内取消（官方 issue #7599）；只能 `start_new_session` 建进程组、`killpg` 整组（杀顶层漏孙子，issue #5902） | ✅（仅此一处） |

- **顺手发现的现存 bug**：逐段迭代 `for segment in segments` 跑在主事件循环线程，转录期间阻塞整个 asyncio（SSE 心跳/其它请求全卡）。一并修：把迭代挪进 `to_thread`。
- **模型复用 vs 杀干净的矛盾被消解**：最初以为要进程隔离（一任务一子进程 → 每次冷启动重载几百 MB 模型）。查 faster-whisper 官方后确认 Whisper 用协作取消即可、模型常驻 `services.py` 单例全程热复用，矛盾自动消失。
- **库调研定论**：Celery `revoke(terminate=True)` 能真杀是因为 prefork 本就把任务跑在子进程 + 需 Redis/RabbitMQ broker（PyInstaller 打包桌面端极痛苦、单用户应用过度设计）；ARQ/SAQ 的 `job.abort()` 用的就是 asyncio 取消（和现状一样杀不掉，还白搭 Redis）。**根因不在队列框架，在底层三库的活进程内不可打断**。结论：保留进程内手写串行队列、不引任何 broker，把取消用「各库官方机制 + 一处进程组」补对。

### 落地（commit `feat(queue): 支持可取消任务并按需读取转录`）
- **A 取消内核** `backend/cancellation.py`：`CancelToken`（`threading.Event` + 子进程组登记），`contextvars` 传递不穿透函数签名，`registry` 按 task_id 触发，`killpg` 整组回收；决策记录 D1–D7 注释在文件顶部。
- **B 三阶段接入**：transcriber generator break + 迭代挪进线程；video_processor 在唯一下载入口 `_download_with_timeout` 注入 hook → `raise DownloadCancelled`，`normalize_local_media_to_m4a` 由 `subprocess.run` 改 `Popen(start_new_session=True)` 登记令牌；pipeline 5 个任务函数 `except CancelledByUser: raise` 不再误标 error。
- **C 队列接口**：`GET stats / items / item/{id}`、`POST item/{id}/cancel`（杀干净+删记录）、`DELETE item/{id}`（仅终态）；入队改 Pydantic + `is_registered` 校验；`delete_task` 统一委托 `cancel_item`，消除两套取消。
- **D history 瘦身**：`list_history` 不返回 `script` 全文（只回元数据+摘要+`has_transcript`），新增 `GET /api/task/{id}/transcript` 按需取。
- **前端同步**：`lib/api.ts` 加 `taskTranscript`/`queueStats` 等；RssPage 排队/处理中条目加「取消」按钮；HistoryPage 详情页加「摘要/转录」切换、按需拉取转录稿（补上用户最初抱怨的「history 看不到转录」）。

## 队列从 RSS 专用到通用串行 + RSS topic/region 分类 · 2026-06-13 04:06~12:23 · pi（前置）

上面架构定稿的前置背景，也由一连串状态混乱 bug 逼出。

- **触发**：上传 MP3 任务进行中 → 点 RSS summarize → MP3 任务被覆盖。根因：队列初期只为 RSS 设计、没覆盖用户手动任务；summaries 按钮没禁用仍可点。用户纠正：「队列只是针对任务维度，不是 RSS 专用；RSS 是否在等待，应区别于当前任务维度是否有正在执行的」。
- **核心决策**：改**多任务串行队列**，后面任务排队等待。**后端不能并发**——Whisper 内存压力、CPU 压力，必须串行。
- `tasks.script` 从 JSON `data.script` 提升为固定列（读取列优先、history 搜索含 script），不做历史回填（用户：没有就没有）。
- result-panel 与 progress-panel **改为可共存**（摘要可能先于转录出来）——之前误把结果面板绑在 `phase==="results"`，导致摘要到了不显示。
- **RSS 分类**：最初做成音频/视频/纯文本，用户纠正「按 RSS 自带信息分类就行」→ 改成 `topic`/`region` 两行 badge + 两行筛选，元数据从 JSON 导入时本地保存；`recommended_rss_feeds.json`（43 源）规整为单 topic/单 region。
- 队列 UI：沙漏图标 → 纯文本 "waiting"；进行中时 summaries 按钮保持 disabled。

## 状态持久化迁移：前端 sessionStorage → 后端 SQLite 单一真实源 · 2026-06-13 04:11~04:34 · pi

- 起点：「页面刷新后端任务还会继续吗？」→ 会，但前端状态丢。第一版用 `taskId` 存 `sessionStorage`，刷新后 `api.taskStatus(taskId)` 恢复。
- 用户嫌这个逻辑烦：「taskId 不能直接都保存到后端吗？前端任何时候刷新都获取当前任务。历史也是，完成自动保存。RSS 解析也在后端，干脆**全部移到后端数据库**，前端只留 model/配置等必要信息到 localStorage。」→ 后端成为唯一真实源。
- 暴露 bug：`NOT NULL constraint failed: tasks.summary`（任务未完成时 summary 为空但建了非空约束）。
- 后端缺日志难排查 → 新增 `logging_config.py` 日志系统。
- **前端 keep-alive 但状态页面私有的澄清**（用户：四个页面应常驻、状态持续更新，与是否在当前页无关）：`App.tsx` 已把四页全渲染、只用 `hidden` 隐藏（切路由不卸载），但数据模型是**页面私有而非全局**——有的页进入时 re-query、有的不。改为：各页**挂载即启动**（loadFeeds/syncQueueState/SSE），去掉切页重拉；History 加 15 秒轮询保证后台持续更新；保留 RSS→Transcribe 任务交接但该步不查最新状态。

## 后端阻塞：转录期间所有短接口 pending · 2026-06-13 11:43 · pi

- 现象：转录任务进行时，`model-status` 等短接口全部 pending，任务结束瞬间全返回。
- 根因：CPU 密集型转录阻塞了 asyncio 事件循环。靠 `asyncio.to_thread` 把阻塞工作挪出事件循环缓解。

## React 大迁移：Vanilla JS → React SPA · 2026-06-13 01:47~03:24 · claude/pi

- 动机：组件化、page router、更现代的 UI。big-bang 重写：`static/app.js` 等旧前端 → `frontend/` 下 React 19 + TS + Vite SPA。
- 技术选型：react-router-dom v7（HashRouter）、Radix UI 无样式原语、`@fluentui/react-icons` 替代内联 SVG、`marked` 渲染 Markdown。**Tailwind v4 不稳 → 降级 v3.4**。
- 工作流定型：dev 用 Vite 代理 `/api`→:8000，不用每次打包；生产 `pnpm build`→`static/`，FastAPI mount；根 `pnpm dev` concurrently 起前后端；生产打包写进 GitHub CI/CD。
- 构建产物 `static/` 不再 git 追踪（CI 生成）；`icon.icns` 改打包时由 `icon-light` 生成（CI），不进仓库。
- **典型坑：Radix `Slot failed to slot onto its children`** —— `asChild` 要求单一 React 元素子节点，RSS 路由进入即崩。
- **路由切换不要卸载**：默认切 tab 会卸载组件 → 进行中的任务 UI 状态丢。改 keep-alive，四个页面常驻，进入 tab 自动刷新自己的数据。
- model select 刷新后为空（没缓存）→ 补缓存 + fetch 后默认选中第一个。

## 后端健壮性重构（5 主题）+ Broken Pipe 诊断弧 · 2026-06-13 03:10 · claude

需求「make backend more 健壮/易扩展/flexible」，做成五个可独立增量落地的主题。

### 主题 1 — 杀掉共享可变状态（真正的并发 bug）
- `transcriber.last_detected_language` 是**挂在共享单例上的可变状态**：每个并发任务都写同一字段，两任务同时跑时**语言检测会串台**（task B 覆盖 task A 还没读到的值）。`summarizer`/`translator` 单例没事是因为它们不持每请求状态，`Transcriber` 持有——这是最清晰的「不健壮」点。
- 修复：`transcribe()` 改为**返回** `(text, language)`，彻底删除 `last_detected_language`；语言作为局部参数 `detected_language` 流过 `run_post_extract_pipeline`；新增无状态 `parse_detected_language()`。
- 顺手修：`routers/transcribe.py` 缺 `FileResponse` 导入，下载端点一调用就 `NameError`。

### 主题 2/3/4 — 新增扩展性脚手架（4 个新模块）
| 模块 | 作用 |
|---|---|
| `config.py` | 单一 `Settings`（dataclass，不引 pydantic-settings 依赖），所有 env（`UPLOAD_MAX_MB`、whisper size、LLM 超时、模型）集中读取 |
| `exceptions.py` | 类型化领域异常 `SourceError`/`TranscriptionError`/`LLMError`，各带 `http_status`，router 映射真实 HTTP 码而非一律 500 |
| `providers.py` | `ASRBackend`/`SummarizerBackend` Protocol + `build_asr_backend()` 工厂，靠 config 换 provider 而非改 pipeline |
| `sources.py` | `extract_media_source()` —— 把 `process_video_task`/`process_upload_task`/`run_rss_summarize_task` 里复制三份的「字幕→音频→Whisper」分支收敛成一个注入式、可单测的函数 |

### 主题 5 — 刻意收窄范围（不做 TaskRegistry 重命名）
- 没做全量 `TaskRegistry` 重命名：单进程单事件循环下，为它改 6 个文件是高 churn 低收益。改为修一个真 bug：任务处理中被 delete（`del tasks[task_id]`）→ 后台任务的 `tasks[task_id].update(...)` 抛 `KeyError`，而 `except` 里**也**做同样 update → 二次故障。新增 `update_task()` 安全访问器（任务已删则 no-op），守住所有错误处理器。

### Broken Pipe 诊断弧（同会话，三次转向才定根因）
- 现象：第一个任务跑着、刷新页面、再发第二个任务 → `下载失败: [Errno 32] Broken pipe`，且偶发、只在并发时复现。
- **第一猜**（错）：`remote_components: ['ejs:github']`——YouTube 专用 nsig 签名求解器、要从 GitHub 拉 JS 组件，国内/B 站用户访问 GitHub 不稳会断管道。确实有问题（顺手把它 gate 到仅 YouTube + 删掉构造函数里那份从没传给 `YoutubeDL` 的 dead config），但不是本 case 根因。
- **第二猜**：用户揭示「第一个任务在跑+刷新+第二个任务」→ 转向并发问题。为拿真相加了 `backend/dev.log` 文件日志（之前用户一直「看不到日志」，`pnpm dev` 把前后端输出混在一起）。
- **真根因**（dev.log 实证）：错误里的 `\x1b[0;31mERROR\x1b[0m`、`\r[download]` 是 yt-dlp 往 stdout 打**进度条 ANSI 颜色码**。`pnpm dev`=`uvicorn --reload` 下 worker 的 stdout 是连到 reloader 的**管道**而非终端；单任务写得少扛得住，两个 yt-dlp 同时狂写 → 某次写失败 → 管道破裂。完美解释「只在并发时偶发」。
- 修复：`_get_base_opts` 给所有 yt-dlp 调用注入 `logger=_YDLP_LOGGER`+`noprogress=True`+`no_color=True`+`consoletitle=False`，让 yt-dlp **再也不碰原始 stdout 管道**，输出改走 Python logging。教训：打包/管道环境下子进程的终端控制码是隐蔽故障源。
- 附带坑：`pnpm dev:api` 报 `uvicorn: command not found`（新终端没激活 venv）；`Address already in use`（旧 `pnpm dev` 后端还占着 8000）。还顺带澄清一个体验 bug：「Connecting… 没动静」不是卡死，是 base 模型 CPU 跑 36 分钟音频期间转录无进度回传（也是后来加实时进度 + Whisper 协作取消的动机）。

## 桌面打包起源：pywebview + PyInstaller（非 Electron）· 2026-06-11 16:46~ · pi

- 洞察：项目本就是「一个 Python 进程既当后端又当前端服务器」（FastAPI mount `static/`）。要分发给小白 → 打包成双击启动的桌面软件。
- 选型：**pywebview**（系统原生 WebView：macOS WebKit / Windows Edge WebView2，无需捆 Chromium）+ uvicorn 后台线程 + PyInstaller。比 Electron 轻得多。
- 几个打包关键点：
  - `.env` 含真实 API key，**绝不能打进包**（基石：配置来自前端，不进服务端）。
  - 打包后 `.app` 内部只读 → 数据目录改用系统应用数据目录（macOS `~/Library/Application Support`，Windows `%APPDATA%`）。
  - PyInstaller 静态分析追不到 uvicorn 运行时 `import "main:app"` → spec 文件显式收集 `backend/` 全部模块。
  - Whisper 模型太大不进包 → 首启后台静默下载，用户无感。
  - CTranslate2 的 native `.dylib`/`.dll` 需显式收集；缺 ffmpeg 静态二进制单独塞。
- 提交到 `feature/desktop-packaging` 分支。

## 字幕优先链路的两个独立 Bug + 下载超时治理 · 2026-06-10 01:44 · claude

这是「明明有字幕却永远找字幕失败」的根因，两个**完全不同**的 bug：

- **Bug 1（拼写）`yt-dlp.YoutubeDL`**：`video_processor.py:194` 把下划线写成连字符。Python 把 `yt-dlp.YoutubeDL` 解析成减法 `yt - dlp.YoutubeDL`，语法合法（import 不报错）但运行到这行每次抛 `NameError`，被第 228 行 `except` 兜住 → 打日志「字幕获取失败」静默回退下载音频。所以字幕永远用不上。修复 `-`→`_`（commit 2b07682）。检测步用的对象名拼写正确，所以日志能看到「发现字幕」却用不上，更迷惑。
- **Bug 2（超时）下载大播客**：100MB MP3 在 ~175KiB/s 下需约 10 分钟，但被硬性 300s 超时 kill。`asyncio.wait_for` 抛的 `TimeoutError` `str()` 为空 → UI 显示 `下载视频失败:`（冒号后空白）。修复：300s→1800s，并 catch 转成可读消息（commit ee28d06）。
- **更深的线程泄漏**（用户指出）：`asyncio.wait_for` 只取消 await，`asyncio.to_thread` 的线程不会停（日志末尾还在 `74.9%...` 就是证据）。真正能终止线程的是 yt-dlp 自己的 `socket_timeout`。补 `socket_timeout=30` 到 `ydl_opts`；五处下载站点统一走 `_download_with_timeout` helper。

## RSS 增强：收藏置顶、两栏布局、链接型 feed 抓正文 · 2026-06-09 · claude/pi

- **订阅收藏**：针对整个订阅源（非单集）的本地 `favorite` 字段，置顶排序，存 IndexedDB；`_rssMergeFeed` 刷新/重订阅时保留该字段不丢。
- **两栏 master-detail**：RSS / History 从单列手风琴改成「左列表 + 右详情」，`max-width` 放宽到 1180px，两栏独立滚动，<760px fallback 单列。处理了空列表、搜索无结果、删除选中项、长标题、被筛选隐藏的选中项等边界。
- **标题 Tooltip 布局无关化**：原 `::after` 伪元素撑出横向滚动条；参考 shadcn/Radix，改成 JS 动态挂到 `document.body` 的 `position:fixed` floating tooltip，默认显示在标题上方居中；`.split-list` 加 `overflow-x:hidden`。
- **surma.dev「没有可处理的内容」**：该 feed 每个 entry 是空 `<content>`、无 summary、无 enclosure（纯标题+链接型）。pipeline 原本「enclosure→文本→报错」三分支没有「从 link 抓正文」。讨论三方案（A 标准库去标签 / B trafilatura / C 原始 HTML 喂 LLM），选 **B trafilatura**：新增 `fetch_article_text(url)`，pipeline 兜底先抓原文再摘要；实测 surma 文章提取 35854 字干净正文。`requirements.txt` +trafilatura。
- **重试跳过重复优化**：转录首次已优化，retry 不该再跑一遍 `optimize_transcript`，复用 `regenerate_summary`（已 skip「优化转录」阶段），且优先用已优化转录做摘要。
- **取消链路修正**：改成「后端先取消成功 → 再让前端关 SSE/清状态」；取消时 `_clearResultsArea()` 清掉残留的 partial summary 面板；`<form>` 加 `novalidate`（`required` 字段会在 submit 前触发「请填写此字段」，拦截取消）。

## 项目创世与架构基石 · 2026-06-08 · pi

早期是原生 HTML/CSS/JS（`static/app.js` 单文件）+ FastAPI，致敬 fork 自 `wendy7756/AI-Video-Transcriber`。这一天确立了贯穿全程的基石。

- **后端无状态、配置来自前端**（最重要基石）：起于把 OpenAI URL 换成 DeepSeek。暴露两坑——SOCKS 代理崩溃（`httpx` 缺 `socksio`）、模型名写死 `gpt-4o`（DeepSeek 只认 `deepseek-v4-pro/flash`）。由此定下：API key/base URL/model 全由前端请求体传入、存浏览器 `localStorage`（`vt_settings`），服务端不持久化、不依赖 `.env`。
- **ASR**：faster-whisper（CTranslate2，CPU+int8），默认 `base`，支持 en/zh/ja/ko。
- **yt-dlp `detecting` 慢 20 秒**：根因默认开 `cookiesfrombrowser` 自动读浏览器 cookies（macOS 读钥匙串极慢）+ Firefox 无条件检测。改为默认关闭，仅显式配置时启用。
- **摘要不再等待全文优化**（关键流程决策，针对 3 小时长视频）：原串行 `raw→optimize(28块逐块)→summary`，等待极长。讨论清楚：分块不是输入放不下，而是单次 `max_tokens=4000` 输出会截断；streaming 不扩上下文/输出上限。改为并行——轻清理 raw 直接喂摘要，transcript 优化后台跑；摘要完成立即 SSE 广播展示，Transcript 后补齐。同时移除「语言不同就全文翻译」分支，直接按 `summary_language` 出摘要。
- **双步摘要定型**：Step1 取原文（≤5 万不截）让 LLM 分析「该如何总结」产出提示词；Step2 把该提示词作 system prompt、完整原文作 user prompt 出摘要。
- **进度条 119% bug**：`url_summary` 阶段权重和为 120 却被当百分制相加。用户纠正「不要 clamp 掩盖，要计算正确」→ 按总权重归一化。
- **RSS 存储 localStorage→IndexedDB**：批量导入「32 failed」连环排查——后端实测 42 源全能解析（排除源问题）→ 怀疑并发太猛改顺序+重试 → 加日志才现真凶 `QuotaExceededError`（feed 一次 700~1000 条撑爆 localStorage）→ 整体迁 IndexedDB（`ai_transcriber_rss`/`feeds`）。`urlparse` 未导入致添加订阅静默失败也在此修。
- **历史摘要 IndexedDB**：History tab，增删查（无改，用户明确不要 sqlite），可在线浏览不必下载。
- **i18n 抽离 + app.js 拆分**：i18n 硬编码致 `app.js` 膨胀到 1366 行 → 抽 `js/i18n.js`，新增日/韩（共四语），切换改四语下拉；`app.js` 拆成 `js/{i18n,ui,transcribe,download,history,rss}.js` 降到 ~244 行；新增 `README_JA/KO.md`，四语互链。
- **进度文案口径简化**：「第 N/M 步·本步 X%」三套口径太乱 → 删「本步内部完成度」，纯按阶段计数；`STAGE_WEIGHTS` 改名 `STAGE_DEFINITIONS` 去掉无用 weight。
