# MediaBrief 应用内轻量 Harness

更新时间：2026-08-14

这是 AI Native 层的架构源文件。产品层见 `ProductizationPlan.md`。媒体恢复是本 Harness 的第一个场景：恢复 Loop、闭集动作、一次性候选解析器、音频策略与质量复核已经落地，架构契约在代码与测试里，本文件不再重复。

对照阅读过 `/Users/actor/Documents/code/python-learns/packages/grok-build`。借鉴的是它的 **loop + 闭集 Tool + 宿主执行** 分层，不是它的产品形态。

---

## 一、这是什么

MediaBrief 内置一个短生命周期命令 Harness。模型在软件运行过程中做分析、判断和轻量维护；用户不必理解 yt-dlp、FFmpeg、模型源或环境变量。

```text
现场 / 定时触发
        ↓
   Harness loop
        ↓
  只选择已登记 Tool
        ↓
  宿主执行并验证
        ↓
  脱敏 observation
        ↓
  再判断 / 完成 / 问人 / 停止
```

同一批 Tool 有两个入口：

- **宿主直接调**：规则已经够用时（启动检查、官方源失败换镜像、下载续传、每周查 yt-dlp）。
- **模型选了再调**：现场需要判断或组合时（抽取失败像解析器过期、镜像也挂了、FFmpeg 报错要先看日志再决定修哪一个）。

两个入口走同一实现。模型不会比宿主更会「换镜像」，它只是能在诊断中按下已经存在的按钮。

---

## 二、这不是什么

本产品不是编程 Harness，也不做通用 Agent 平台。

明确不做：

- 通用 Shell、仓库编辑、代码补丁、测试运行器
- 任意写文件、任意改环境变量、任意 `pip` / `brew`
- MCP、插件市场、技能系统、多 Agent、子 Agent
- 长期会话、上下文压缩、向量记忆、工作流引擎
- 通用 OS 沙箱、通用浏览器自动化
- 让模型修改 MediaBrief 源码、安装目录或用户项目
- 绕过 DRM、会员、私密内容或访问控制

Grok Build 是终端里的编程 Agent（读仓库、改文件、跑命令）。我们只借它的驾驭方式：模型只选 Tool，宿主管权限、执行和验证。

---

## 三、从 Grok Build 借鉴什么

源码树：`packages/grok-build`。分层大致是：

| 层 | crate | 对我们有用的部分 |
|---|---|---|
| Agent 装配 | `xai-grok-agent` | 一次运行绑定「目标 + 本轮可见 Tool + 策略」，不是把场景写进 loop |
| 生命周期钩子 | `xai-agent-lifecycle` | 贡献者能观察 turn 起止，但不拥有 loop 控制权 |
| 采样 / 重试 | `xai-grok-sampler` | 模型调用与 Tool 执行分开；取消、超时、失败分类 |
| Tool 协议 | `xai-tool-protocol` | 稳定 id、能力声明（只读 / 可取消 / 超时 / 并发） |
| Tool 类型 | `xai-tool-types` | `name` + 描述 + 参数 schema；标识符闭集 |
| Tool 运行时 | `xai-tool-runtime` | `Tool` 契约、`ToolDispatch`、typed args、统一错误、observation |
| Tool 实现 | `xai-grok-tools` | 每个能力一个小实现；注册表按 pack 装配；`should_list` 控制本轮可见集 |
| 密钥处理 | `xai-grok-secrets` | 离开工具边界的文本先脱敏 |

### 要借的原则

1. **Loop 不认识具体能力。** Grok 的 `ToolDispatch` 只按 id 调 Tool，drain 到一条 Terminal 结果。我们的 coordinator 也不该认识 YouTube 或 FFmpeg。
2. **Tool 是一等契约。** 每个 Tool 自带稳定名字、参数类型、能力标记和执行函数。不是 loop 里的一长串 `if action == ...`。
3. **参数在边界校验。** Grok 用 typed `Args` + JSON schema；非法参数变成 `InvalidArguments`，不进业务。
4. **给模型的是观察，不是内部对象。** `ToolError.detail` 明确写给模型看。我们继续走脱敏摘要，不回传 Cookie、Key、路径秘密或整段原始日志。
5. **错误要分类。** 参数错、权限拒绝、超时、取消、执行失败必须分开，模型才能决定下一步，而不是看见一句「出错了」。
6. **本轮可见 Tool 可以裁剪。** Grok 的 `should_list` 按 turn 上下文隐藏 Tool。媒体恢复轮不必列出「写某个环境变量」；环境维护轮不必列出候选解析器。
7. **只读与变更分开。** Grok 用 `is_read_only` / `tool_scope`。观察类 Tool 可并行；变更类必须串行、可取消、有预算。
8. **问人是 Tool，不是聊天。** Grok 的 `AskUserQuestion` 发结构化问题，按钮由宿主渲染。我们继续只用固定 `action code`，模型只写说明文字。
9. **宿主也可以不经过模型调用同一 Dispatch。** Grok 的 `call_terminal` 就是这条路。换镜像、续传、定时更新走这里。
10. **重复空转要停。** Grok 有 doom-loop 检测。我们规模小，用「同一 Tool + 同一参数连续失败 N 次则停止」即可，不上服务端检测。

### 明确不借

| Grok Build | 为什么不借 |
|---|---|
| `read_file` / `search_replace` / `bash` | 编程 Agent 的主工具 |
| MCP、插件、Skills、Marketplace | 通用扩展平台 |
| 子 Agent、Orchestrator、Workspace | 多代理与仓库工作区 |
| 长期会话、compaction、产品 Memory | 我们是短任务，不是结对编程 |
| 通用 Sandbox / Computer Hub | 安全靠减少能力，不靠再造沙箱 |
| JSON-RPC Tool 协议、流式 progress 栈 | 第一版不需要跨进程 Tool 服务器 |
| 行为版本、多 toolset preset | 我们只有一份产品 Tool 目录 |

候选解析器（一次性 Deno、stdin/stdout、无文件无网络）已经是本产品的专用 Tool，不是 Grok 的 bash。它继续留在媒体 pack 里，不升级成通用代码执行。

---

## 四、两层承重结构

```text
┌─────────────────────────────────────────────┐
│  场景（本轮目标 + 可见 Tool 包 + 成功条件）   │
│  媒体恢复 / 依赖维护 / 环境诊断 …            │
└───────────────────┬─────────────────────────┘
                    │ 装配
┌───────────────────▼─────────────────────────┐
│  Harness 内核                                │
│  loop · 预算 · 取消 · 问人 · 模型适配         │
└───────────────────┬─────────────────────────┘
                    │ Dispatch
┌───────────────────▼─────────────────────────┐
│  Tool 目录                                   │
│  观察 · 维护 · 媒体 · 与人                   │
│  每个 Tool 小而专用，宿主和模型都能调         │
└─────────────────────────────────────────────┘
```

文件仍按仓库约定平铺在 `backend/`，用模块名和 import 表达分层，不建 `harness/` 包，也不引入插件系统。

建议职责（实现时可改名，不可把三层揉回一个「媒体恢复」文件）：

| 职责 | 现有近似 | 目标 |
|---|---|---|
| 数据契约 | `media_contracts.py` 里混着恢复动作 | 通用 observation / 决策 / 预算；场景枚举各自独立 |
| Loop 内核 | `media_recovery.py` 的 `MediaRecoveryCoordinator` | 不写死媒体提示词和成功条件 |
| 模型适配 | `OpenAICompatibleRecoveryModel` | 只负责 decide，system 由场景注入 |
| Dispatch / 目录 | `MediaRecoveryActions.action_specs` + 大 switch | 登记、裁剪本轮可见集、按 id 执行 |
| 各 Tool | 全堆在 `media_recovery_actions.py` | 一个能力一个函数或模块，实现可被宿主直接 import |
| 场景装配 | `media_recovery_service.py` | 「这一次要解决什么」+ 可见 pack + 成功条件 |
| 产品接入 | `pipeline.py` / `sources.py` 的 `recover_media` | 失败或定时器触发一次短运行 |

---

## 五、Harness 内核契约

一次运行是短生命周期对象，不常驻、不跨任务聊天。后台常驻的是触发点与宿主执行侧，不是模型会话：每次触发新开一次短会话，运行结束即丢弃，上下文不跨运行累积、不保存记忆。需要留档的历史交给软件的日志系统（将来的事），不进模型上下文，也不靠对话记忆续上下文——要继续就开新会话，现场靠持久化的最小状态（如 `recovery_continuation`）恢复，不靠聊天记录。

### 输入

- **目标**：本轮要完成什么（找回已验证音频、让默认模型就绪、解释并修复环境）。
- **现场**：脱敏后的失败 / 状态快照。
- **可见 Tool 表**：本轮允许的 id 与参数 schema。
- **预算**：模型轮数、动作次数、总时长、单次模型超时、单次 Tool 超时、防空转阈值（见循环）。任何触发都有上界：媒体恢复按任务（每任务最多一轮、默认 5 turn）；环境场景按失败事件触发，但同一失败条件在退避期内重复触发由宿主节流，模型不主动发起新 run。
- **取消令牌**：与现有 `cancellation.py` 同一套。

### 循环

```text
for turn in 预算:
    取消检查
    decision = model.decide(messages, 可见 Tool 表)
    若 completed → 问宿主是否已验证成功条件；未验证则回 observation，继续
    若 failed / 需要停止 → 结束
    若 action 不在可见表 → observation(unknown_action)
    若同一指纹连续失败达阈值 → 停止（防空转，原因记为 `doom_loop`）
    observation = dispatch.execute(action, args)
    若 Tool 请求问人 → 结束协程，保存最小继续现场
    把 observation 追加进 messages
```

内核只理解 `action` / `completed` / `failed`。它不知道「音频文件」或「Hugging Face」。成功条件由场景的 `verified_result`（或等价物）判定：媒体场景要有宿主验证过的字幕或音频；维护场景要有宿主验证过的组件状态。

**触发与观察分离。** 任何可能超过单次预算的操作（下载、等待、更新）都拆成「触发 + 宿主后台继续 + 事后观察」：模型调触发类 Tool 拿到「已启动」就结束本轮，之后用观察类 Tool 复核结果。loop 里没有阻塞式 wait——模型不等待下载、不等待长任务；宿主侧门闩（如默认模型就绪）在 loop 之外，重构不得把它拖进 loop。

**防空转阈值。** 指纹 = Tool id + 规范化参数（参数排序、去空白后比对）；只有 `observation.status == failure` 算失败，成功但未达成目标不算。同一指纹连续失败达到默认阈值 `2`（场景可覆盖，写进预算契约）即停止本轮，原因记为 `doom_loop`。借鉴 Grok：默认值取小、每项独立默认、可覆盖，停止是带原因的明确终止类别，不是模糊的「出错了」。

### 模型

- 只输出结构化 JSON：选一个已列出的 Tool，或宣布完成 / 失败。
- 禁止要密钥、Cookie、Shell、源码或任意路径。
- 未配置模型时立即 `unavailable`，不改变既有失败，不假装成功。
- 当前验证阶段继续直连 DeepSeek；Key 不进 Git。

### 问人

已确认决策：

- 按钮只能绑定宿主认可的固定 action code。
- 模型可以写说明，不能发明新按钮或带任意 payload。
- `action_required` 结束当前运行并保存最小继续现场；用户操作后再入队。

---

## 六、Tool 层契约

Tool 是本软件对外暴露给模型和宿主的最小能力。以后会有几十个，每一个都必须小、专用、可单独测试。

### 每个 Tool 必须声明

- **稳定 id**：`snake_case`，例如 `inspect_runtime`、`switch_model_source`。
- **一句话说明**：写给模型，说明何时用、不能做什么。
- **参数 schema**：闭集；没有的字段就是没有。
- **能力**：`read` 或 `mutate`；是否可取消；默认超时。
- **执行函数**：宿主和模型走同一函数。
- **observation**：`status` + `code` + 脱敏 `summary`。变更类成功时，summary 必须是宿主已验证的事实，不能是「我已经试过了」。

### 硬规则

1. 一个 Tool 只做一件宿主允许的事。换镜像、续传、更新 yt-dlp 是三个 Tool，不是一个 `maintain_environment`。粒度按宿主授权边界切，不是按功能、平台或实现细节：参数 / 风险 / 观察语义不同就是不同 Tool；信任边界变化（受信二进制 vs 不可信产物）就是不同 Tool；没有调用方需要独立调它，就不是 Tool。功能（媒体恢复）是场景，平台（B站 / YouTube）是同一批 Tool 的不同失败实例，实现细节（`next_download_endpoint`）都不是 Tool。
2. 没有「任意命令」「任意 URL」「任意文件路径」参数。HTTP 必须落在本轮允许的域名或宿主提出的 proposal 上。
3. 写环境变量如果存在，必须是「写这个已知键」的专用 Tool，键名闭集。
4. 给模型的文本先脱敏。沿用 `sanitize_diagnostic` / `sanitize_plain_text`；必要时再收紧（Cookie、Token、本机绝对路径、完整 stderr）。
5. 观察类默认只读、可并行；变更类串行。
6. 先有会以 Tool 契约调用它的场景，再登记。宿主内联裸逻辑不算调用方——宿主调的是实现，不是 Tool 契约；抽成 Tool 的触发，是出现第二个会以 Tool 契约调用它的调用方（通常是模型在某个真实场景里经 Dispatch 调它），此时宿主改调 Dispatch 只是抽取后的附带统一，不是理由。不要为「以后可能用到」先造 Tool。
7. 测试只打契约和真实边界：参数拒绝、超时、取消、脱敏、宿主验证。不为 Harness 搭通用测试框架。
8. 落进持久化字段的 code 是跨版本线上格式：旧版本写入、新版本读取，读端是严格枚举 round-trip。改名必须走 §七 末尾的变更纪律和同步清单；当前阶段（还没有不可清理的真实用户数据）允许改，正式用户数据落地后冻结：只增不改。
9. 观察尽量全，操作严格闭集。模型的视野覆盖整个软件的可脱敏运行状态（任务、队列、模型、依赖、日志尾部、环境画像）；但任何操作都必须走登记的 Tool，没有绕过 Tool 的操作入口。给模型的是「看得到全部脱敏状态，动作面只有 Tool 列表」，不是「只能看到一部分」。
10. 单次 Tool 执行必须落在预算内。任何可能超时的操作一律「触发 + 宿主后台继续 + 事后观察」，wait 类工具不进 loop；宿主侧门闩（如默认模型就绪）保持在 loop 之外，重构不得把它拖进 loop。

### 双入口

```text
宿主（启动 / 定时 / 已知失败）          模型（诊断 / 组合判断）
              \                          /
               \                        /
                └── dispatch.execute ──┘
                          │
                     同一个 Tool
```

例子：官方 Hugging Face 失败后，下载循环直接调 `switch_model_source`，不必先问模型。模型的入口要等一个会把「官方源失败、镜像未试」放进失败现场的场景出现（见硬规则 6）——今天的媒体恢复现场是抽取类失败，不含模型源状态，模型没有理由按这个按钮。

今天还不是这样：换源和续传写在 `whisper_models.py` 里，恢复 loop 看不见；`prepare_ytdlp_update` 只是催一下更新器。目标是把这些实现收成 Tool，宿主改调 Dispatch，而不是复制一份给模型。

---

## 七、Tool 目录（按簇生长，不一次造齐）

名字是产品词汇，实现时可以更短。未列出的不存在。

这句的「短」只适用于代码内标识符、函数名与 UI 文案；凡是会写进持久化字段的字符串值（`recovery_*`、`recovery_continuation`、observation 的 `action`/`code`，以及未来的 Tool id）是跨版本线上格式，改名纪律见本节末尾。

### 观察（只读）

| id | 做什么 | 现状 |
|---|---|---|
| `inspect_runtime` | 读 FFmpeg / Deno / MLX / yt-dlp / Whisper 同一份画像 | 已有，摘要偏短 |
| `inspect_failure` | 读本轮脱敏失败现场 | 已有，仅媒体抽取 |
| `inspect_model_status` | 默认模型是否就绪、当前源、已试源、最近错误 | 事实在 `whisper_models.default_model_status()`，未独立成 Tool |
| `inspect_update_status` | yt-dlp（及以后其他依赖）的版本与更新状态 | 事实在 `yt_dlp_updater.update_status()` |

观察簇与维护簇同门槛：没有真实失败类别之前不加。「最近报错」现在塞进失败摘要已够用；`inspect_logs` 需要新建「有界、已脱敏的日志尾部读取器」——那是新基础设施，等有真实失败类别再建，现在不登记。

### 维护（变更，宿主已有逻辑的优先抽）

| id | 做什么 | 现状 |
|---|---|---|
| `check_ytdlp_update` | 检查是否有新 stable | 宿主每周做 |
| `prepare_ytdlp_update` | 后台拉取 yt-dlp，下次启动生效 | Agent 可催，实现仍在更新器里 |
| `switch_model_source` | 换到下一个已知模型源 | 宿主下载循环内做，模型不能调 |
| `retry_model_download` | 忽略退避，立刻再下默认模型 | 宿主有重试事件，未暴露 |
| `wait_for_default_model` | 不登记为 Tool。等待是宿主门闩的职责（`whisper_models.wait_for_default_model`，loop 之外）；模型侧用 `inspect_model_status` 观察就绪态 | 转录路径已有门闩，保持 loop 之外 |

以后若真有需要，再加闭集维护 Tool（例如「写某个已知环境键」「核验随包 FFmpeg」）。没有真实失败类别之前不加。

### 媒体（第一个场景 pack）

沿用现有恢复动作，登记为 Tool，而不是永远叫 `RecoveryAction`：

`run_ytdlp` · `http_request` · `run_candidate_parser` · `use_browser_session` · `request_youtube_challenge_capability` · `download_candidate` · `validate_media` · `validate_subtitle`

约束（YouTube / Bilibili 白名单、登录态不透明、候选代码一次性且无文件/网络/子进程、产物由宿主验证）保持不变。

### 与人

`set_user_message` · `ask_user`

`ask_user`（模型可请求）的 `action_code` 只允许 4 个：`enable_browser_session` · `login_then_retry` · `requeue_continue` · `abort`。拒绝未知 code 和额外 payload。

UI 可触发的动作有 5 个 = 上述 4 个 + `copy_sanitized_diagnostic`（复制脱敏诊断）。`copy_sanitized_diagnostic` 是等待态界面上的用户侧动作，由 `recovery_user_actions.apply_recovery_user_action` 直接处理，不经过 `ask_user`——模型不能请求它，实现时别把它加进模型可见集（`REQUESTABLE_USER_ACTION_CODES` 只有 4 个，`_ask_user` 会拒绝）。

### 持久化 code 的变更纪律

会落进 SQLite `tasks.data` 的值（`recovery_status` / `recovery_code` / `recovery_user_action` / `recovery_action_state` / `recovery_continuation` / observation 的 `action`·`code`，以及未来所有 Tool id）由旧版本写入、新版本读取，读端是严格枚举 round-trip，没有迁移层。

- **改名窗口一直开着**，直到出现不可清理的真实用户数据（即正式发布、用户机器落库真实任务记录）。在这之前随时可以改名，不必赶窗口：用户量还没涨起来，改名成本只有同步清单本身。
- **改名后的代价是已知且可接受的**：旧任务记录里的旧值读不到，任务卡在等待态（`RecoveryActionConflict`）。开发/测试库里的旧记录应在改完后清掉，避免自己踩坑。
- **冻结时机**：正式发布、任何一台用户机器落库真实任务数据后冻结。冻结后只增不改：新能力登记新 code，永不修改、重排、删除已有值。
- **改一个持久化 code 的同步清单**（缺一处就是运行时才暴露的 bug——字符串比对没有类型检查）：
  1. 后端枚举值（`media_contracts.RecoveryAction`、`media_recovery.UserActionCode`）；
  2. 前端 union 类型（`frontend/src/lib/types.ts` 的 `RecoveryActionCode`）；
  3. 前端按钮与比对逻辑（`useTranscribe.ts`、`TaskInsightsPanel.tsx`）；
  4. 测试里的硬编码字符串（`test_recovery_user_actions.py`、`test_media_recovery.py`、`test_product_scenarios.py`）；
  5. 脱敏诊断导出（`recovery_user_actions.build_sanitized_recovery_diagnostic`）；
  6. 去重/防空转读取（`recovery_continuation.attempted_actions` 的消费方）。
- **冻结后的例外路径**：确需改名时用读端别名映射（旧值→新值）或一次性迁移脚本改写 `tasks.data` 的 JSON 值，两者都要写测试。这是例外路径，不改变默认纪律。

---

## 八、场景如何挂上

场景不是新框架，只是一次运行的装配参数。

| 场景 | 何时启动 | 可见 pack | 成功条件 |
|---|---|---|---|
| 媒体恢复 | 字幕和音频都失败之后 | 观察 + 媒体 + 相关维护 + 与人 | 宿主验证过的字幕或音频 |
| 依赖 / 环境 | 宿主确定性回退全部走完（所有源试过、进入退避期）之后，与媒体恢复同级 | 观察 + 维护 + 与人 | 宿主验证过的组件状态，或明确降级并告知用户 |
| 正常成功路径 | 不启动 Harness | — | 字幕或音频按现有管线走 |

「依赖 / 环境」是否建、何时建，看第九节的触发条件：上表「回退全部走完」只是触发条件，还要求有被演示的、需要模型判断的失败类别（诊断分类 / 组合判断）；没有就不建。

环境场景与媒体恢复同级触发：只在宿主确定性回退全部走完（所有源试过、进入退避期）之后才启动，退避本身是宿主逻辑，不交给模型。模型层的价值不是替宿主多试一个源——宿主已试过的动作在 `attempted_actions` 里有记录，模型不会重试——而是诊断分类与组合判断：宿主回退走完后决定「是解析器过期、镜像全挂，还是环境缺组件」，选维护 Tool 继续、问人、或宣布失败。

音频体检、Whisper 策略、质量复核仍是确定性宿主代码（`audio_profiler` / `transcription_strategy` / `transcript_quality`）。它们给下游事实，不进 loop。分析失败则回退当前默认转录。

---

## 九、和当前代码的关系

已经落地、不要重做行为：

- 正常路径不打模型
- 恢复 loop、预算、取消、问人后结束协程
- 闭集恢复动作、Deno 候选解析器、宿主验证
- 运行时画像、官方源失败换国内镜像、yt-dlp 每周自更新
- 固定恢复 action code 与任务状态字段

当前形态是「媒体恢复功能里嵌了一个 loop」，还不是本文件描述的 Harness：

- 提示词和目标写死在 `OpenAICompatibleRecoveryModel` / `MediaRecoveryCoordinator.run`
- 动作枚举叫 `RecoveryAction`，和新的观察/维护 Tool 挤在一起
- 换源、续传、每周更新由宿主独占，模型最多催 yt-dlp
- `inspect_runtime` 还看不到完整报错与日志

演进顺序：每一步都以「真实场景 + 会以 Tool 契约调用它的调用方」为前置。不要先追求几十个 Tool，也不要为分层去建包或搬迁无关模块。

1. **现状维持**。媒体恢复里嵌着的 loop 和大动作类已经是「有调用方」的形态，行为有测试覆盖，先不动。媒体场景内的动作可以随时补模型说明与能力标记（改善模型决策），这不等于拆文件。

2. **触发点：环境诊断出现被演示的真实失败类别**。「官方源失败换镜像」不算——那是宿主确定性行为，模型不加值；要的是「官方 + 镜像都挂，在退避重试 / 降级 / 问用户之间选择」这类真的需要判断、宿主规则表里没有的失败。没有这个，第 3 步不做。

3. **场景成立后再拆内核 + Dispatch**。这时才有第二个场景消费者：媒体恢复 + 环境诊断。媒体场景迁入共享 Dispatch，其动作是迁移（调用方一直存在）不是新登记，契约升级只是进入共享 Dispatch 的接口成本；维护类 Tool（`switch_model_source` / `retry_model_download` / `inspect_model_status` …）随环境场景的 pack 一起登记——它们的模型调用方在这一刻才出现。宿主下载循环改调 Dispatch 是这一步的附带重构，一次完成。

---

## 十、给后续实现的约束

1. 每个新抽象必须直接服务 loop、Dispatch 或某一个真实 Tool。
2. 平铺文件、扁平 import，与 `AGENTS.md` 一致。
3. 不把 Grok Build 的 crate 边界复制成 Python 包森林。
4. 不把 `ProductizationPlan.md` 里「不做微型 coding agent / Agent Harness」理解成「不要本文件这种应用内 Harness」。那句话拒绝的是编程 Harness 和通用平台。
5. 真实 Key、Cookie、Token、账号、私密媒体不进 Git、日志、测试、observation。
6. 模型输出、网页、Tool 观察、候选代码一律当不可信输入。
7. 本文件改架构决策；具体产品化任务仍按 `ProductizationPlan.md` 一次一项推进。
8. 模型视野覆盖整个软件的可脱敏状态，动作面只有登记的 Tool 闭集；wait 类门闩不进 loop，长操作一律「触发 + 事后观察」。
