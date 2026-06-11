# TODO — 桌面打包后续优化

## 高优先级

- [ ] **ICNS 图标** — 将 `static/icon128.svg` 转为 `.icns` 格式，替换 PyInstaller spec 中的 `BUNDLE_ICON`
- [ ] **首次启动引导** — 用户首次打开时引导配置 API Key（当前需手动在 `.app/Contents/MacOS/` 下创建 `.env`）
- [ ] **macOS 代码签名 + 公证** — 否则分发时会有"无法验证开发者"安全警告

## 中优先级

- [ ] **Whisper 模型下载状态** — 前端调用 `/api/model-status` 展示"模型下载中"提示，避免用户误以为卡住
- [ ] **Windows 构建验证** — 在 Windows 机器上跑 `scripts/build_windows.ps1`，确认 .exe 可正常启动
- [ ] **窗口关闭确认** — 目前 `confirm_close=False`，关闭窗口即退出，考虑加一个"任务进行中"的提示

## 低优先级

- [ ] **自动更新** — macOS 用 Sparkle，Windows 用 Squirrel
- [ ] **安装器** — macOS `.dmg` 背景图 + 拖拽到 Applications 的引导
- [ ] **通知** — 转录完成后系统通知（pywebview 不支持原生通知，需额外处理）
- [ ] **菜单栏图标** — macOS 菜单栏常驻，窗口可关闭但服务不退出
