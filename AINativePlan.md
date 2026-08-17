# MediaBrief AI Native 现状与实现指南

更新时间：2026-08-16  
当前状态：**已完成**（本文描述现在的软件，并指导怎么加 Tool、怎么加场景）

架构说明在 `AINative.md`。产品化剩余项仍走 `ProductizationPlan.md`。

---

## 一、软件里现在有什么

用户侧：

- 不用自己装环境、填模型源、更新 yt-dlp。官方源失败换镜像、每周检查、默认模型续传，由宿主做。
- 字幕和音频都失败后，软件自己尝试恢复。界面说「正在尝试其他方式」，不是 yt-dlp 命令。
- 必须人点头时只有固定按钮，没有聊天框，没有让用户贴 Cookie。
- 失败用产品语言；复制诊断给愿意深挖的人。

环侧：

- 两个场景：媒体恢复（多轮 Coordinator）、下载列表（单次 decide + 同一 `execute`）
- 媒体 13 个 Tool 有完整说明书（description / read|mutate / timeout / 闭集参数）
- 下载列表 Tool `present_download_list` 独立模块，Detect 后接入
- 闸门：可见表、参数必须是 object、超时、取消、`unknown_action`
- 同一失败指纹连续 2 次 → `doom_loop`
- 未配置模型：恢复保留原失败；下载列表宿主自己出列表
- `inspect_runtime` 摘要能判断缺组件、模型源、yt-dlp 是否过期

确定性宿主代码仍在环外：`audio_profiler` / `transcription_strategy` / `transcript_quality`、Whisper 换源与续传、`wait_for_default_model`。

---

## 二、文件地图

| 要改什么 | 去哪 |
|---|---|
| 多轮 loop、预算、decide、停止原因 | `backend/media_recovery.py` |
| 媒体 Tool 说明书 + 执行 | `backend/media_recovery_actions.py` |
| 媒体动作 id | `backend/media_contracts.py` 的 `RecoveryAction` |
| 媒体场景装配 | `backend/media_recovery_service.py` |
| 下载列表 Tool | `backend/format_curator.py` |
| 下载列表场景 | `backend/download_list_scene.py` |
| Detect 接入 | `backend/routers/downloads.py` |
| 抽取失败后接入恢复 | `backend/pipeline.py`、`backend/sources.py` |
| 用户按钮 | `backend/recovery_user_actions.py` |
| 运行时画像 | `backend/runtime_environment.py` |
| 恢复用模型客户端 | `backend/llm_client.py`（关思考）、`OpenAICompatibleRecoveryModel` |
| 界面文案 | `frontend/src/i18n/dictionaries.ts`（四语） |
| 恢复详情 | `frontend/src/features/transcribe/TaskInsightsPanel.tsx` |
| 测试 | `backend/tests/test_media_recovery.py`、`test_download_list_scene.py`、`test_format_curator.py`、`test_product_scenarios.py` |

继续平铺在 `backend/`，扁平 import。不要新建 `harness/` 包。

---

## 三、两种接入方式，选对再写

**多轮判断**（像媒体恢复）：用 `MediaRecoveryCoordinator`。场景传入 `goal`、`system_prompt`、带 `action_specs` / `execute` / `verified_result` / `pending_user_action` 的 executor。失败会进任务诊断。

**单次选 Tool、失败就回退宿主**（像下载列表）：写一个薄场景函数。先算宿主结果，有模型就 `decide` 一次，选中则调同一 `execute`，否则返回宿主结果。不要为这种事再开一条 `chat.completions`。

新功能先问：成功条件能不能由宿主函数验证？本轮模型只该看见哪几个 id？没有调用方就不要先造 Tool。

---

## 四、如何加一个 Tool

### 形态

```python
TOOL_ID = "do_the_thing"

def tool_spec() -> dict:
    return host_function_tool(
        TOOL_ID,
        "When to use it. What it must not do.",
        capability="read",   # 或 "mutate"；发给模型前会去掉
        timeout_sec=5,
        properties={"known_field": string_prop("closed-set meaning")},
        required=["known_field"],
    )

def execute(arguments: dict | None = None) -> ...:
    # 参数闭集校验；宿主和模型都走这里
    ...
```

媒体恢复里的等价物是：`RecoveryAction` 枚举值 + `action_specs()` 一条 + `execute` 字典里的处理方法。处理方法返回 `RecoveryObservation`。

### 步骤

1. **先有场景。** 哪个调用方会按 Tool 契约调它？只是宿主内部函数，先别登记。
2. **切粒度。** 参数、风险、观察语义不同就是不同 Tool。不要做一个万能 `maintain_environment`。
3. **选放哪。**
   - 属于媒体恢复、需要进 Coordinator：加进 `RecoveryAction` + `MediaRecoveryActions`。
   - 独立、宿主也要直接调：单独模块（照 `format_curator.py`），场景只把 id 放进本轮可见表。
4. **说明书写清不能做什么。** 例如不能传任意 yt-dlp 参数、不能访问任意域名、不能发明 `action_code`。
5. **同一 `execute`。** 禁止再写一条只给模型用的实现。
6. **测试打契约。** 非法参数、不可见 id、超时/取消（若适用）、脱敏、宿主验证后的成功。
7. **若 id 或 code 会落库：** 按 `AINative.md` §六 同步清单改前端类型、按钮、测试。正式用户数据落地后只增不改。
8. **若界面要显示：** 四语文案进 `dictionaries.ts`，产品语言，不要把内部 id 当主文案。

### 不要

- 不要自动扫描目录注册
- 不要 JSON/YAML 插件
- 不要按平台复制 Tool
- 不要把 `wait_for_default_model` 收进 loop
- 不要给模型任意路径、任意 URL、任意环境变量
- 不要把 `copy_sanitized_diagnostic` 加进模型可见集

---

## 五、如何加一个新场景

一次运行必须带齐：

```text
goal                给模型看的一句话
system_prompt       禁止要密钥 / Shell / 任意路径；只许列出的 Tool
visible_tools       本轮 id；不在表里 = 不存在
success_check       宿主函数，不是模型说完成就算
budget              多轮场景用 RecoveryBudget（含 doom_loop_threshold=2）
```

模型只许输出：

```json
{"kind":"action","action":"<id>","arguments":{}}
{"kind":"completed","message":"..."}
{"kind":"failed","message":"..."}
```

非法 JSON 当 `model_error`，不要当成未知 Tool 去执行。

接入点写在已有产品路径上：抽取失败、Detect 之后、或某个宿主回退走完之后。不要做「问 AI」入口页。

问人继续用固定 `action_code`。需要新按钮就同时改 `UserActionCode`、`REQUESTABLE_USER_ACTION_CODES`、前端 union 和四语文案。

---

## 六、内核闸门（改 loop 时保持这个顺序）

1. 取消令牌
2. action 是否在本轮可见表
3. arguments 必须是 object
4. 按该 Tool 闭集校验
5. `execute` + 超时 + 取消
6. 超时 / 取消 / 其它异常分类（摘要走 `sanitize_diagnostic`）
7. 若 Tool 请求问人 → `action_required`，保存最小 continuation
8. 观察截断到 `max_observation_chars` 再进 messages

防空转：指纹 = Tool id + 规范化 JSON 参数。只计 `status == failure`。同一指纹连续 2 次停止，`code=doom_loop`。

停止原因（会落库）：`artifact_verified` · `user_action_required` · `model_unavailable` · `cancelled` · `doom_loop` · `model_turn_budget_exhausted` · `action_budget_exhausted` · `total_timeout` · `model_timeout` · `model_error` · `model_stopped`。

`unknown_action` / `invalid_arguments` / `action_timeout` / `action_error` 是观察 code，不是运行终止 code，除非因此触发 doom_loop 或预算耗尽。

---

## 七、和其它文档的关系

| 文件 | 管什么 |
|---|---|
| `AINative.md` | 现在的环怎么跑、有哪些 Tool、边界 |
| 本文件 | 现状清单；加 Tool / 加场景的步骤 |
| `ProductizationPlan.md` | 发行、签名、下载页、五人验收 |
| `PROJECT_MEMORY.md` | 跨会话决策 |
