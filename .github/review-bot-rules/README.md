# Review Bot Rules — AI Transcriber

项目专用 CodeRabbit 审查规则。每个规则对应一个关注面，在 `.coderabbit.yaml` 中按文件类型分派。

## 规则索引

| 规则 | 适用文件 | 关注面 |
|------|---------|--------|
| `python-imports.md` | `backend/**/*.py`（非子包内） | 禁止根模块之间的相对导入 |
| `python-boundaries.md` | `backend/**/*.py` | 路由→编排→服务三层边界 |
| `python-cancellation.md` | `backend/**/*.py`（长任务路径） | 取消令牌检查、子进程安全回收 |
| `python-security.md` | `backend/**/*.py` | 无硬编码密钥、ffmpeg 绝对路径、禁止 shell=True |
| `frontend-i18n.md` | `frontend/src/**/*.{ts,tsx}`, `dictionaries.ts` | 四语言覆盖、禁止硬编码字符串 |
| `frontend-patterns.md` | `frontend/src/**/*.{ts,tsx}` | Error/Toast 模式、API 调用、组件结构 |
| `source-artifacts.md` | `**/*` | 禁止生成文件进入版本控制 |
