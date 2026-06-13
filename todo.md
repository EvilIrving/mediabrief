# TODO — 桌面打包后续优化

## 高优先级

- [x] **ICNS 图标** — 将 `static/icon128.svg` 转为 `.icns` 格式，替换 PyInstaller spec 中的 `BUNDLE_ICON`
- [x] **首次启动引导** — 用户首次打开时引导配置 API Key（当前需手动在 `.app/Contents/MacOS/` 下创建 `.env`）
- [x] **macOS 代码签名 + 公证** — 已创建 `scripts/sign_and_package.sh`（需 Apple Developer 证书才能实际签名）

## 中优先级

- [x] **Whisper 模型下载状态** — 前端调用 `/api/model-status` 展示"模型下载中"提示，避免用户误以为卡住
- [ ] **Windows 构建验证** — 在 Windows 机器上跑 `scripts/build_windows.ps1`，确认 .exe 可正常启动
- [x] **窗口关闭确认** — 目前 `confirm_close=False`，关闭窗口即退出，考虑加一个"任务进行中"的提示

## 前端迁移（React）后续

- [x] **迁移到 React + TypeScript** — 已将 `static/` 的纯 JS UI 重写为 `frontend/` 的 React SPA（Vite + Tailwind v4 + HashRouter），构建产物输出到 `static/dist/`，由 FastAPI 提供
- [ ] **引入 shadcn/Radix 组件** — 当前移植复用了原有 oklch 设计变量与类名以保证 1:1 视觉一致；可按需将 Tabs / Select / Dialog / Toast 等替换为 shadcn 原语
- [ ] **逐页浏览器实测** — 在真实浏览器/桌面窗口中逐页核对 transcribe / download / rss / history 行为
- [ ] **历史消息原文切换** — 在 history 详情里增加“原文”视图，可在原文与转写内容之间切换，便于核对历史消息内容
- [ ] **移除旧版前端** — 确认无回退需求后删除 `static/js/*` 与旧 `static/index.html`
- [ ] **install.ps1 / install.bat 对齐** — 为 Windows 安装脚本补充与 `install.sh` 一致的前端构建步骤

## 低优先级

- [ ] **自动更新** — macOS 用 Sparkle，Windows 用 Squirrel
- [x] **安装器** — DMG 已集成到 `scripts/sign_and_package.sh`，含 Applications 快捷方式
- [ ] **通知** — 转录完成后系统通知（pywebview 不支持原生通知，需额外处理）
- [ ] **菜单栏图标** — macOS 菜单栏常驻，窗口可关闭但服务不退出
- [ ] 绑定 TG/slack，tg发送链接，自动下载并转录，转录完成后发回文本消息。 
