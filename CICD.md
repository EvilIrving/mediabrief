# MediaBrief macOS CI/CD 签名与公证

更新时间：2026-08-13

## 当前状态

仓库已经加入 `.github/workflows/release-macos.yml`：

- `workflow_dispatch` 可以手动执行，适合首次验证；
- 推送 `v*` Tag 后会自动执行；
- 使用 GitHub `macos-15` Apple Silicon Runner；
- 构建和签名拆成两个 Job，构建 Job 不接触 Apple 凭据；
- 签名 Job 使用受保护的 `macos-release` Environment；
- 临时导入 `Developer ID Application` 证书；
- 使用 App Store Connect Team API Key 调用 `notarytool`；
- 调用 `scripts/sign_and_package.sh notarize` 完成 app/DMG 签名、公证、staple 和 Gatekeeper 验证；
- 成功后上传 DMG、发行清单和公证日志；Tag 触发时把 DMG 和清单附加到 GitHub Release。

当前还没有向 GitHub 写入任何 Apple 凭据，也没有执行过远端正式公证。凭据准备完成前，签名 Job 会明确失败，不会降级生成未签名发行物。

## 明天需要准备的内容

### 1. 导出 Developer ID Application 证书

在本机“钥匙串访问”中找到有效的：

```text
Developer ID Application: <团队或个人名称> (<Team ID>)
```

展开证书，确认下面存在对应私钥。选择证书和私钥一起导出为 `.p12`，设置一个强导出密码。

不要把 `.p12`、密码或 Base64 文本保存到仓库。

将 `.p12` 转为适合 GitHub Secret 的单行 Base64：

```bash
base64 -i DeveloperID.p12 | pbcopy
```

### 2. 创建 App Store Connect Team API Key

进入 App Store Connect：

```text
Users and Access → Integrations → App Store Connect API → Team Keys
```

创建供 MediaBrief 公证使用的 Team Key，并记录：

- Key ID；
- Issuer ID；
- 下载得到的 `AuthKey_<KEY_ID>.p8`。

必须使用 Team Key。Apple 的 Individual Key 不能用于 `notarytool`。`.p8` 只能下载一次，下载后立即放入密码管理器或安全备份。

将 `.p8` 转为 Base64：

```bash
base64 -i AuthKey_<KEY_ID>.p8 | pbcopy
```

### 3. 创建 GitHub Environment

在仓库中进入：

```text
Settings → Environments → New environment → macos-release
```

建议开启 Required reviewers。这样即使有人创建了 Tag，签名 Job 也必须经发布负责人确认后才能读取 Apple 凭据。

在这个 Environment 中添加以下 Secrets：

| Secret | 内容 |
| --- | --- |
| `MACOS_CERTIFICATE_BASE64` | `.p12` 的 Base64 |
| `MACOS_CERTIFICATE_PASSWORD` | `.p12` 导出密码 |
| `MACOS_KEYCHAIN_PASSWORD` | CI 临时 Keychain 使用的随机强密码 |
| `APPSTORE_KEY_ID` | App Store Connect Team API Key ID |
| `APPSTORE_ISSUER_ID` | App Store Connect Issuer ID |
| `APPSTORE_PRIVATE_KEY_BASE64` | `.p8` 的 Base64 |

这些值不要写入 GitHub Variables；必须使用 Secrets。

### 4. 保护发布入口

建议为 `main` 和 `v*` Tag 配置 Repository Ruleset：

- 只有维护者可以创建或更新 `v*` Tag；
- 发布提交必须已经合并到受保护的 `main`；
- `.github/workflows/release-macos.yml`、`scripts/sign_and_package.sh` 和 entitlements 的改动需要代码审查；
- 不允许外部 PR 或 `pull_request_target` 获得 `macos-release` Environment。

## 首次远端验证

先确认以下文件与同一批签名脚本改动已经提交并推送；GitHub Runner 只能读取远端提交，无法看到本机未提交文件：

```text
.github/workflows/release-macos.yml
.github/workflows/build.yml
scripts/sign_and_package.sh
scripts/build_macos.sh
pyinstaller/entitlements.plist
pyinstaller/deno-entitlements.plist
CICD.md
```

先不要创建正式 Tag。在 GitHub 的 Actions 页面手动运行 `macOS Signed Release`。

预期结果：

1. `build` Job 在 ARM64 Runner 上完成前端、Python、FFmpeg、Deno 和 PyInstaller 构建；
2. 进入 `sign-notarize` Job 前触发 Environment 审批；
3. Runner 临时创建 Keychain，并确认恰好有一个 Developer ID Application 身份；
4. `notarytool` 接受 app 和 DMG 两次提交；
5. `stapler validate`、`codesign --verify --deep --strict` 和 `spctl` 全部通过；
6. Actions Artifacts 中出现 `mediabrief-macos-signed`；
7. 下载 DMG 后，挂载内容包含 `MediaBrief.app` 和 `Applications` 快捷方式。

首次验证失败时，查看对应 Job 和上传的 `notary-*.json`。不要把 Secrets、`.p12` 或 `.p8` 上传为 Artifact。

## 正式 Tag 发布

远端手动验证通过后，从受保护的发布提交创建版本 Tag：

```bash
git tag v1.0.0
git push origin v1.0.0
```

Tag 会自动触发签名工作流。只有公证、staple 和 Gatekeeper 全部成功，DMG 才会上传到 GitHub Release。

工作流会检查 Tag 去掉 `v` 后是否与应用的 `CFBundleShortVersionString` 完全一致；版本不一致会停止发布。

## 已知遗留问题

当前工作流已经覆盖自动化签名和公证，但构建输入还没有完全锁定：

- `scripts/build_macos.sh` 仍会在构建期间升级 yt-dlp；
- `pyinstaller/ai_transcriber.spec` 仍会在 PyInstaller 阶段联网获取 Whisper base；
- `requirements.txt` 中还有范围依赖；
- PyInstaller spec 中应用版本仍需切换到项目统一版本来源；
- GitHub Actions 引用目前跟随官方 major tag，正式供应链加固时应固定到完整 commit SHA。

这些问题不会让签名失败被误报为成功，但会影响构建的可复现性。完成首次 CI 公证基线后，应继续按 `ProductizationPlan.md` Task 1 收紧。

## 官方参考

- Apple：<https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution>
- Apple `notarytool`：<https://developer.apple.com/documentation/security/customizing-the-notarization-workflow>
- App Store Connect API Key：<https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api>
- GitHub macOS 签名证书：<https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications>
- GitHub-hosted Runner：<https://docs.github.com/en/actions/reference/runners/github-hosted-runners>

## 安全边界

- PR 构建不读取 Apple Secrets；
- 只有 `sign-notarize` Job 绑定 `macos-release` Environment；
- `.p12`、`.p8` 和临时 Keychain 只写入 `$RUNNER_TEMP`；
- GitHub-hosted Runner 在 Job 结束后销毁；工作流仍通过 `if: always()` 主动删除临时凭据；
- 日志和发行清单只包含签名身份摘要、公证 submission ID、哈希与验证结果，不包含密码或私钥；
- 任何签名、公证、staple、DMG 或 Gatekeeper 检查失败都会返回非零状态并阻止发布。
