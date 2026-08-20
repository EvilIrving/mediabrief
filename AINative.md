# MediaBrief AI Native

应用内 Harness 现在怎么工作。

更新时间：2026-08-16

这是当前软件里的实现说明。产品层见 `ProductizationPlan.md`。怎么加 Tool、怎么挂新场景，见 `AINativePlan.md`。

---

## 一、它是什么

MediaBrief 内置一个短生命周期命令环。模型只选已登记的 Tool，宿主执行、验证、脱敏。用户不必理解 yt-dlp、FFmpeg、模型源或环境变量。

```text
现场触发（抽取双失败 / Detect 拿到格式清单）
        ↓
   场景装配（目标 + 可见 Tool + 成功条件）
        ↓
   模型 decide（只输出 JSON：选 Tool / 完成 / 失败）
        ↓
   宿主 execute（同一函数，模型选完也走这里）
        ↓
   脱敏 observation → 再判断 / 问人 / 停止
        或直接把 payload 交给页面
```

同一 Tool 有两个入口：

- **宿主直接调**：规则已经够用，或模型不可用。
- **模型选了再调**：现场需要判断时。选完仍调同一个 `execute`。

模型不会比宿主更会做事。它只是在诊断里按下已经存在的按钮。

---

## 二、它不是什么

不是编程 Agent，也不是通用平台。

不做：通用 Shell、任意写文件、MCP、插件市场、多 Agent、长期会话、聊天页、让模型发明按钮或绕过 Tool。

`ProductizationPlan.md` 里「不做 Agent Harness」拒绝的是编程 Harness。本文说的是已经在跑的应用内命令环。

---

## 三、现在怎么实现

没有 `harness/` 包。分层靠 `backend/` 里的模块名和 import。

```text
┌─────────────────────────────────────────────┐
│  场景                                       │
│  媒体恢复  media_recovery_service.py        │
│  下载列表  download_list_scene.py           │
└───────────────────┬─────────────────────────┘
                    │ 装配
┌───────────────────▼─────────────────────────┐
│  环                                          │
│  MediaRecoveryCoordinator  （多轮 loop）     │
│  OpenAICompatibleRecoveryModel（decide）     │
│  RecoveryBudget / 闸门 / doom_loop           │
└───────────────────┬─────────────────────────┘
                    │ 按 id 执行
┌───────────────────▼─────────────────────────┐
│  Tool                                        │
│  MediaRecoveryActions.action_specs + execute │
│  format_curator.tool_spec + execute          │
└─────────────────────────────────────────────┘
```

| 职责 | 文件 |
|---|---|
| 决策 / 预算 / observation 类型 | `media_recovery.py`、`media_contracts.py` |
| 多轮 loop + 闸门 + 防空转 | `MediaRecoveryCoordinator` |
| 模型适配 | `OpenAICompatibleRecoveryModel`（`llm_client.complete_model` → Responses API） |
| 媒体 Tool 说明书与执行 | `MediaRecoveryActions` |
| 下载列表 Tool | `format_curator.py` |
| 媒体场景装配 | `media_recovery_service.py` |
| 下载列表场景装配 | `download_list_scene.py` |
| 产品接入 | `pipeline.py` → `sources.py` 的 `recover_media`；`routers/downloads.py` 的 Detect |
| 问人按钮 | `recovery_user_actions.py` |
| 运行时画像 | `runtime_environment.py`（`inspect_runtime` 读这份） |

模型配置使用任务已经解析出的有效 LLM 配置：带 Key 包优先取 `release_config`，不带 Key 包取用户在界面保存的配置。没配 Key 或模型时，媒体恢复立即 `unavailable`，保留原失败；下载列表则宿主直接 `execute`。

---

## 四、两个已接入场景

场景不是框架，是一次运行的装配：目标、system prompt、本轮可见 Tool、成功条件。

### 媒体恢复

字幕和音频都失败之后，`sources.py` 调 `recover_media`。

- 装配：`MediaRecoveryService.recover` 建 `MediaRecoveryActions`，交给 `MediaRecoveryCoordinator`
- 可见表：`MediaRecoveryActions.action_specs()` 的 13 个动作
- 成功条件：宿主验证过的字幕或音频（`verified_result`）
- 正常成功路径不进这个环

Coordinator 接受 `goal` / `system_prompt`（默认是媒体恢复那两句）。循环：

```text
for turn in 预算（默认 5 轮、6 个动作、总 120s）:
    取消检查
    decision = model.decide(messages, 可见 Tool 表)
    completed → 问 verified_result；未验证则回 observation，继续
    failed → 结束
    action 不在可见表或不在 RecoveryAction → unknown_action 观察
    参数不是 object → invalid_arguments
    execute，套 action_timeout
    若 pending user action → 结束，保存 recovery_continuation
    同一 Tool+参数连续失败 2 次 → doom_loop
    把脱敏 observation 追加进 messages
```

未配置模型、超时、取消、预算耗尽都有固定 `recovery_code`，会落进任务字段。界面用产品语言，不堆动作名；完整诊断走「复制脱敏诊断」。

### 下载列表

Detect 拿到 `video_formats` / `audio_formats` 之后，`routers/downloads.py` 调 `run_download_list_scene`。

- 可见表：只有 `present_download_list`
- 有模型：一次 `decide`，选中则把 Detect 参数交给同一 `execute`
- 没模型、模型报错、没选这个 Tool、execute 失败：宿主用同一 `execute` 出 payload
- 页面拿到 `{video, audio}`，每项有 `id` 和 `label`（每个清晰度一条）
- 不另写 `chat.completions` 旁路

这个场景不走 Coordinator 的多轮 loop。它是「单次 decide + 同一 Tool」，失败就回退宿主。

---

## 五、Tool 现在长什么样

每个给模型看的 Tool 都有：

```text
name            稳定 id，snake_case
description     何时用、不能做什么
capability      read | mutate
timeout_sec     给模型看的预期
arguments       闭集；没有的字段就是没有
execute(...)    宿主和模型走同一函数
```

媒体 Tool 的 observation 是 `status` + `code` + 脱敏 `summary`。变更类成功时，summary 是宿主已验证的事实。

### 媒体恢复可见集（`RecoveryAction`）

| id | capability | 做什么 |
|---|---|---|
| `inspect_failure` | read | 读本轮脱敏抽取失败 |
| `inspect_runtime` | read | 读 FFmpeg / FFprobe / Deno / MLX / yt-dlp / Whisper / 浏览器会话 |
| `run_ytdlp` | mutate | 跑一个宿主批准的 profile（metadata / subtitles / audio） |
| `prepare_ytdlp_update` | mutate | 催后台 stable 更新，本轮不等待生效 |
| `http_request` | mutate | GET/HEAD 白名单域名或宿主 proposal |
| `run_candidate_parser` | mutate | 一次性 Deno 解析器，无文件/网络/子进程 |
| `use_browser_session` | mutate | 使用不透明登录态，不把 Cookie 给模型 |
| `request_youtube_challenge_capability` | mutate | 问宿主是否已有 challenge 能力 |
| `download_candidate` | mutate | 下载已接受的 candidate_id |
| `validate_media` | mutate | 宿主校验媒体 |
| `validate_subtitle` | mutate | 宿主校验字幕非空 |
| `set_user_message` | mutate | 任务详情上的短进度，≤300 字纯文本 |
| `ask_user` | mutate | 停下来要人按固定按钮 |

`inspect_runtime` 的摘要能区分组件是否可用、Whisper 源/已试源/最近错误、yt-dlp 版本与待重启。上限 1200 字，无绝对路径、Key、Cookie。

### 下载列表可见集

| id | capability | 做什么 |
|---|---|---|
| `present_download_list` | read | Detect 清单 → 页面可渲染的 `{video, audio}` |

它不在 `RecoveryAction` 里，独立模块 `format_curator.py`。

### 宿主在做、还没登记成 Tool 的事

换模型源、重试默认模型下载、每周查 yt-dlp，实现分别在 `whisper_models.py` 和 `yt_dlp_updater.py`。媒体恢复能通过 `inspect_runtime` 看见状态，也能催 `prepare_ytdlp_update`。`wait_for_default_model` 是转录路径的宿主门闩，不进 loop。

---

## 六、问人和持久化

`ask_user` 只能要这 4 个 code：`enable_browser_session` · `login_then_retry` · `requeue_continue` · `abort`。模型不能发明按钮，不能带额外 payload。

UI 还有第 5 个：`copy_sanitized_diagnostic`。它不经 `ask_user`，模型看不见。

会进 SQLite `tasks.data` 的字符串（`recovery_status` / `recovery_code` / `recovery_user_action` / observation 的 `action`·`code`、以及 Tool id）按跨版本格式对待：正式用户数据落地后只增不改。改名要同步：

1. `media_contracts.RecoveryAction`、`media_recovery.UserActionCode`
2. `frontend/src/lib/types.ts` 的 `RecoveryActionCode`
3. 前端按钮与比对（`useTranscribe.ts`、`TaskInsightsPanel.tsx`）
4. 测试里的硬编码字符串
5. `recovery_user_actions.build_sanitized_recovery_diagnostic`
6. `recovery_continuation.attempted_actions` 的消费方

---

## 七、写新 Tool、做新功能时守住的边界

1. 一个 Tool 只做一件宿主允许的事。换源、续传、更新 yt-dlp 是三个，不是一个大 Tool。
2. 功能是场景，平台是失败实例。不要为 YouTube / B 站各写一套 Tool。
3. 没有「任意命令 / 任意 URL / 任意路径」。
4. 给模型的文本先脱敏（`sanitize_diagnostic` / `sanitize_plain_text`）。
5. 先有会以 Tool 契约调用它的场景，再登记。宿主内联逻辑不是登记理由。
6. 长操作拆成「触发 + 宿主后台继续 + 事后观察」。wait 不进 loop。
7. 本轮看不见的 Tool 等于不存在。权限在可见表，不在各个函数里再写一遍。
8. 平铺文件、扁平 import。不建插件目录，不复制 Grok 的包森林。
9. Key / Cookie / Token / 私密媒体不进 Git、日志、测试、observation。
10. 模型输出、网页、observation、候选代码当不可信输入。
