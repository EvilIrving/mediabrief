# 获取与转写

## fetch_media.py

```bash
python scripts/fetch_media.py URL --out DIR
python scripts/fetch_media.py URL --out DIR --video
python scripts/fetch_media.py URL --out DIR --cookies-from-browser chrome
```

默认：音频 + 字幕（含 auto-subs）+ `source.json`。`--video` 才下画面。

`source.json`：`url` `title` `extractor` `audio` `subtitles` `video` `mode_hint`（有非空字幕文件则为 `subtitle`）。

按 stderr 处理，不要把 ffmpeg/yt-dlp 原文丢给用户当结论：

| 信号 | 做法 |
|---|---|
| sign in / not a bot / login required | `--cookies-from-browser` |
| private | 停，说明私密不可取 |
| members-only / age | 需要已登录会员或成年账号的 cookie |
| geo / not available in your country | 地区限制 |
| 429 | 限流，过后再试 |
| 403 / 412 | 风控或过期链接 |
| 404 / video unavailable | 链接失效或已删 |
| only images are available | 没有音视频 |
| unsupported url / no video formats | 来源解析不到媒体 |
| requested format is not available | 换 cookie，或 `--video` 后再抽音 |
| timed out / connection | 网络或代理 |
| postprocessing / no decoder / ffmpeg | 文件或编码问题，不要假装已转写 |

同一组参数连续失败两次就换策略（cookie / 音频格式 / 带画面抽音），不要用相同命令空转。

yt-dlp 过旧先升级，不要手写页面解析替代脚本。

## transcribe.py

```bash
python scripts/transcribe.py AUDIO --out transcript.raw.md
python scripts/transcribe.py AUDIO --out transcript.raw.md --language zh
python scripts/transcribe.py AUDIO --out transcript.raw.md --model mlx-community/whisper-small-mlx
```

Apple Silicon 默认 `mlx-community/whisper-small-mlx`；要质量再换 `whisper-large-v3-turbo`。语言能稳定专名时才加 `--language`。

权重下载：Hugging Face 连不上时走 ModelScope 同仓库直链。不要用 hf-mirror 当下权重——API 通了，大文件仍会 302 到海外 CDN 中断。

字幕转文本：去时间轴、序号、连续重复行；保留顺序。
