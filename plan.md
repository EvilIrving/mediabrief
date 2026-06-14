# 重构计划：把"队列 SSE + 任务 SSE"收敛为"一条队列流 + 一个详情 REST"

## 背景与动机

当前前端被两套状态分别驱动，导致队列列表与详情进度可能撕裂：

```
Queue SSE/REST → setItems() / setProcessing()        （列表读 item.status）
Task SSE        → setPhase() / setProgress() / setResults()  （详情读 task.status）
```

关键约束：`SerialStrategy` 下同一时刻只有一个任务在跑，且**永不支持并发**（见"决策"）。
因此"实时进度"全局只属于那一个任务，而它恰好就是队列里的 `processing` 项。
点开已完成/历史任务时，task SSE 不再有任何后续更新——那本就是一次 REST GET 的活。

结论：不去**调和**两个真相源，而是**删掉**第二个。

## 决策（来自本轮 review，已拍板）

1. **不存在灰度。** 项目未发布、无用户、无历史包袱。直接切换，不保留旧路径、不做双读验证。
   历史数据若碍事直接删（`temp/` 下 sqlite）。
2. **永不支持并发。** UI 直接消费队列流里唯一的 `processing` 项即可，不为 `ConcurrentStrategy`
   预留抽象。
3. **retry 队列化。** retry 视为一个"轻量任务"，走 `queue_manager.enqueue(...)` 进统一队列，
   进度自然从队列流流出，不再走 `asyncio.create_task` 旁路。
4. **下载页独立轮询。** 下载与转录是两条不相关的路线；下载页**不接队列流**，改用一条简单
   REST 轮询（`GET /api/task-status/{id}`）。它不参与本次单源收敛。
5. **SSE 不承载敏感字段。** 队列项 payload 含 `api_key`/`model_base_url`/`model_id`，必须定义
   **安全投影**，SSE/REST 队列状态只返回 UI 所需字段。

## 目标形状

```
一条 SSE  = 队列流，其中 processing 项带 progress / current_stage / summary_ready / transcript_ready（安全投影，无正文、无密钥）
一个 REST = GET /api/task/{id}，按需取 script / summary / translation 正文
下载页    = 独立 GET /api/task-status/{id} 轮询，与上面互不相干
```

### 硬约束：SSE 永远只承载轻量状态，正文一律走 REST

不可妥协的不变量：

- **正文（script / summary / translation）任何时候都不进 SSE**，包括任务完成之后。
- **密钥/配置（api_key / model_base_url / model_id）任何时候都不进 SSE/REST 队列状态。**
- 激活/查看任意任务（运行中或已完成）→ 一律 `GET /api/task/{id}` 拉最新正文。
- 任务结束前的"准备中/已就绪"只用**轻量字段**表达：`progress`、`current_stage`、
  `summary_ready`、`transcript_ready` 等布尔/标量。
- 因此 SSE 帧大小恒定、与转录长度无关。

> 现状与此相反：`task_store.broadcast_task_update`（task_store.py:116）推整个 task dict
> （含 script/summary/translation），前端 `showPartialSummary` 直接读流里的 `task.summary`。
> 同样 `db.queue_get_state`（db.py:567）`SELECT *` 把整条 payload（含密钥）原样返回。
> 合并时两处都要剔除。
>
> 注：摘要先于转录展示不是特殊路径。摘要在 pipeline 里先完成 → `summary_ready` 先翻 true →
> REST 此刻即可查到摘要 → 前端按 ready 标志去 REST 拉对应正文。"摘要先于转录"是完成顺序
> 自然掉出的结果，无 partial 机制。

## 已完成的前置修复（本轮已 ship，保留）

- 后端 `task_queue.py::cancel_item`：取消处理中任务时 `await asyncio.wait({running})`，
  等 pipeline 在段边界真正停掉、worker `finally` 释放 `SerialStrategy._active` 锁，再删记录广播。
- 前端 `useTranscribe.ts::applyQueueState`：单调性守卫（`STATUS_RANK`），晚到旧快照不能把
  processing 降回 queued。
- 前端"取消中…"状态（`cancellingIds` + `QueuePanel` 禁用按钮 + i18n `q_cancelling`）。

## 实施步骤

> 无灰度：每步直接落地，不保留双路径。

### 步骤 1：后端——队列状态安全投影 + 进度富化

落点：`db.queue_get_state`（db.py:567）。

- **定义安全投影**：不再 `SELECT *` 原样吐 payload。每个 item 只返回 UI 字段：
  `id`、`task_id`、`status`、`position`、`job_kind`、`source_label/title`、`error`。
  **剔除 payload 中的 `api_key` / `model_base_url` / `model_id`**（以及其余非 UI 字段）。
- **富化 processing 项**（按 `task_id` join `tasks` 表）：
  `progress`、`current_stage`、`progress_key`、`progress_step_current/total`、
  `summary_ready`、`transcript_ready`、`task_status`（= tasks.status）、`mode/task_type`。
  **不带 script/summary/translation 正文。**
- 列表项（queued/error）只需轻量身份字段，不必 join 进度。

### 步骤 2：后端——进度更新接入队列流广播

- `task_store.broadcast_stage` / `broadcast_task_update`（task_store.py:310 / :116）在更新任务后，
  对该任务所属队列触发一次 `queue_manager._broadcast_state("tasks")`，让富化后的 processing
  项把进度推到队列流。频率与现状一致，只是落点从 task SSE 收敛到队列流。
- 因为下载页改独立轮询（步骤 6），`broadcast_task_update` 的 task SSE 推送在步骤 7 整体删除；
  这里先让队列流成为转录进度的唯一推送通道。

### 步骤 3：后端——新增 GET /api/task/{id}

- 现状：`/api/task/{task_id}` 仅有 **DELETE**（transcribe.py:268）；完整状态在
  `/api/task-status/{id}`（transcribe.py:190），正文单独接口只有 transcript
  （transcribe.py:300）。
- **新增 `GET /api/task/{task_id}`**：返回完整任务（script/summary/translation/
  detected_language/stage_items/result_items 等，形状参考现 task SSE 推送的 task dict）。
  内部复用 `refresh_task_view_state` + `_db_get_task`。
- 历史转录全文沿用既有 `GET /api/task/{id}/transcript`（D6 路径）。
- `/api/task-status/{id}` 保留——下载页轮询要用它（步骤 6）。

### 步骤 4：后端——retry 队列化

落点：`retry_task`（transcribe.py:362）。

- 把 `asyncio.create_task(regenerate_summary(...))` 旁路改为
  `queue_manager.enqueue("tasks", "retry", task_id, {...})`，payload 带
  `task_id` / `summary_language` / `use_two_step` / 密钥三件套。
- worker 分发新增 `job_kind == "retry"` → 调 `regenerate_summary(...)`。
  （`STAGE_DEFINITIONS["retry"]` 已存在，task_store.py:177，stage 流复用。）
- 重试进度由此走队列流的 processing 富化字段，与首跑一致，无独立通路。
- 入队前 `_db_update_task(status="queued", message="task.retrying")`，而非直接 processing。

### 步骤 5：前端——切换为单源 + 详情 REST（转录页）

落点：`useTranscribe.ts`。

- 进度条改读队列流 processing 项（经 `displayStatus` 派生），不再读 task SSE。
- 详情正文：
  - 选中某项 → `GET /api/task/{id}` 拉正文渲染。
  - 正在跑的项 → 队列流里某 artifact 的 ready 标志翻转时，`GET /api/task/{id}` 拉对应正文
    （摘要先 ready 先显示，转录后到同理）。
- `displayStatus` 派生：`taskStatus` 优先于 `queueStatus`；终态 > processing > queued。
- 单调性守卫（`STATUS_RANK`）并入同一 selector。

### 步骤 6：前端——下载页改独立轮询

落点：`DownloadPage.tsx:148` 的 `startSSE`。

- 删除 `EventSource(api.streamUrl(...))`，改为对 `GET /api/task-status/{id}` 的简单轮询
  （如 1–2s 间隔，读 `progress` / `current_stage` / `status`），完成/出错即停。
- 与转录页完全解耦，不接队列流。

### 步骤 7：前端 + 后端——删除旧的第二状态源

- 前端删 `useTranscribe.ts` 中 task SSE：`taskEsRef` EventSource effect、5s 轮询兜底、
  `onTaskMessageRef`、`detailIdRef` 等围绕 task SSE 的机制。
- 后端删 `/api/task-stream/{task_id}` 路由（transcribe.py:199）及 `task_store` 中仅服务它的
  广播分支：`broadcast_task_update` 的 SSE 推送部分、`sse_connections` / `sse_lock`。
  保留 `refresh_task_view_state`（队列富化与 REST 都还要用）。
- `api.streamUrl` 等仅供 task SSE 的前端辅助若无其它引用一并删除。

## 验证

- `cd frontend && pnpm build`（tsc + vite）。
- `cd backend && python -c "import main; print(len(main.app.routes))"`
  （删 task-stream、加 GET /api/task/{id}，净变化按实际更新预期值；当前基线 27）。
- 安全投影核对：队列流/队列 REST 的任一帧都不含 `api_key`/`model_base_url`/`model_id`，
  也不含 script/summary/translation 正文。
- 手测矩阵：URL 转录 / 本地上传 / 取消处理中 / **重试（经队列）** / 点开历史项 /
  多任务排队 / **下载任务（独立轮询）**，确认列表徽标与进度条始终一致、无 queued↔processing
  撕裂、摘要仍先于转录出现。

## 不做

- 灰度 / 双读验证 / 旧新路径兼容——项目未发布，直接切。
- `ConcurrentStrategy` 抽象与多 processing 派生——永不支持并发。
- 后端独立 `/api/task-view/stream`——用"富化既有队列流"替代。
- 前端独立 unified store/reducer 框架——单源后 selector 足够。
