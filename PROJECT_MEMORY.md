# Project Memory

## 打包版首启失败的三个发行约束 · 2026-08-13 09:23 · grok

安装后第一条 B 站链接（无字幕）会走本地下载 + Whisper。发行 FFmpeg 用 `--disable-everything`，configure 组件名是 `pcm_s16le` 不是 `s16le`；漏掉时 `-f s16le` 失败，完好 AAC 会被标成 Unusable audio。解码现已改走 wav muxer，构建脚本必须同时启用 `pcm_s16le` 和 `wav`。

`mlx.core` 初始化会 `import mlx._reprlib_fix`。这是 C 扩展拉的纯 Python 模块，PyInstaller 不会自动收；漏了只报 `Encountered an error while initializing the extension`。spec 必须 hiddenimport `mlx._reprlib_fix`。`mlx_whisper.timing` 在 import 时就要 `scipy.signal`，发行包排除完整 scipy，由 `transcriber._ensure_mlx_whisper_import_shims` 提供带 `__version__` 的桩。Hardened Runtime 需要 JIT / unsigned executable memory / disable-library-validation，但缺 `_reprlib_fix` 时加 entitlements 也救不了。

VAD 末窗常比 ffprobe 时长多几毫秒。质量复核必须裁剪时间轴，不能 `raise` 把已经得到的转录整单作废。

## 产品化与 AI Native 是同一软件的两层 · 2026-08-13 · grok

`Plan.md` 和 `ProductizationPlan.md` 不是互相替代的需求。产品层要求装上就能用，环境、模型、库由软件自己管；AI Native 层是应用内轻量命令 Agent，用来处理 yt-dlp 穷举不完的站点失败，以及解释宿主没能自动修好的环境问题。

能事先确定的事先由宿主做：官方 Hugging Face 失败后立刻换 `https://hf-mirror.com`，不要先问用户，也不要先打模型。Agent 通过同一份运行时画像看见 FFmpeg / Deno / MLX / yt-dlp / Whisper 准备状态。不要把已经落地的恢复 Loop、音频策略、启动端口/单实例/模型等待当成没做。也不要把它扩成通用编程 Agent。

这条修正了把两份计划理解成冲突、以及把恢复系统当成产品噪音的判断。

## 首次启动必须自动准备最佳转录环境 · 2026-08-13 02:01 · /root

MediaBrief 的发行版必须在主窗口尽快出现后，立即后台自动准备完整运行环境。`large-v3-turbo` 是正常产品路径：首次启动自动下载并负责断点续传、失败重试和网络恢复后继续，普通用户不需要确认下载、选择模型或进入设置。需要本地转录的任务在模型准备期间应显示明确等待状态，不能因为下载尚未完成而静默使用 `base`。

内置 `base` 仅用于 `large-v3-turbo` 因断网、持续下载失败或设备环境异常而确实无法使用时的应急降级；发生降级必须明确告知用户原因和质量影响。FFmpeg、FFprobe、Deno、MLX、yt-dlp 等组件同样由发行版自动提供、检查和维护，版本状态、更新结果与失败原因应进入统一诊断，不能让用户安装环境或做技术选择。
