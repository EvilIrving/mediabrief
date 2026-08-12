# MediaBrief 自适应媒体任务恢复与转录执行计划

更新时间：2026-08-13  
当前状态：方案已重新收敛，尚未开始实现  
执行方式：一次只完成一个任务；完成并验收后再开始下一项

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

> 模型负责理解现场、选择受控动作和在必要时生成一次性媒体解析器；宿主负责权限、网络、登录态、资源、音频分析、Whisper 参数边界、执行和结果验证。

## 二、范围边界

### 这是要做的

- 一个短生命周期、有步骤与资源预算的媒体恢复 Loop；
- 对 yt-dlp 完整脱敏诊断的保留和分类；
- YouTube/Bilibili 的受控恢复动作；
- 必要时生成一次性 HTML/JSON/媒体清单解析器；
- 确定性的音频质量分析；
- 从宿主认可的配置中选择 Whisper 策略；
- 转录质量报告和有限的局部重试；
- 需要登录、授权或用户操作时返回结构化请求；
- 在 UI 中解释音频情况、采用的策略、恢复过程和结果。

### 这不是要做的

- 通用 Coding Agent、通用 Shell、代码编辑器或仓库维护 Agent；
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

## 四、当前代码事实

### 媒体获取

- `backend/sources.py` 目前是固定的“字幕 → 音频 → Whisper”编排。
- `backend/video_processor.py::fetch_subtitles()` 会把不同异常统一压成“没有字幕”，Agent 目前看不到真实失败现场。
- `video_processor.py` 已有 yt-dlp、Cookie、FFmpeg/FFprobe、超时、取消和媒体时长验证能力，应复用这些能力。
- `use_auto_detect_browser_cookies()` 已能按任务临时启用浏览器 Cookie；不需要先建设通用浏览器会话代理。
- `backend/yt_dlp_updater.py` 当前每周检查 PyPI stable，新版本下次启动生效；它能处理“上游已经发布修复”的一部分情况，但不是失败时即时恢复机制。
- `backend/platforms/youtube.py` 当前固定了 player client 和 EJS 组件，配置本身也可能随上游策略变化而老化。
- `start.py` 和打包流程已经携带 Deno，主要供 yt-dlp EJS 使用；能否同时作为候选解析器运行时必须单独验证，不能直接假定安全。

### 音频与转录

- 当前实际转录引擎是 `mlx-whisper`，所有 MLX 调用固定在单 worker 线程以满足 Metal 线程亲和。
- `backend/transcriber.py` 已有固定十分钟分块、块间取消、静音能量检测、Silero VAD、固定抗幻觉阈值和重复幻觉过滤。
- 当前 VAD 已计算每块语音时长和语音比例，但这些信息只写日志，没有汇总成可消费的 AudioProfile。
- 当前 Whisper 参数基本固定，没有根据音频质量选择策略，也没有结构化记录“为什么采用这个策略”。
- 当前有重复幻觉过滤，但没有完整 TranscriptQualityReport，也没有针对可疑时间段的受控重试。
- `probe_duration()`、`decode_audio_chunk()` 和 Silero VAD 可以作为音频分析基础，不需要引入通用 DSP 框架。

### 任务与 UI

- `task_store.py`、SQLite 和队列 SSE 已能持久化并广播任务状态。
- 当前队列状态主要是 queued/processing/completed/error/cancelled，没有现成的常驻暂停会话。
- 动态说明应继续走现有任务状态和 SSE；常见提示仍用四语 i18n 做快速路径与模型失败兜底。

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

## Task 1 — 保留媒体失败现场并定义端到端契约（下一个任务）

状态：`[ ] 未开始`

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

待执行 Agent 填写：实际改动、验证结果、遗留问题。

---

## Task 2 — 建立确定性 AudioProfile

状态：`[ ] 未开始`

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

待执行 Agent 填写。

---

## Task 3 — 自适应 Whisper 策略与转录质量复核

状态：`[ ] 未开始`

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

待执行 Agent 填写。

---

## Task 4 — 建立受限 Media Recovery Loop 并接入 DeepSeek

状态：`[ ] 未开始`

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

待执行 Agent 填写。

---

## Task 5 — 接入 YouTube/Bilibili 恢复动作与一次性解析器

状态：`[ ] 未开始`

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

待执行 Agent 填写。

---

## Task 6 — 产品接入与真实场景验证

状态：`[ ] 未开始`

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

待执行 Agent 填写。

## 八、当前明确不要做

- 通用 Coding Agent Harness；
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

1. 每个新增抽象必须直接服务于媒体获取、音频分析、转录策略或质量复核。
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

> 阅读根目录 `AGENTS.md` 和 `Plan.md`，只执行 **Task 1 — 保留媒体失败现场并定义端到端契约**。先让字幕/媒体提取明确区分“确认没有字幕”和“提取路径失败”，保留脱敏的 yt-dlp/运行时现场；定义最小 `ExtractionFailure`、`RecoveryObservation`、`AudioProfile`、`TranscriptionStrategy`、`TranscriptQualityReport` 契约。本任务不要调用 DeepSeek，不要实现候选代码，不要改变 Whisper 参数，不要修改前端。完成后运行针对性测试，并把实际改动、验证结果和遗留问题写回 Task 1 完成记录。
