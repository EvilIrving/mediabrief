# 多平台 Bot 集成：架构设计

## 目标

用户在 Telegram / Slack / 飞书 / 微信 等平台发送链接，MediaBrief 自动下载并转录，完成后回传摘要 + 转录文本。

## 核心约束

- MediaBrief 是纯本地服务（无公网 IP，无入站连接）
- 本机能访问外网（出站 HTTPS 可用）
- Bot Token 等配置由前端 Settings 弹窗管理，不写死 `.env`

---

## 各平台可行性

| 平台 | 困难度 | 连接模式 | 依赖 | 说明 |
|------|--------|----------|------|------|
| **Telegram** | 🟢 低 | Long Polling (`getUpdates`) | `httpx`（已有） | 最成熟，零额外依赖 |
| **Slack** | 🟡 中 | Socket Mode (WebSocket) | `slack-sdk` | 需创建 Slack App |
| **Discord** | 🟡 中 | Gateway WebSocket | `httpx`（已有） | 需创建 Discord Application |
| **飞书/Lark** | 🟡 中 | 事件订阅 (Long Polling) | `httpx`（已有） | 需创建飞书应用 |
| **企业微信** | 🟡 中 | 官方 Bot API | `httpx`（已有） | 需企业主体注册 |
| **微信个人号** | 🟡 中 | Sidecar 桥接（WeClaw） | WeClaw 独立进程 | 见下方微信专项方案 |
| **LINE** | 🔴 高 | Webhook | — | 需公网 URL，不适合 |
| **WhatsApp** | 🔴 高 | Cloud API Webhook | — | 需 Business 账号 + 公网 URL |

---

## 整体架构

```
                    ┌──────────────────────────────────┐
                    │          MediaBrief               │
                    │                                  │
  Telegram ─────────┤  backend/bots/telegram.py         │
  (Long Polling)    │  backend/bots/slack.py            │
                    │  backend/bots/discord.py          │
  Slack ────────────┤  backend/bots/feishu.py           │
  (Socket Mode)     │  backend/bots/wecom.py            │
                    │                                  │
  飞书 ─────────────┤  backend/bots/common.py     ←─── 共享：URL提取、消息分片、结果格式化
  (事件订阅)         │  backend/bots/base.py       ←─── 抽象接口
                    │  backend/bots/manager.py     ←─── 启停管理 + 配置热更新
                    │  backend/routers/bots.py     ←─── HTTP 路由
                    │         ↑                            │
                    │   复用 pipeline.py                   │
                    │   复用 task_store.py                 │
                    │         │                            │
  微信 ── WeClaw ──►│  POST /api/bots/wechat-webhook       │
  (sidecar 桥)      │  (被动接收，不主动连微信协议)           │
                    └──────────────────────────────────┘
```

**设计原则：**
1. TG/Slack/Discord/飞书/企微：Bot 主动建立长连接，由 MediaBrief 内部管理生命周期
2. 微信个人号：WeClaw 作为外部 sidecar 负责微信协议，MediaBrief 只暴露一个 HTTP 端点接收消息
3. 所有平台的「URL 检测 → 转录 → 回传」逻辑复用同一套 `common.py`
4. Bot 配置由前端 Settings 弹窗 `POST /api/bots/configure` 统一下发

---

## 后端抽象接口设计

### BaseBot（`backend/bots/base.py`）

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

class BotStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"

@dataclass
class BotConfig:
    enabled: bool = False
    token: str = ""
    extras: dict = field(default_factory=dict)
    # extras 承载平台特有字段：
    #   Slack: app_token
    #   飞书: app_id, app_secret
    #   企微: corp_id, agent_id, corp_secret

class BaseBot(ABC):
    platform: str  # 'telegram' | 'slack' | 'discord' | 'feishu' | 'wecom'

    @abstractmethod
    async def start(self, config: BotConfig) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    def get_status(self) -> dict: ...
    # 返回 {"status": "running", "uptime_seconds": 3600, "messages_processed": 12, "last_error": None}
```

### BotManager（`backend/bots/manager.py`）

```python
class BotManager:
    def __init__(self):
        self._bots: dict[str, BaseBot] = {}

    async def apply_configs(self, configs: dict[str, BotConfig]) -> dict:
        """对比新旧配置，新增/修改的 Bot 重启，移除的 Bot 停止，返回状态摘要"""

    def get_all_status(self) -> dict:
        """{ "telegram": {...}, "slack": {...} }"""

    async def shutdown(self):
        """停止所有 Bot"""
```

### 消息处理通用流程（`backend/bots/common.py`）

```python
import re

URL_PATTERN = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)

async def handle_incoming_message(
    reply_fn,        # async (text: str) -> None    发送文本
    reply_file_fn,   # async (path: str) -> None    发送文件
    text: str,
    summary_lang: str = "zh",
):
    url = extract_url(text)
    if not url:
        await reply_fn("请发送一个链接，支持 YouTube / Bilibili / TikTok / 播客等平台。")
        return

    await reply_fn(f"⏳ 开始处理：{url}")

    task_id = str(uuid.uuid4())
    await process_video_task(task_id, url, summary_lang, ...)

    result = tasks[task_id]
    if result["status"] == "completed":
        await reply_fn(result["summary"])           # 先发摘要
        await reply_file_fn(result["script_path"])  # 再发完整转录 .md
    else:
        await reply_fn(f"❌ 处理失败：{result.get('error')}")

def split_long_message(text: str, max_len: int = 4000) -> list[str]:
    """将超长文本按段落边界分片"""
```

---

## API 设计

### `POST /api/bots/configure`

```json
// Request
{
  "bots": {
    "telegram": { "enabled": true, "token": "123456:ABC..." },
    "slack":    { "enabled": false, "token": "", "extras": { "app_token": "" } },
    "feishu":   { "enabled": false, "token": "", "extras": { "app_id": "", "app_secret": "" } },
    "wecom":    { "enabled": false, "token": "", "extras": { "corp_id": "", "agent_id": "", "corp_secret": "" } },
    "discord":  { "enabled": false, "token": "" }
  }
}

// Response
{
  "bots": {
    "telegram": { "status": "running", "message": "已启动" },
    "slack":    { "status": "stopped", "message": "未启用" },
    "feishu":   { "status": "error", "message": "App Secret 无效" }
  }
}
```

### `GET /api/bots/status`

```json
{
  "bots": {
    "telegram": {
      "status": "running",
      "uptime_seconds": 3600,
      "messages_processed": 12,
      "last_error": null
    }
  }
}
```

### `POST /api/bots/wechat-webhook`

```json
// WeClaw → MediaBrief
{
  "chat_id": "wxid_abc123",
  "text": "https://www.youtube.com/watch?v=xxx",
  "chat_type": "private",    // "private" | "group"
  "sender_name": "张三"
}

// Response
{
  "reply": "⏳ 开始处理：https://www.youtube.com/watch?v=xxx"
}
// 处理完成后，MediaBrief 主动回调 WeClaw 的发送接口推送结果
```

---

## Telegram 实现要点

```
TG 用户发消息
  → Bot 长轮询 getUpdates 拉取
  → 正则提取 URL
  → 回复 "⏳ 开始处理"
  → 调用 process_video_task()
  → 管线完成
  → sendMessage 发送摘要（<4096 chars，通常够）
  → sendDocument 上传 transcript.md 文件
```

**Bot Token 获取：** 搜 @BotFather → `/newbot` → 拿到 token

**长轮询参数：**

```python
async def polling_loop(token: str):
    offset = 0
    async with httpx.AsyncClient(timeout=35) as client:
        while True:
            resp = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": offset, "timeout": 30}
            )
            for update in resp.json()["result"]:
                offset = update["update_id"] + 1
                await handle_update(client, token, update)
```

---

## Slack 实现要点

- 使用 `slack-sdk` 的 `SocketModeHandler`
- 需在 Slack API 控制台创建 App，启用 Socket Mode，获取 `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN`
- 订阅 `message.im` 事件（私聊）和 `app_mention` 事件（@机器人）

```python
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient

async def handle_message(event):
    text = event.get("text", "")
    channel = event.get("channel")
    url = extract_url(text)
    if url:
        await client.chat_postMessage(channel=channel, text=f"⏳ 开始处理：{url}")
        # ... 调用管线 ...
        # 结果通过 files_upload 上传 .md 文件
```

---

## 飞书实现要点

```
飞书开放平台 → 创建企业自建应用 → 获取 App ID + App Secret
  → 开启"机器人"能力
  → 订阅 im.message.receive_v1 事件
  → 长轮询获取事件
```

- 飞书消息无硬性长度限制，但仍建议长文本用文件上传
- 图片消息直接忽略（暂不支持 OCR 识别链接）

---

## 微信个人号接入专项

### 方案：WeClaw Sidecar

```
┌──────────┐  微信协议    ┌──────────┐  HTTP        ┌─────────────────┐
│  微信 App │ ──────────▶ │  WeClaw  │ ───────────▶ │  MediaBrief      │
│  发链接   │ ◀────────── │  (Go)    │ ◀─────────── │  :8000           │
└──────────┘             └──────────┘              └─────────────────┘
   用户手机                 本机进程                   本机进程
```

**WeClaw 是什么：**
- GitHub: [fastclaw-ai/weclaw](https://github.com/fastclaw-ai/weclaw) ⭐1500
- Go 单二进制，一行安装：`curl -sSL https://raw.githubusercontent.com/fastclaw-ai/weclaw/main/install.sh | sh`
- 支持 ACP (stdio)、CLI (子进程)、HTTP 三种 Agent 模式
- 首次运行弹出二维码，手机扫码即可登录微信
- 灵感源自 `@tencent-weixin/openclaw-weixin` npm 包

**集成方式：**
1. 用户在 ai-transcribe 前端 Settings 里启用「微信」
2. ai-transcribe 暴露 `POST /api/bots/wechat-webhook` 端点
3. 用户自行安装 WeClaw，将其 Agent 模式配置为 HTTP webhook 指向 ai-transcribe
4. WeClaw 收到微信消息 → POST 到 ai-transcribe → 转录 → ai-transcribe 回调 WeClaw HTTP API 发回微信

**ai-transcribe 不直接处理微信协议**，只暴露一个标准的 HTTP webhook，微信协议的复杂性完全由 WeClaw sidecar 承担。微信协议变动时只需更新 WeClaw，与 ai-transcribe 无关。

### WeClaw 配置示例

```json
{
  "agents": {
    "transcriber": {
      "mode": "http",
      "webhook_url": "http://localhost:8000/api/bots/wechat-webhook",
      "response_url": "http://localhost:8000/api/bots/wechat-send"
    }
  },
  "default_agent": "transcriber"
}
```

### 参考项目

| 项目 | ⭐ | 说明 |
|------|-----|------|
| [fastclaw-ai/weclaw](https://github.com/fastclaw-ai/weclaw) | 1500 | Go 独立微信桥接，QR 码登录 |
| [freestylefly/openclaw-wechat](https://github.com/freestylefly/openclaw-wechat) | 1667 | OpenClaw 微信插件，需 OpenClaw 框架 |
| [dingxiang-me/OpenClaw-Wechat](https://github.com/dingxiang-me/OpenClaw-Wechat) | 527 | 企业微信 + 个人微信，支持群聊 |

---

## 前端 Settings 弹窗设计

```
┌─────────────────────────────────────────────┐
│  ⚙ 设置                                  [✕] │
├─────────────────────────────────────────────┤
│                                             │
│  📡 Bot 集成                                │
│                                             │
│  ┌─ Telegram ─────────────────────────────┐ │
│  │  [══ 已启用 ══]     ● 运行中 2h         │ │
│  │  Bot Token  [····················] 👁   │ │
│  │  获取方式: @BotFather → /newbot         │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌─ Slack ────────────────────────────────┐ │
│  │  [══ 已禁用 ══]     ○ 未启动            │ │
│  │  Bot Token  [····················]      │ │
│  │  App Token  [····················]      │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌─ 飞书 ─────────────────────────────────┐ │
│  │  [══ 已禁用 ══]     ○ 未启动            │ │
│  │  App ID      [····················]     │ │
│  │  App Secret  [····················]     │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌─ 微信（个人号）────────────────────────┐ │
│  │  ℹ️ 需额外安装 WeClaw sidecar           │ │
│  │  Webhook URL: /api/bots/wechat-webhook  │ │
│  │  [查看配置指南]                          │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌─ 企业微信 ─────────────────────────────┐ │
│  │  [══ 已禁用 ══]     ○ 未启动            │ │
│  │  Corp ID     [····················]     │ │
│  │  Agent ID    [····················]     │ │
│  │  Corp Secret [····················]     │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌─ Discord ──────────────────────────────┐ │
│  │  [══ 已禁用 ══]     ○ 未启动            │ │
│  │  Bot Token  [····················]      │ │
│  └────────────────────────────────────────┘ │
│                                             │
│        [保存配置]          [取消]            │
└─────────────────────────────────────────────┘
```

每个平台卡片：
- **Toggle 开关**：控制启用/禁用
- **状态指示灯**：● 绿（运行中）/ ○ 灰（未启动）/ ● 红（错误）
- **Token 输入**：password 类型，带 👁 显示/隐藏切换
- **一行提示**：告诉用户如何获取 Token/App ID
- 微信特殊处理：显示 webhook URL + 配置指南链接（不需 token）

配置存储：
- 前端 `localStorage` 持久化
- 每次点「保存」时 `POST /api/bots/configure` 同步后端

---

## 文件变更清单

```
新增文件：
  backend/bots/__init__.py       # 导出 BotManager
  backend/bots/base.py           # BaseBot 抽象类 + BotConfig + BotStatus
  backend/bots/common.py         # URL提取、消息格式化、超长分片
  backend/bots/manager.py        # BotManager：配置比对、启停控制
  backend/bots/telegram.py       # TelegramBot(BaseBot) — Long Polling
  backend/bots/slack.py          # SlackBot(BaseBot) — Socket Mode
  backend/bots/feishu.py         # FeishuBot(BaseBot) — 事件订阅
  backend/bots/wecom.py          # WeComBot(BaseBot) — 企微Bot API
  backend/bots/discord.py        # DiscordBot(BaseBot) — Gateway
  backend/routers/bots.py        # Bot HTTP 路由
  docs/bot-integration-design.md # 本文档

修改文件：
  backend/main.py                # +5行：startup 启动 BotManager，shutdown 停止
  static/index.html              # Settings 弹窗 HTML
  static/js/                     # 新增 bots.js 配置管理
  requirements.txt               # 按需加 slack-sdk

不改动（零侵入）：
  backend/pipeline.py            # 完全复用
  backend/task_store.py          # 完全复用
  backend/services.py            # 完全复用
  backend/routers/transcribe.py  # 完全复用
```

---

## 实现计划

| Phase | 内容 | 新增文件 | 预估 |
|-------|------|----------|------|
| **1** | 后端基础架构：`base.py` + `manager.py` + `common.py` + `routers/bots.py` | 4 | 1 天 |
| **2** | Telegram 实现 + 前端 Settings 弹窗（基础版） | 2 + 前端 | 1 天 |
| **3** | 端到端验证：TG 发链接 → 转录 → 收消息 | — | 半天 |
| **4** | Slack 实现 | 1 | 1 天 |
| **5** | 飞书实现 | 1 | 1 天 |
| **6** | 微信（WeClaw webhook + 配置文档） | 路由扩展 | 半天 |
| **7** | 企业微信 + Discord（按需） | 2 | 1-2 天 |

---

## 待确认

1. 微信是否需要群聊支持？WeClaw 支持群聊，但需额外配置
2. Settings 弹窗是独立 Modal 还是扩展当前设置面板？需看现有前端结构
3. Discord 是否有需求？还是 TG + Slack + 飞书 + 微信 就够？
