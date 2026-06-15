# source-artifacts — 源控产物清洁

## 规则

以下类型的文件不得进入版本控制，除非有明确的产品、文档、测试或发布理由：

### 禁止的文件类型

| 类别 | 示例 | 例外 |
|------|------|------|
| 构建产物 | `static/`（CI 构建输出）、`dist/`、`.next/`、`__pycache__/` | `static/` 中的 hand-crafted 文件（favicon 等） |
| 临时文件 | `temp/`、`*.tmp`、`*.log`、`*.pid` | 无 |
| IDE/编辑器个人配置 | `.vscode/settings.json`（非共享）、`.idea/` | `.vscode/extensions.json`（共享推荐） |
| 依赖缓存 | `node_modules/`、`venv/`、`.pnpm-store/` | package-lock 文件 |
| 模型缓存 | `~/.cache/huggingface/`、`models/`、`*.bin`、`*.pt` | 嵌入的离线 fallback 模型（需注明） |
| 音视频文件 | `*.mp3`、`*.mp4`、`*.wav`、`*.webm`、`*.mkv` | 测试 fixture（放在 `tests/fixtures/` 中，需注明来源） |
| 截图与录屏 | `*.png`（非文档用）、`*.mov`、`*.gif` | `docs/assets/` 中的文档截图 |
| 环境文件 | `.env`、`.env.local`、`.env.production` | `.env.example`（不含真实密钥） |

### 检查方法

```bash
# 检查是否有不该提交的文件
git status  # 查看未跟踪文件
git ls-files | grep -E '\.(log|tmp|pid|pyc)$'  # 已跟踪的文件
```

### 已经加入 .gitignore 的目录

- `static/` — CI 构建产物
- `temp/` — 运行时数据（sqlite、tasks、downloads）
- `.env` — 环境变量
- 音视频文件、模型缓存、FFmpeg 二进制
