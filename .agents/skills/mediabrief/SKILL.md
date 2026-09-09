---
name: mediabrief
description: >-
  把视频、音频、播客链接或本地媒体变成清洗过的转录和二次摘要。
  主动下载（yt-dlp）、字幕优先、Whisper 兜底、转录纠偏、双步摘要（sub-agent 判断内容并产出定制 Prompt，主 Agent 按该 Prompt 执行）。
  Use when the user pastes YouTube/Bilibili/抖音/播客 URL，或要求转录、翻译、摘要音视频，或提到两步摘要、二次摘要。
---

# mediabrief

链接或文件进，可读转录和按材料定制的摘要出。下载与转写只用本目录 `scripts/`；判断与生成走模型。**双步摘要必须拆成 sub-agent / 主 Agent**，不要同一次输出里既定标准又写成品。

机制与失败处理见 [acquire.md](acquire.md)、[two-step.md](two-step.md)、[pitfalls.md](pitfalls.md)。

## 交付物

默认写到用户指定目录；未指定则用当前工作区 `_mediabrief/<slug>/`：

| 文件 | 内容 |
|---|---|
| `source.json` | URL、标题、获取方式（subtitle / whisper / file） |
| `transcript.raw.md` | 原始字幕或 Whisper 文本 |
| `transcript.md` | 纠偏后的可读正文（需要时） |
| `summary.prompt.md` | 第一步产出的定制摘要指令 |
| `summary.md` | 第二步按该指令写成的摘要 |

只要摘要时仍写出 `summary.prompt.md`，便于核对标准是否合理。

## 总流程

1. **获取**：链接用脚本；本地媒体直接转写；已有文稿则跳过下载。
2. **转录**：有可用字幕就不要再 Whisper；否则音频 + Whisper。
3. **纠偏（默认做）**：错别字、专名、分段；不删口语、不改人称。官方字幕或用户已校对的可跳过。
4. **双步摘要（默认）**：sub-agent 只出 Prompt；主 Agent 只执行。
5. **交付**：先给摘要；需要时再给转录路径。

用户明确只要单步摘要时，跳过 sub-agent，用 [two-step.md](two-step.md) 的 `SUMMARY_EDITOR`。

## 1. 获取媒体

先读 [acquire.md](acquire.md)。默认**不要下完整视频**。

```bash
python "<skill-dir>/scripts/fetch_media.py" "URL" --out "<out-dir>"
```

`skill-dir` 是本 `SKILL.md` 所在目录。失败时读 stderr，按 acquire.md / pitfalls.md 换 cookie、格式或仅音频，**不要另写一套 yt-dlp 封装**。

本地 `.mp4/.mp3/.m4a/.wav/.webm/.mkv`：直接转写。本地 `.txt/.md`：当作已有转录。

## 2. 转录

1. 已有 `.vtt/.srt` → 去掉时间轴、序号、重复行，保留说话顺序，写入 `transcript.raw.md`
2. 否则：

```bash
python "<skill-dir>/scripts/transcribe.py" "<audio>" --out "<out-dir>/transcript.raw.md"
```

需要 `ffmpeg`。Apple Silicon 用 `mlx-whisper`，否则 `faster-whisper`。缺依赖就装好再跑，不要换来路不明的 ASR。

长音频可按约 10 分钟一块（很长、静音多则约 5 分钟），允许并行，合并必须按时间顺序，头尾都要在。

Whisper 段落后：丢掉固定间隔重复的短句、片尾「感谢观看 / thanks for watching / 请订阅」一类幻觉；不要把它们写进摘要。

## 3. 转录纠偏

用 **sub-agent** 做领域预分析（只出约束块），主 Agent 再改 `transcript.md`：

- 修错别字、同音专名；无把握保留原文
- 补标点；按主题分段（约 1–8 句）
- **不改人称、不删重复口语、不加改动说明或检测语言行**

字幕常是碎句。摘要前先收成可读段落（中文可直接拼接，西文用空格），避免空行把上下文切碎。角色全文见 [two-step.md](two-step.md)。

## 4. 双步摘要

不是「先摘要再压缩一遍」。第一步定这一份材料的提取标准；第二步只执行该标准。

### Step 1 — sub-agent：判断，只输出 Prompt

另开 sub-agent（Cursor：`Task`，`subagent_type=generalPurpose`）。只给：

- 标题、来源、目标语言
- 转录预览：尽量全文；超长则开头 + 中段 + 结尾，并写明未覆盖范围
- [two-step.md](two-step.md) 里 `SUMMARY_PROMPT_DESIGNER` 全文

返回值只能是定制摘要 Prompt（对执行者说话的第一人称指令）。不要摘要、不要「以下是 Prompt」。写入 `summary.prompt.md`。

若返回空：回退 `SUMMARY_EDITOR`，并标明本次没有定制标准。

### Step 2 — 主 Agent：执行

把 Step 1 的 Prompt 当人设，读 `transcript.md`（或 raw），写 `summary.md`。

- 语言跟用户；未指定则跟材料
- 不复述全文、不逐句扩写
- 不写「以下是摘要」、客套结尾、过程说明
- 专名、数字、否定、条件以转录为准；缺的不要用搜索补
- 不要把 `[Part N]`、分块编号写进用户可见摘要
- 超长：按 Step 1 的维度分段提取，**主 Agent** 整合去重；sub-agent 不写最终摘要

## 模型怎么用

| 步骤 | 谁 | 要什么 |
|---|---|---|
| 领域预分析 | sub-agent | 短约束块 |
| 转录纠偏 | 主 Agent | 保真正文 |
| 定制 Prompt | **sub-agent** | 可执行指令 |
| 写摘要 | **主 Agent** | 成品 Markdown |
| 下载 / Whisper | 脚本 | 文件 |

鉴权失败、额度不足、模型不存在：直接告诉用户，不要静默改成劣质兜底摘要冒充成功。

当前对话模型不可用时：仍完成下载和转写，摘要能写再写，并说明未跑 Step 1。

## 用户可见顺序

先摘要（必要时带一句标准是否合理），再转录路径。语气直接、短。
