# 测试方案 — AI Transcriber

本文件描述前后端单元测试的目标、分层、目录约定与运行方式。原则：**纯逻辑优先**、
**架构隔离**（测试不跨越 router / pipeline / stage 的分层），测试贴合各自生态的惯例。

---

## 1. 目标与边界

- **测什么**：可独立验证的纯逻辑与编排——错误映射、文本清洗、配置契约、来源提取编排、
  前端展示变换、i18n 一致性。
- **不测什么**：真实网络请求（yt-dlp/LLM/Whisper 下载）、真实文件系统重活、第三方库内部。
  这些通过**依赖注入 + 假对象**隔离，或留给端到端手测。
- **隔离红线**：stage 模块不被 router 反向依赖；测试 `sources.py` 这类编排时用假的
  `video_processor` / `transcriber` / 回调注入，**不触碰** `services` 与 `task_store`。

---

## 2. 后端（已落地）

### 选型
- `pytest` + `pytest-asyncio`（`asyncio_mode=auto`，`async def test_*` 免逐个标注）。
- 开发依赖独立于打包构建：`requirements-dev.txt`。

### 目录
```
backend/
├── pytest.ini                    # testpaths=tests, asyncio_mode=auto
└── tests/
    ├── conftest.py               # 注入 backend/ 到 sys.path，沿用运行时 flat import
    ├── test_error_messages.py    # 签名匹配 / 领域异常透传 / 两张签名表同序
    ├── test_llm_sanitize.py      # 尾部寒暄、转录过程说明 / <think> 块剥离
    ├── test_config.py            # frozen 不可变、派生属性、默认值契约
    └── test_sources.py           # extract_media_source 字幕/Whisper 两路径（依赖注入）
```

### 运行
```bash
pip install -r requirements.txt -r requirements-dev.txt
pnpm test:api          # = cd backend && ../venv/bin/python -m pytest
```

### 设计要点
- **conftest.py** 解决「后端从 `backend/` 运行、用 flat import」的约定：把 backend 根注入
  `sys.path`，测试里 `import error_messages` 直接生效，无需改产品代码的 import 风格。
- **test_sources.py** 是隔离样板：`FakeVideoProcessor` / `FakeTranscriber` / `Recorder`
  以参数注入，断言阶段广播、跳过集合、mode 设置，完全不依赖单例与全局状态。
- **签名表同步测试**：`_SIGNATURES` 与 `_SIGNATURE_CODES` 必须同序同 needle，否则用户
  文案与稳定 code 错位——用一条断言锁死这个易碎约束。

### 后续可扩展（按需）
| 模块 | 测什么 | 隔离手段 |
|------|--------|----------|
| `exporter.py` | MD/TXT 内容生成、文件名清洗 | 写入临时目录 `tmp_path` |
| `whisper_models.py` | `_resolve_available_size` 回退到 `base` 的逻辑 | mock 模型缓存探测 |
| `rss_reader.py` | feed 解析 / 字段归一化 | 喂本地 RSS 样本字符串 |
| `routers/*` | HTTP 状态码映射（领域异常 → 4xx/5xx） | FastAPI `TestClient` + mock pipeline |

---

## 3. 前端（设计，待实现）

### 选型
- **Vitest + jsdom + @testing-library/react**。复用现有 `vite.config.ts` 的 `@/` alias 与
  ESM 配置，零额外构建链，比 Jest 更契合 Vite 8 工具栈。

### 目录（测试与被测模块同级 `__tests__/`，前端社区惯例，便于 alias 解析）
```
frontend/
├── vitest.config.ts                       # 复用 vite resolve.alias；环境分层
└── src/
    ├── lib/__tests__/utils.test.ts         # cn() tailwind 类合并/去重（node 环境）
    ├── features/rss/__tests__/rssUtils.test.ts
    │     # mergeFeedMetadata / feedSummaries / normalizeImportList
    │     # 去重、去尾斜杠、localStorage 损坏数据兜底（mock localStorage）
    ├── i18n/__tests__/dictionaries.test.ts # 四语言 key 集合一致性（en/zh/ja/ko 无缺漏）
    └── hooks/__tests__/useAutoDismissError.test.ts  # 定时清除（vi.useFakeTimers）
```

### 环境分层
- 纯函数（`utils`、`rssUtils`、`dictionaries`）→ 默认 **node** 环境，跑得快。
- hooks / 组件 → **jsdom**。
- `rssUtils` 依赖 `localStorage`：测试注入内存版 mock，专门覆盖 `readMetaMap` 的
  `try/catch` 损坏 JSON 兜底分支。

### 最高价值用例
- **i18n key 一致性**：新增文案漏翻译任一语言时立即失败，守住「UI 文案唯一来源」约定。
- **normalizeImportList 去重**：RSS 导入的去尾斜杠 + 去重逻辑是用户可感知的正确性热点。

### 运行（实现后）
```bash
cd frontend && pnpm add -D vitest jsdom @testing-library/react @testing-library/jest-dom
pnpm test          # vitest run
```

---

## 4. CI 接入（建议）

仓库已有 `.github/workflows/`。建议新增/合入一个 `unit-tests` job：

```yaml
# 后端
- run: pip install -r requirements.txt -r requirements-dev.txt
- run: cd backend && python -m pytest
# 前端（实现后）
- run: cd frontend && pnpm install && pnpm test
```

后端测试无需 FFmpeg / 模型 / 网络，秒级完成，适合每次 PR 必跑。
