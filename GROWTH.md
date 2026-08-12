# Growth Context

*Last updated: 2026-08-12*
*Status: synced from product + code (MediaBrief rename, bots/TTS, English screenshots, demo video path).*

## Product
- **Name:** MediaBrief
- **One-liner:** Self-hosted tool that turns any media link into a clean transcript and AI summary.
- **What it does:** Paste a link from YouTube, Bilibili, TikTok, Apple Podcasts, SoundCloud, and 30+ more (via yt-dlp), or drop a local audio/video/text file. MediaBrief pulls existing subtitles when available, falls back to Faster-Whisper when they are not, then cleans and summarizes with a user-configured OpenAI-compatible LLM. Summaries stream first while the full transcript refines in the background. RSS automation (including YouTube channels), media download, Telegram/Slack bots, optional TTS readout, and export to MD/TXT/DOCX/PDF are built in. Runs as a self-hosted web app (optional desktop window via pywebview).
- **Category:** self-hosted media transcription + AI summary web app

## Platform & distribution
- **Platform / requirements:** Python 3.12+ backend (FastAPI/uvicorn + SQLite), Node/pnpm frontend (Vite + React 19). FFmpeg and yt-dlp required (bundled binaries present for packaging). Whisper via Faster-Whisper (CTranslate2). Bring your own OpenAI-compatible LLM endpoint.
- **How it ships / installs:** Docker (`Dockerfile` + `docker-compose.yml`), install scripts (`install.sh` / `install.ps1` / `install.bat`), run from source (`start.py`), macOS/Windows desktop packaging (PyInstaller + pywebview).
- **Updates:** Manual (git pull / rebuild Docker image). yt-dlp self-updates on a throttled weekly schedule in packaged builds. No full app auto-update channel.
- **Repo:** https://github.com/EvilIrving/mediabrief
- **Site:** none (repo is the public surface)

## Pricing model
- Free and open source under the **MIT License**.
- **Bring-your-own-model**: user supplies their own OpenAI-compatible API key (and optional TTS key). MediaBrief itself is free. No tiers, no SaaS billing.

## Audience
- **Who it's for:** researchers, content creators, product managers, and lifelong learners who need text instead of hours of audio/video. Secondary: RSS power users; self-hosters and privacy-minded users who want local processing with their own model.
- **Why they reach for it:** turn multi-hour interviews or a backlog of podcast episodes into readable key points in minutes; subtitle-first speed when captions exist; keep data and model choice on their side; automate recurring feeds.

## Differentiators (ranked, all true)
1. **Subtitles-first:** pulls existing captions without downloading audio; Whisper only when needed.
2. **Summary-first streaming:** summary appears while transcript optimization continues.
3. **RSS automation incl. YouTube channels:** subscribe and summarize/download new items.
4. **Bring-your-own-model:** any OpenAI-compatible API, configured in the UI with model discovery.
5. **Self-hosted and private:** runs on your machine; history in local SQLite.
6. **Bots + voice (shipped):** Telegram and Slack bots send links and get summary + transcript back; optional Doubao TTS to read summaries aloud.
7. **Broad input + export:** 30+ platforms via yt-dlp plus local media/text; export MD, TXT, DOCX, PDF; share summary as image.

## Competitors / alternatives
| Name | Model | Honest strength | How we differ |
|------|-------|-----------------|---------------|
| Otter.ai / cloud transcription SaaS | Paid SaaS | Polished, real-time, collaboration | Free, self-hosted, BYO-model, link-based multi-platform + RSS |
| "Summarize YouTube" GPT tools / extensions | Free/freemium SaaS | Zero setup in browser | 30+ platforms, local files, RSS, full transcript + history, runs locally |
| Whisper / whisper.cpp (raw) | Free OSS | Strong local ASR | UI, subtitle-first path, LLM cleanup + summary, RSS, export, bots |
| Other self-hosted transcribers | Free OSS | Local peer tools | Summary-first streaming, RSS incl. channels, BYO-model, bots |

## Channels
- **Where this audience is:** GitHub, Hacker News (Show HN), Product Hunt, r/selfhosted, r/opensource, r/DataHoarder, r/LocalLLaMA, r/podcasting, awesome-selfhosted, Docker Hub.
- **Languages to publish in:** English, 简体中文, 日本語, 한국어 (UI + READMEs).

## Voice
- **Tone:** efficient, capable, unobtrusive (per PRODUCT.md). Direct, technical but not cold. No marketing superlatives, no emoji overuse.
- **Words to use / avoid:** subtitle-first, summary-first, self-hosted, BYO-model, 30+ platforms. Avoid SaaS marketing language, "magic", inflated numbers, fake social proof, vague claims like "powerful" or "revolutionary."

## Proof points (REAL only)
- Public GitHub repo: https://github.com/EvilIrving/mediabrief
- Docker, install scripts, desktop packaging scripts present.
- Screenshots: `docs/img/{home,rss,history}.png` (English UI, MediaBrief brand).
- Demo video path: `docs/img/demo.mp4` (drop-in; see `docs/img/README.md`). Public play URL after push to main: `https://github.com/EvilIrving/mediabrief/raw/main/docs/img/demo.mp4`
- Do not invent star counts, download counts, or user testimonials.

## Links
- **Social handles / accounts:** none captured
- **Press / contact:** none captured

## Visual assets (for README / launch)
| Asset | Path | Notes |
|-------|------|--------|
| Demo video | `docs/img/demo.mp4` | Must be committed (gitignore exception). Prefer under ~25 MB. |
| Home shot | `docs/img/home.png` | Transcribe + results |
| RSS shot | `docs/img/rss.png` | Subscriptions |
| History shot | `docs/img/history.png` | Saved summaries |
