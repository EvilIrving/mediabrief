# MediaBrief 自适应媒体任务恢复与转录执行计划

更新时间：2026-08-13  
当前状态：Task 1–7 已完成
执行方式：一次只完成一个任务；完成并验收后再开始下一项

这和根目录 `ProductizationPlan.md` 是同一产品的两层，不是互相替代：

- 产品层：用户装上就能用，不填配置。环境、模型、库由软件自己管。
- AI Native 层：软件内嵌一个轻量命令 Agent。yt-dlp 覆盖不了一千个站，环境失败也不该靠一百条 if/else。Agent 拿上下文、用这个软件自己的工具、能自己处理就自己处理，必须人点头才问人。

已经落地的媒体恢复 Loop、音频策略、质量复核和任务详情不要重做。后面只补它还看不见的环境，以及宿主能确定处理的策略。

## 一、目标

MediaBrief 要解决的不是“在应用里造一个通用 Coding Agent”，而是一个完整的媒体任务问题：

1. YouTube、Bilibili 等站点策略变化后，原有 yt-dlp 路径失败，应用仍能诊断并尝试恢复；
2. 得到音频后，不是直接套一组固定 Whisper 参数，而是先分析音频质量和内容结构；
3. 根据分析结果选择受控的转录策略；
4. 转录后检查空白、重复、幻觉和异常区间，必要时只重试可疑片段；
5. 最终向下游交付经过宿主程序验证的媒体和可信转录。

媒体获取失败恢复是第一个高价值场景，但不是完整边界。完整链路是：

```text
来源获取与失败恢复
  → 媒体文件验证
  → 音频质量分析
  → 生成 Whisper 转录策略
  → 执行转录
  → 转录质量复核
  → 可疑片段有限重试
  → 摘要、翻译和导出
```

核心定义：

> 能事先确定的事（换国内模型镜像、续传、检查随包组件、选空闲端口）由宿主直接做。解释不清或策略穷举不完的事（站点抽取失败、未分类的环境错误）进同一个轻量 Agent loop。模型只选择宿主提供的工具；宿主负责权限、网络、登录态、资源、执行和结果验证。

## 二、范围边界

### 这是要做的

- 一个短生命周期、有步骤与资源预算的轻量命令 Agent loop（媒体恢复是第一个接入场景）；
- 对 yt-dlp 完整脱敏诊断的保留和分类；
- YouTube/Bilibili 的受控恢复动作；
- 必要时生成一次性 HTML/JSON/媒体清单解析器；
- 确定性的音频质量分析；
- 从宿主认可的配置中选择 Whisper 策略；
- 转录质量报告和有限的局部重试；
- 需要登录、授权或用户操作时返回结构化请求；
- 在 UI 中解释音频情况、采用的策略、恢复过程和结果。

### 这不是要做的

- 通用 Coding Agent、通用 Shell、代码编辑器或仓库维护 Agent（应用内轻量命令 Agent 要做，通用编程 Agent 不要）；
- 让模型修改 MediaBrief 源码、安装目录或用户项目；
- 通用插件/MCP/技能系统；
- 长期会话、上下文压缩、向量数据库、多 Agent 或工作流平台；
- 通用浏览器自动化和任意登录态 HTTP 代理；
- 自研一套跨平台通用 OS 沙箱；
- 绕过 DRM、会员、私密内容、地区限制或其他访问控制。

## 三、已确认的设计决策

1. **正常路径优先。** 字幕或音频正常取得时，不启动媒体获取 Agent；音频体检和策略选择仍可正常执行。
2. **完整范围包含转录。** Agent/策略层不能在“下载成功”处结束，必须覆盖 AudioProfile、TranscriptionStrategy 和 TranscriptQualityReport。
3. **事实由确定性工具产生。** 编码、采样率、音量、静音、语音比例等由 FFprobe、PCM 统计和 Silero VAD 计算，模型不能凭感觉编造。
4. **Whisper 只能使用宿主认可的策略。** 模型可以选择策略、说明原因，但不能传入任意底层参数或加载任意模型。
5. **现有默认策略必须保留为兜底。** 分析或 Agent 失败时，仍按当前 mlx-whisper + Silero VAD 路径完成任务。
6. **转录重试必须有限。** 优先只重试可疑时间段，不允许无上限地整段反复转录。
7. **获取恢复使用真正的 Loop。** 现场 → 模型判断 → 宿主工具/候选解析器 → observation → 再判断 → 完成/问人/停止。
8. **恢复工具是固定能力，不是裸命令。** yt-dlp、HTTP、Cookie、EJS/PO Token provider、下载和 FFmpeg 都通过结构化动作调用，不接受 Shell 字符串。
9. **登录态是不透明能力。** Agent 只知道某个浏览器会话是否可用和是否获准使用，永远看不到 Cookie、Token、认证头或浏览器数据库。
10. **YouTube challenge 交给确定性组件。** EJS、JS runtime、PO Token provider 等由 yt-dlp/宿主能力处理；模型只负责诊断和选择，不能临时“发明”证明令牌。
11. **候选代码只解决媒体解析。** 第一版只用于解析宿主提供的 HTML/JSON/清单，不能编写音频处理逻辑、修改应用或直接联网。
12. **候选代码是纯 stdin/stdout 转换器。** 输入 JSON，输出 JSON；不需要文件、网络、环境变量、Cookie 或子进程权限。
13. **候选运行时只选一种。** 优先实测已随包携带的 Deno；若无法在 PyInstaller/macOS 场景可靠满足权限边界，则暂不启用候选代码，不能用宿主进程 `exec()` 或高权限 Python subprocess 顶替。
14. **候选代码第一版只使用一次。** 当前任务结束即删除，不自动缓存、共享或远程下发。
15. **结果由宿主验证。** 文件存在、非空、媒体可解析、音轨有效、时长合理，转录结果通过质量检查，才算成功。
16. **用户动作固定，说明可以动态。** 模型可以生成纯文本解释，但按钮行为只能绑定宿主认可的固定 action code。
17. **`action_required` 不长期占用运行协程。** 第一版结束当前恢复运行并保存最小继续现场；用户操作后重新入队继续，避免建设常驻会话 actor。
18. **直接调用 DeepSeek API。** 当前验证阶段不建设 Hosted API、账号、兑换码或密钥代理。
19. **真实 Key 不进入公开 Git。** 构建时从本机未跟踪配置或环境注入，可做轻量混淆，并通过控制台额度、频率和费用限制控制风险。
20. **任何不可恢复场景都要停止。** DRM、无访问权、账号风控、站点服务端拒绝等不能伪装成可修复问题。
21. **宿主先做能确定的事。** 官方 Hugging Face 失败后自动换国内镜像，不先问用户，也不先打模型。镜像都失败后，再让 Agent 看见现场并解释。
22. **Agent 要能看见运行环境。** Deno、MLX、FFmpeg、yt-dlp、默认 Whisper 模型的准备状态是同一份运行时画像，不能只存在启动日志里。

## 四、当前代码事实

### 已经落地，不要重做

- 字幕路径故障已分类，不再和“确认没有字幕”混为一谈；`ExtractResult` 会保留脱敏 `ExtractionFailure`。
- 字幕和音频都失败后，`pipeline.py` 才启动 `MediaRecoveryService`；正常成功路径不调用 DeepSeek。
- 恢复 Loop 在 `media_recovery.py`：闭集动作、预算、取消、问人后结束协程。工具在 `media_recovery_actions.py`，YouTube/Bilibili 白名单 profile、受限 HTTP、一次性 Deno 解析器、宿主验证都已接上。
- `AudioProfile`、`TranscriptionStrategy`、`TranscriptQualityReport` 已进入任务状态和 `TaskInsightsPanel`。
- 真实公开样本验证过字幕快路径和音频下载；完整恢复闭环仍主要靠模拟。DeepSeek 只做过最小真实连通。
- Deno 候选解析器已在本机和打包 `deno` 上验证过无文件/网络/环境/子进程权限。

### 媒体获取

- `sources.py` 仍是“字幕 → 音频 → Whisper”，失败后才进恢复。
- HTTP 和 yt-dlp profile 目前按 YouTube/Bilibili 域名收口；未知站点几乎只能再跑通用抽取。
- `yt_dlp_updater.py` 已有可写副本、每周检查、原子替换和 `update_status()`；恢复动作里的 `prepare_ytdlp_update` 可以触发检查，新版本仍是下次启动生效。
- `start.py` 会找随包 Deno 并注入 PATH。

### 音频、模型与启动

- 转录引擎是 `mlx-whisper`，MLX 单 worker 线程。
- 默认模型是 `large-v3-turbo`；`base` 只作明确降级。`get_transcriber()` 在默认模型未就绪时返回惰性门闩，真正转录才等待；`_resolve_available_size()` 不再偷偷改成 `base`。
- 首启会后台下载默认模型，有进度、退避重试和 `snapshot_download` 续传。三次失败后置 `degraded`，转录可用 `base`，后台继续拉大模型。
- 下载仍默认打官方 Hugging Face。`hf_endpoint` 只在开发设置或单次 API 参数里生效，发行版会藏掉这项设置。官方源失败后不会自动换国内镜像。
- `start.py` 已用系统分配端口、单实例锁、启动失败重试/打开日志、退出清理子进程。`confirm_close=True` 是通用关窗确认，还不会说明“正在运行的任务会被停止”。

### 任务与 UI

- 任务状态、SQLite、队列 SSE、固定恢复 action code 已接好。
- 发行配置存在时，前端隐藏 API Key、Base URL、模型选择和 Whisper 选择。
- `/api/diagnostics` 和 `/api/environment-status` 已能读 Whisper / yt-dlp 状态，但恢复 Agent 的 `inspect_runtime` 几乎只看 yt-dlp 版本和 Cookie/Deno 布尔值，看不见模型下载失败原因。

## 五、总体控制流

```text
URL / 本地媒体 / RSS enclosure
  ↓
正常来源提取
  ├─ 成功取得字幕 → 验证字幕 → 下游整理
  ├─ 成功取得音频 → 宿主验证媒体
  └─ 失败 → 收集脱敏 ExtractionFailure
               ↓
          Media Recovery Loop
            ├─ 检查 yt-dlp/运行时状态
            ├─ 选择受控 yt-dlp 重试配置
            ├─ 请求不透明浏览器 Cookie 能力
            ├─ 使用宿主 HTTP 获取页面/JSON
            ├─ 必要时运行一次性候选解析器
            ├─ 下载候选媒体
            └─ 宿主验证 / 问用户 / 停止
               ↓
          得到已验证音频
               ↓
          Audio Profiler
            ├─ 容器/编码/时长/采样率/声道/码率
            ├─ RMS/峰值/削波/低音量
            ├─ 语音比例/静音比例/长静音
            └─ 质量标记与置信度
               ↓
          Strategy Selector
            ├─ 模型与语言
            ├─ 是否规范化音量
            ├─ 分块方案
            ├─ VAD 配置档
            ├─ 解码配置档
            └─ 可疑片段重试策略
               ↓
          Whisper Transcription
               ↓
          Transcript Quality Check
            ├─ 空结果/覆盖不足
            ├─ 固定间隔重复/已知幻觉
            ├─ 异常长段/时间戳异常
            └─ 可疑时间区间
               ↓
          通过 / 有限局部重试 / 降级说明
               ↓
          摘要、翻译、导出
```

## 六、最小逻辑边界

这些是职责边界，不要求一开始机械拆成同数量文件。

### 1. Media Recovery Coordinator

只负责媒体获取失败后的短生命周期 Loop：

```text
goal + ExtractionFailure + available_actions
  → DeepSeek
  → structured action
  → host action / candidate parser
  → observation
  → completed / action_required / failed
```

必须具备：

- 当前运行内消息历史；
- 最大模型轮数、工具次数、候选运行次数、下载体积和总耗时；
- 模型、工具和候选运行超时；
- cooperative cancellation；
- 工具参数 schema 校验；
- 未知动作、非法参数和工具异常的结构化 observation；
- 网页、日志、模型输出和 stdout/stderr 长度限制；
- 统一结果，业务层不解析自然语言猜状态。

不具备：

- 通用文件读写；
- Shell、Git、包管理器；
- 插件、MCP、技能；
- 长期聊天历史和上下文压缩。

### 2. 受控媒体恢复动作

第一批动作只围绕真实媒体失败：

- `inspect_failure`：读取结构化、脱敏的失败现场；
- `inspect_runtime`：读取 yt-dlp、Deno/EJS、平台适配器和 Cookie 能力状态；
- `run_ytdlp`：从宿主认可的 profile 中选择 metadata/subtitle/audio、匿名/登录态、平台 fallback 等组合；
- `prepare_ytdlp_update`：检查并准备上游修复，具体是否能同进程切换由实现证据决定；
- `http_request`：对原站和已验证媒体域名执行受限 GET/HEAD/必要 POST；
- `use_browser_session`：只请求宿主用不透明会话执行某个动作；
- `request_youtube_challenge_capability`：调用宿主已有 EJS/PO Token provider 能力，Agent 不接触令牌；
- `download_candidate`：下载经过校验的候选字幕或媒体 URL；
- `validate_media` / `validate_subtitle`：由宿主判断产物是否可用；
- `set_user_message`：更新恢复进度；
- `ask_user`：返回固定 action code 的结构化请求。

`run_ytdlp` 不接受命令字符串；第一版也不开放任意 yt-dlp 参数字典，而是从少量经过验证的 profile 中选择。

### 3. 一次性候选解析器

候选代码只在宿主已有动作不足、且现场属于 HTML/JSON/媒体清单解析问题时使用。

输入：

- 当前页面或 API 响应的脱敏 JSON；
- 原始 URL、平台和允许的资源标识；
- 明确的输出 schema。

输出只能是：

- 字幕/媒体候选；
- 下一次 HTTP request proposal；
- 解析诊断；
- 明确失败。

候选代码不得：

- 读取项目、用户目录、浏览器数据库或其他任务；
- 读取环境变量；
- 直接联网；
- 启动子进程；
- 调用 FFmpeg/yt-dlp；
- 修改 MediaBrief；
- 自行宣布最终成功。

### 4. AudioProfile

AudioProfile 是确定性分析结果，不由模型自由撰写。至少包含：

- 容器、音频编码、时长；
- 原始采样率、声道数、码率；
- 解码后的 RMS、峰值、削波比例和低音量标记；
- VAD 语音时长、语音比例、静音比例和最长静音；
- 可可靠检测的损坏、空音轨或异常短音轨；
- 噪声/音乐等只能近似判断的指标及其置信度；
- 面向用户的质量等级和具体原因。

不得用一个模糊的“好/差”取代原始指标。质量等级必须能追溯到事实。

### 5. TranscriptionStrategy

策略只能从宿主认可的范围或 profile 中产生，至少表达：

- 使用哪个已安装 Whisper 模型；
- 语言自动检测或明确语言；
- 是否需要音量规范化；
- 分块时长和边界处理；
- VAD 配置档；
- 解码/抗幻觉配置档；
- 可疑片段的重试上限和备用配置；
- 选择这些配置的结构化原因。

第一版应保留当前固定策略作为 `default`，再增加少量有证据的 profile，例如：

- `clean_speech`
- `long_form`
- `silence_heavy`
- `low_volume_or_noisy`
- `safe_fallback`

名称可按实现调整，但不能演变成任意参数搜索器。

### 6. TranscriptQualityReport

至少检查：

- 有语音但转录为空或覆盖明显不足；
- 固定间隔短句重复；
- 已知幻觉文本；
- 大段语音区间没有文本；
- 异常长段、时间戳倒退或越界；
- 局部重试前后的变化与最终采用结果。

mlx-whisper 当前不提供的置信度指标不能伪造。质量报告应区分确定事实、启发式信号和未知项。

## 七、执行任务

## Task 1 — 保留媒体失败现场并定义端到端契约

状态：`[x] 已完成（2026-08-13）`

### 目的

先让系统能准确表达“媒体为什么失败、音频是什么情况、准备采用什么策略、转录结果是否可信”。本任务不接 DeepSeek、不运行候选代码，也不改变现有成功路径。

### 范围

- 调整字幕获取的结果边界，至少区分：
  - 确认没有字幕；
  - 字幕下载失败；
  - 字幕解析失败；
  - 媒体元数据提取失败；
  - 登录/权限/限流/challenge 类失败；
  - 用户取消。
- 定义最小结构化契约：
  - `ExtractionFailure`
  - `RecoveryObservation`
  - `AudioProfile`
  - `TranscriptionStrategy`
  - `TranscriptQualityReport`
- `ExtractionFailure` 至少记录：平台、阶段、yt-dlp 版本、脱敏错误摘要、是否有 Cookie/Deno/EJS 能力、已尝试动作和取消状态。
- 敏感字段不得进入日志、数据库、模型上下文或 API 响应。
- 现有“没有字幕 → 下载音频”逻辑保持不变，仅让失败信息不再丢失。
- 增加针对结果分类和脱敏的最小测试。

### 不做

- 不实现通用 Agent Runtime；
- 不调用 DeepSeek；
- 不改变 Whisper 参数；
- 不增加 UI；
- 不实现候选代码。

### 验收

- 真正无字幕和字幕路径故障不再混为一谈；
- 业务层能拿到结构化脱敏失败现场；
- 正常字幕和正常音频路径行为不变；
- 五类契约有明确字段和校验边界；
- 针对性测试通过。

### 完成记录

实际改动：

- 新增 `backend/media_contracts.py`，定义并校验 `ExtractionFailure`、`RecoveryObservation`、`AudioProfile`、`TranscriptionStrategy`、`TranscriptQualityReport`，以及字幕 `found/no_subtitles/failed/skipped` 显式结果边界；后四类本任务只定义契约，不接执行。
- `fetch_subtitles()` 现在区分确认无字幕、元数据失败、字幕下载失败、字幕解析失败、登录/权限/限流/challenge 信号和用户取消；取消直接向上抛，其余故障仍按原逻辑回退音频。
- `ExtractResult` 在音频回退成功后保留字幕路径的脱敏 `ExtractionFailure`；音频随后失败时通过结构化异常保留当前失败和先前现场。
- 统一清理 yt-dlp、FFmpeg、任务错误与队列持久化边界中的 URL 私有部分、认证头、Cookie、Key/Token、浏览器数据库和用户路径；能力状态只记录布尔值，动作只记录固定 code。
- 未接 DeepSeek、未实现候选代码、未改变 Whisper 参数、未修改前端。

验证结果：

- Task 1 针对性测试通过：`48 passed`。
- 覆盖正常字幕、确认无字幕、元数据/下载/解析故障、auth/permission/rate-limit/challenge 分类、取消透传、音频回退、契约不变量和日志/结果脱敏。
- 后端导入检查通过，FastAPI 正常注册 58 条路由。

遗留问题：

- `AudioProfile` 仍为 `not_analyzed`，策略仅能表达当前默认配置，质量报告仍为 `not_evaluated`；按计划分别留给 Task 2–3。
- 媒体恢复 Loop、DeepSeek 和一次性解析器尚未实现；按计划留给 Task 4–5。

---

## Task 2 — 建立确定性 AudioProfile

状态：`[x] 已完成`

前置：Task 1 完成。

### 目的

对下载音频和本地媒体做一次轻量、可解释的体检，为 Whisper 策略选择提供事实。

### 范围

- 复用 FFprobe、PCM 解码和 Silero VAD，计算 AudioProfile；
- 覆盖容器/编码/时长/采样率/声道/码率、RMS、峰值、削波、低音量、语音/静音比例和最长静音；
- 对噪声和音乐等启发式结果标记置信度，不输出虚假精确值；
- 音频损坏、无音轨、全静音或异常短时显式失败/告警；
- 下载音频与本地上传共用同一分析入口；
- 分析失败时返回不完整 profile 并走当前默认转录策略，不能阻断原功能；
- 增加少量针对性样本测试：正常语音、全静音、低音量、削波和长静音。

### 验收

- 每个进入 Whisper 的音频都有可消费的 AudioProfile；
- 质量等级能追溯到具体指标；
- VAD 分析与当前时间轴保持一致；
- 不引入大型通用音频依赖或 DSP 框架；
- 分析异常不会让原本可转录的任务直接失败。

### 完成记录

已完成：

- 新增 `backend/audio_profiler.py`，用 FFprobe 读取容器、编码、时长、采样率、声道和码率；用 30 秒有界 PCM 分块扫描完整时间轴。
- 计算 RMS、峰值、削波比例、低音量、VAD 语音/静音比例和跨块最长静音；噪声只给出低置信启发式，音乐保持未知。
- 全静音、无音轨、异常短和解码失败都产生显式 profile；VAD/分析失败返回 `partial/failed` 并继续现有默认转录，用户取消原样透传。
- URL 下载音频、RSS 媒体和本地上传共用同一分析入口，并在 Whisper 之前将 `audio_profile` 写入任务状态。

验证结果：

- Task 2 针对性测试通过：`27 passed`。
- 覆盖正常语音、全静音、低音量、削波、跨块长静音、VAD 故障、取消透传，以及分析失败不阻断转录。
- 后端导入检查通过，FastAPI 正常注册 61 条路由。

---

## Task 3 — 自适应 Whisper 策略与转录质量复核

状态：`[x] 已完成（2026-08-13）`

前置：Task 1–2 完成。

### 目的

把当前固定 mlx-whisper 参数提升为“默认策略 + 少量受控策略”，并在转录后识别可疑区间。

### 范围

- 把当前固定参数收敛为 `default` 策略，确保行为基线不变；
- 根据 AudioProfile 选择宿主认可的策略 profile；
- 策略至少覆盖长音频、静音占比高、低音量/噪声和安全兜底；
- 记录选择结果和结构化原因，供任务状态和 UI 展示；
- 让 Transcriber 接收已验证的 TranscriptionStrategy，而不是任意参数字典；
- 建立 TranscriptQualityReport；
- 对明确可疑时间区间允许一次有限重试，优先局部而不是整段；
- 重试结果仍异常时保留较可信版本并给出说明，不能无限循环；
- 保持 MLX 单线程亲和、分块取消和模型热复用。

### 验收

- 同一音频在相同 AudioProfile 下产生确定的策略；
- 当前正常音频仍能走接近现有行为的 default/clean 策略；
- 静音占比高或低音量样本采用不同且可解释的策略；
- 重复幻觉、空结果和覆盖不足能进入质量报告；
- 局部重试次数有硬上限；
- 分析/策略层失败时安全回退到当前默认路径。

### 完成记录

实际改动：

- 新增 `backend/transcription_strategy.py`，根据 AudioProfile 确定性选择 `default/clean_speech/long_form/silence_heavy/low_volume_or_noisy/safe_fallback`，只输出宿主白名单配置。
- `Transcriber` 接收已验证的 `TranscriptionStrategy`；固定 profile 映射到分块、overlap、VAD、解码阈值和有界音量规范化，不接受任意 Whisper kwargs。
- 新增 `backend/transcript_quality.py`，检查有语音但空结果、覆盖不足、固定间隔重复、已知幻觉、语音缺口、过长段和时间戳回退/越界。
- 转录器保留 VAD 语音时间线供质量复核；只对第一个明确可疑区间重试一次，且只在候选严格更可信时替换。
- URL、RSS 和本地上传均记录 `transcription_strategy` 与 `transcript_quality_report`；分析/选择失败时退回之前的 600 秒默认路径。
- 保留 MLX 单 worker 线程亲和、分块取消和模型热复用。

验证结果：

- Task 1–5 合并后完整后端测试通过：`202 passed`。
- 覆盖全部策略 profile、选择优先级、分块 overlap/解码 profile 实际执行、八类质量问题、严格候选选择和一次局部重试上限。

遗留问题：

- 任务页的可视化和真实合法站点样本验证按计划留给 Task 6。

---

## Task 4 — 建立受限 Media Recovery Loop 并接入 DeepSeek

状态：`[x] 已完成（2026-08-13）`

前置：Task 1 完成；Task 2–3 可并行准备，但接入完整链路前必须完成。

### 目的

让真实媒体获取失败能经过“判断 → 受控动作 → observation → 再判断”，但不建设通用 Coding Agent。

### 范围

- 实现短生命周期 Media Recovery Coordinator；
- 定义最小模型 client 协议，并实现 DeepSeek/OpenAI-compatible 适配；
- Runtime 只认识媒体恢复 action 和统一 result；
- 支持最大轮数、总超时、单模型/单动作超时、取消和输出限制；
- 注册第一批受控动作：失败现场、运行时状态、yt-dlp profile、更新检查、Cookie 能力、受限 HTTP、下载与宿主验证；
- YouTube EJS/PO Token provider 只作为宿主能力状态和动作，不暴露内部令牌；
- `action_required` 返回最小继续现场并结束当前运行，不保持等待中的长生命周期协程；
- 使用 fake model/fake transport 覆盖多步调用、未知动作、非法参数、动作异常、最大步数、取消和问人；
- DeepSeek 真实连通只做最小人工验证，不把付费请求写入自动测试。

### 验收

- fake model 能完成“读取诊断 → 选择 yt-dlp profile → observation → 再判断 → 完成/问人”的 Loop；
- 正常媒体路径不调用 DeepSeek；
- 模型看不到 API Key、Cookie、Token 和原始认证头；
- Runtime 中没有 Shell、文件编辑、Git、包管理或平台外工具；
- DeepSeek 不可用时保留原有错误和默认流程，不让任务卡死。

### 完成记录

实际改动：

- 新增短生命周期 `MediaRecoveryCoordinator`、闭集 decision/result、模型轮数/动作数/总耗时/单次超时/输出长度预算和 cooperative cancellation；模型只能选择 `RecoveryAction`，未知动作和非法参数只形成脱敏 observation。
- 新增 DeepSeek/OpenAI-compatible 模型适配和发行配置装配；Key 只进入 SDK client，不进入消息、日志、任务状态或 observation。未配置模型时立即返回 `unavailable` 并保留原 `MediaExtractionError`。
- 新增按任务创建的宿主动作执行器，覆盖失败/运行时检查、受控 yt-dlp profile、更新准备、不透明浏览器会话与 YouTube challenge capability、同源受限 HTTP、候选下载、字幕/媒体宿主验证、进度消息和固定用户动作。
- 只有现有字幕与音频路径都失败时才启动恢复 Loop；正常路径不调用模型。模型不能自行宣布成功，只有宿主验证过的字幕或媒体才能返回 `recovered`。
- `action_required` 保存不含 URL、Cookie、Token 的最小继续现场并结束运行；任务记录保留脱敏动作序列，后续可重新入队，不占用常驻协程。

验证结果：

- fake model/fake executor 覆盖多步恢复、未知动作、非法参数、动作异常脱敏、模型轮数上限、取消、问人、未配置模型和宿主验收门槛。
- 正常媒体成功路径不启动恢复；恢复模型不可用时仍抛回原始结构化媒体错误。
- 完整后端测试通过：`164 passed`；后端导入检查通过，FastAPI 正常注册 61 条路由。

后续验证补充：

- 2026-08-13 使用用户提供的 Key，对 `https://api.deepseek.com` 的 `deepseek-v4-pro` 完成最小真实请求；项目适配器成功解析 JSON decision，并返回白名单动作 `inspect_failure`。
- Key 已按用户要求写入 Git 忽略且权限为 `0600` 的本地 `release-config.json`，并内置到本机构建的 `.app`/ZIP；未写入受 Git 跟踪源码、自动测试、日志、任务状态或诊断输出。
- YouTube/Bilibili 平台专用 profile、跨媒体域名约束和一次性 Deno 解析器随后已在 Task 5 完成。

---

## Task 5 — 接入 YouTube/Bilibili 恢复动作与一次性解析器

状态：`[x] 已完成（2026-08-13）`

前置：Task 1、4 完成。

### 目的

在真实站点策略变化时，先使用确定性能力恢复；只有 HTML/JSON/清单结构问题才启用一次性候选解析器。

### 范围

- 为 YouTube/Bilibili 定义少量可验证的 yt-dlp profile，不开放任意参数；
- 处理上游已发布修复、匿名/登录态差异、客户端/EJS/PO Token capability、限流和常见 HTTP 拒绝；
- 保留完整脱敏工具序列和 observation；
- 实现受限 HTTP 资源获取和候选媒体下载；
- 实测选择 Deno 作为唯一候选语言/运行时，或明确判定暂不启用；
- 候选解析器只使用 stdin/stdout JSON，不直接访问文件、网络、环境或子进程；
- 候选发现下一请求时只输出 request proposal，由宿主校验并执行；
- 限制候选源码大小、输入/输出大小、运行时间、内存和修正次数；
- 候选结束后删除源码和临时输入，除非用户明确保留脱敏诊断；
- 最终字幕/音频必须由宿主验证。

### 验收

- 至少一个模拟 YouTube 失败能通过受控配置或宿主 capability 得到明确恢复/停止结论；
- 至少一个模拟 Bilibili 页面/API 结构变化能完成“获取资源 → 生成解析器 → proposal/结果 → 宿主验证”；
- 候选代码无法读取 Key、Cookie、用户目录、项目源码或其他任务；
- 候选代码无法直接联网和启动子进程；
- challenge、DRM、会员或无访问权问题不会被错误标记为解析成功；
- 运行时边界在 macOS PyInstaller 目录结构中有最小真实验证。

### 完成记录

实际改动：

- YouTube 新增 `youtube_android_anonymous`、`youtube_web_ejs`、`youtube_browser_session` 三个宿主白名单 profile；Bilibili 新增匿名/不透明浏览器会话两个 profile。模型只能传 profile 名，不能传 yt-dlp 参数、命令或认证材料。
- 受限 HTTP 只允许来源域名及 YouTube/Bilibili 固定媒体域名后缀，拒绝用户信息、本机/非公网 IP 和任意第三方域；响应正文只保存在当前运行内，模型只看到脱敏结构预览和 host 分配的 response/candidate/proposal ID。
- 新增一次性 JavaScript `CandidateParserRuntime`，只使用 Deno stdin/stdout JSON；以 `--no-prompt --cached-only` 且不授予任何 allow 权限运行，不开放文件、网络、环境、子进程、FFI 或 import。没有 Python/宿主 `exec()` 兜底。
- 限制候选源码 20KB、输入 256KB、输出 64KB、V8 heap 128MB、单次 3 秒和每任务一次运行；源码和宿主临时 stdout/stderr 在运行后删除，输入只走 stdin。
- 候选输出只能是媒体/字幕候选、GET/HEAD request proposal 或明确失败；proposal 仍须宿主校验并执行，最终字幕/音频仍须通过宿主非空、大小、音轨和时长验证。
- DRM 新增显式失败分类；登录、权限、challenge、DRM、会员/地区限制类现场禁止进入候选解析器，不能伪装成结构解析成功。

验证结果：

- 使用本机 Deno 2.7.9 真实验证：候选代码读取环境变量、`/etc/passwd`、联网和启动子进程均被拒绝。
- 使用现有 `dist/MediaBrief.app/Contents/MacOS/deno` 再次验证相同四类边界，`sandbox_verified=True`，覆盖实际 macOS PyInstaller 目录结构。
- 模拟 YouTube challenge 通过指定匿名 Android profile 得到宿主验证产物；任意 profile 名被拒绝。
- 模拟 Bilibili JSON 结构变化完成“响应 → Deno 解析 → bilivideo 白名单候选 → 宿主下载 → 媒体验证”；无关域名、越权源码和访问控制现场均被拒绝。
- 完整后端测试通过：`200 passed`；后端导入检查通过，FastAPI 正常注册 61 条路由。

遗留问题：

- 未对当前真实 YouTube/Bilibili 公网页面发起恢复请求，避免把易变站点状态和付费模型调用写进自动验证；真实合法样本留给 Task 6。
- Deno 候选解析器当前严格每任务一次、不缓存源码；是否需要脱敏缓存须在 Task 6 真实样本后再判断。

---

## Task 6 — 产品接入与真实场景验证

状态：`[x] 已完成（2026-08-13）`

前置：Task 1–5 完成。

### 目的

把恢复过程、音频分析、Whisper 策略和质量结果接入现有任务体验，并用真实合法样本判断是否真正提高成功率和转录可靠性。

### 范围

- 通过现有 task_store/队列 SSE 展示：
  - 媒体恢复进度；
  - 音频质量摘要与原因；
  - 采用的 Whisper 策略及原因；
  - 转录质量告警和是否进行了局部重试；
  - 最终恢复、降级或停止说明。
- 动态说明只展示纯文本，限制长度并清除 HTML/控制字符；
- 用户动作只使用固定 action code：允许本次浏览器会话、登录后重试、重新入队继续、放弃、复制脱敏诊断；
- 用户拒绝登录态后，同一任务不得反复请求；
- 使用少量公开、合法、当前可访问样本验证：
  - YouTube 有字幕；
  - YouTube 无字幕需音频；
  - YouTube challenge/登录/限流类失败；
  - Bilibili 正常音频；
  - Bilibili 页面/API 结构变化模拟；
  - 长音频、静音占比高、低音量和重复幻觉样本；
  - 明确不可恢复的会员/私密/DRM 场景。
- 记录脱敏工具序列、候选轮数、AudioProfile、TranscriptionStrategy、QualityReport、耗时和 DeepSeek 调用次数；
- 真实样本后再判断是否需要候选代码本机缓存，默认仍不缓存。

### 验收

- 正常成功路径没有因为获取 Agent 变慢；
- 至少完成一条 YouTube 和一条 Bilibili 的真实成功验证；
- 至少完成一次接近真实的站点失败恢复或明确停止；
- 至少两种明显不同音频产生不同、可解释的 Whisper 策略；
- 至少一个可疑转录区间被识别并有限重试；
- 用户能看懂“音频质量如何、采用了什么策略、为什么”；
- Agent、候选运行时或音频分析失败时，原有功能仍可安全降级。

### 完成记录

实际改动：

- 新增任务“处理详情”面板，通过现有任务状态、SQLite、队列和 SSE 展示媒体恢复状态与动作序列、AudioProfile 指标与原因、TranscriptionStrategy 配置与原因、TranscriptQualityReport 告警和局部重试结果；正常成功路径不启动恢复模型。
- 前端接入中英日韩四语文案。动态说明先剥离 HTML、控制字符并限长，且只作为 React 文本节点渲染；后端持久化、SSE、API 和复制诊断边界同样执行纯文本化、脱敏和限长。
- 新增固定恢复动作端点 `POST /api/task/{task_id}/recovery-action`，只接受 `enable_browser_session`、`login_then_retry`、`requeue_continue`、`abort`、`copy_sanitized_diagnostic` 五个 code，拒绝未知动作和额外 payload。
- 继续操作只原子复用宿主数据库中既有的媒体任务 payload 重新入队；HTTP 不能提交任务类型、URL 或任意 payload。浏览器会话只以布尔能力开关传入任务上下文，模型和前端都看不到 Cookie/Token。
- `action_required` 不保留等待协程；动作锁和状态消费阻止双击重复入队。用户拒绝登录态后写入 `recovery_login_declined`，同一任务后续不再提供两种登录动作。
- 新增 11 个端到端产品场景，覆盖字幕快路径、无字幕音频体检、不同音频策略、YouTube challenge/login/rate-limit、Bilibili 结构变化候选链、DRM/会员/私密停止、重复幻觉恰好一次局部重试，以及动态文本持久化脱敏。

真实合法样本验证：

- YouTube 公开 Blender Sintel 样本实际走 `VideoProcessor.fetch_subtitles()`，取得英文字幕并保留约 888 秒媒体时长。
- YouTube 公开 Big Buck Bunny 样本实际确认无字幕后走音频下载与宿主验证，得到约 634.6 秒有效音频；没有误启动恢复 Loop。
- Bilibili 公开 CC-BY Big Buck Bunny 样本实际完成元数据提取、音频下载和宿主验证，得到约 634.2 秒有效音频。
- 当前站点请求中实际观察到 Bilibili HTTP 412，并保留为明确失败而非伪装成功；challenge、登录、限流、页面结构变化和访问控制场景使用接近真实的受控 transport/页面数据完成恢复或停止验证。
- 长音频、静音占比高、低音量样本产生不同且可解释的白名单策略；固定间隔重复/已知幻觉样本只触发一个可疑区间、一次局部重试，并在候选严格更可信时才替换。

验证结果：

- 完整后端测试通过：`221 passed`；FastAPI 导入正常，共 62 条路由。
- 前端 `pnpm build` 通过（TypeScript 与 Vite production build）。
- 当前 yt-dlp `2026.07.04` 下完成上述真实公开样本检查。
- 候选解析器继续保持每任务最多一次且不缓存；本轮证据不足以证明本机缓存有必要，因此维持默认不缓存。

已知限制：

- 已完成 DeepSeek `deepseek-v4-pro` 最小真实连通与结构化决策验证；Key 按用户要求只持久化在 Git 忽略的本地发行配置和本机构建产物中。自动化仍使用 fake model/transport，避免测试套件持续产生付费请求；多步预算、超时、取消和 Loop 由确定性测试覆盖。
- 未主动寻找或绕过真实 DRM、会员、私密、风控或登录内容；这些类别只验证明确停止和固定用户动作，符合本计划的访问控制边界。

---

## Task 7 — 宿主自动换模型源，现有 Agent 能看见运行环境

状态：`[x] 已完成（2026-08-13）`

前置：Task 1–6 已完成。不要重写恢复 Loop、不要搬迁已有媒体工具、不要重做音频策略。

### 目的

把“开箱即用”和现有轻量 Agent 接上：能确定的环境问题由宿主直接处理；Agent 诊断媒体失败时，也能看到模型、Deno、MLX、FFmpeg 现在是什么状态。

### 范围

- 默认模型下载由宿主按官方 Hugging Face → 国内镜像自动切换；用户不用填 Endpoint，发行版也不为此打开设置。
- 官方源失败后立刻换下一个源，不要先干等退避；一轮源都失败后再退避重试，并标记 `degraded`。
- 下载状态记录当前源、已尝试的源和最近错误，供 UI、诊断和 Agent 使用。
- 收敛一份运行时画像：FFmpeg、FFprobe、Deno、MLX、yt-dlp、默认 Whisper 模型。
- 现有 `inspect_runtime` 读取这份画像，而不是只返回 yt-dlp/Cookie 布尔值。
- `/api/environment-status` 返回同一份画像。
- 不把媒体恢复工具拆包重写；不新增大而全的 Agent 框架；不把换源做成用户配置项。

### 不做

- 不重做 Task 1–6 已验收的恢复动作、候选解析器、音频策略和质量复核；
- 不建设通用 Coding Agent 或任意 Shell；
- 不把 HTTP 白名单立刻扩成全网；
- 不在本任务做下载页、五人验收或静默应用更新。

### 验收

- 不传 `hf_endpoint` 时，官方源失败会自动改走国内镜像。
- 显式传入的 `hf_endpoint` 仍只使用该源。
- `default_model_status()` / 环境画像能看出当前源和失败原因。
- `inspect_runtime` 的 observation 包含 Whisper 准备状态和组件可用性。
- 现有媒体恢复测试和 Whisper 模型选择契约继续通过。

### 完成记录

实际改动：

- `whisper_models.py` 默认下载顺序改为官方 Hugging Face → `https://hf-mirror.com`。官方源失败后立刻换下一个源，不先退避；一轮源都失败后再退避并标记 `degraded`。
- 显式传入的 `hf_endpoint` 仍只使用该源，不会被自动换源覆盖。
- `default_model_status()` 增加 `endpoint` 和 `tried_endpoints`。
- 新增 `runtime_environment.py`，收敛 FFmpeg、FFprobe、Deno、MLX、yt-dlp 和默认 Whisper 状态。
- 现有 `inspect_runtime` 和 `/api/environment-status` 读取同一份画像。`start.py` 为随包 Deno 写入 `AIT_DENO`。
- 未搬迁媒体恢复工具，未重写 Loop。

验证结果：

- 针对性测试覆盖默认换源顺序、立刻切镜像、显式源不换源、环境观察包含 Whisper 源、`inspect_runtime` 把画像交给 Agent。
- 完整后端测试通过：`233 passed`。

遗留问题：

- 关窗确认还不会说明正在运行的任务会被停止。
- 降级转录结果尚未在成品上标明应急质量。
- HTTP / yt-dlp profile 仍按 YouTube/Bilibili 收口；未知站点仍主要依赖通用抽取。
- 下载页、干净 Mac 和五人验收仍在 `ProductizationPlan.md` Task 4。

## 八、当前明确不要做

- 通用编程 Agent、任意 Shell 或仓库维护 Agent；应用内轻量命令 Agent 继续做；
- 通用权限策略引擎或任意 Shell；
- 让候选代码修改项目、应用或用户文件；
- 多语言候选运行时；
- 自动缓存、共享或远程下发模型生成代码；
- Hosted AI 服务、账号、兑换码、订阅或许可证；
- Agent 聊天页、多 Agent、长期记忆、向量数据库；
- 通用浏览器控制或读取原始 Cookie；
- 任意 FFmpeg/yt-dlp 命令字符串；
- 自动尝试大量 Whisper 参数的搜索器；
- 自研降噪、源分离或通用音频增强框架；
- 绕过 DRM、会员、私密或法律/地区访问限制；
- Windows、Intel Mac 或 App Store 工作。

## 九、复杂度约束

1. 每个新增抽象必须直接服务于媒体获取、运行环境准备、音频分析、转录策略或质量复核。
2. 没有真实失败类别支撑的工具不加入第一版。
3. 没有 AudioProfile 指标支撑的 Whisper 策略不加入第一版。
4. 候选代码能力验证失败时可以推迟，不能因此建设更大的通用沙箱。
5. 不为了“以后可能复用”提前建设插件、持久会话、通用权限或工作流系统。
6. 测试只覆盖真实边界和回归风险，不搭通用 Harness。
7. 安全简化靠减少能力，不靠放宽权限。

## 十、执行规则

每位接手 Agent 必须：

1. 阅读根目录 `AGENTS.md` 和本文件。
2. 只执行一个标记为“下一个任务”的任务，不顺手开始后续任务。
3. 开始前检查 `git status --short`，保留用户已有修改。
4. 复用现有 yt-dlp、Cookie、FFmpeg/FFprobe、Silero VAD、mlx-whisper、取消和任务状态能力。
5. 不做无关重构，不搭通用测试脚手架。
6. 不把真实 Key、Cookie、Token、账号信息或私密媒体写入 Git、日志、测试或本计划。
7. 把模型输出、网页内容、工具 observation 和候选代码视为不可信输入。
8. 完成任务规定的针对性验证。
9. 把任务状态和“实际改动/验证/遗留问题”写回本文件。
10. 不自行提交、推送或发布，除非用户明确要求。

## 下一位 Agent 的第一条指令

> Task 1–7 已完成。不要重写恢复 Loop、候选解析器、音频策略或模型换源。后续只处理真实使用中的具体回归，或 `ProductizationPlan.md` 里尚未完成的产品化缺口（关窗说明、降级结果标记、真实发行配置验收、下载页）。不要建设通用编程 Agent，也不要把付费请求写入自动测试。
