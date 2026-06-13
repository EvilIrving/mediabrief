# AGENTS.md — AI Transcriber

## Project Overview

AI Transcriber transforms video/audio/podcast links (30+ platforms via yt-dlp) and local media files into optimized transcripts and AI summaries. It pulls subtitles when available, falls back to Whisper transcription, then cleans everything with an LLM. RSS automation for recurring sources. Multi-language UI (EN/ZH/JA/KO) and summary output.

## Architecture

```
┌─ frontend/ (React 19 + TypeScript + Vite + Tailwind v4) ─┐
│  Built to ../static/ via `pnpm build`                     │
│  Dev: Vite proxies /api → localhost:8000                  │
└───────────────────────────────────────────────────────────┘
                              │
                              ▼ Static files + REST API + SSE
┌─ backend/ (Python 3.12 + FastAPI + asyncio) ─────────────┐
│  main.py          ── App assembly, CORS, static mount     │
│  config.py        ── Frozen dataclass defaults            │
│  services.py      ── Processor singletons                 │
│  pipeline.py      ── Task orchestration (post-extract)    │
│  task_store.py    ── Task state, SSE broadcast, DB calls  │
│  db.py            ── SQLite persistence (asyncio.to_thread)│
│  cancellation.py  ── Task cancellation + orphan cleanup   │
│  summarizer.py    ── LLM summary + two-step               │
│  transcriber.py   ── Faster-Whisper (CTranslate2)         │
│  translator.py    ── LLM translation                      │
│  video_processor.py ── yt-dlp + FFmpeg                    │
│  llm_sanitize.py  ── LLM artifact cleanup                 │
│  rss_reader.py    ── RSS feed parsing                     │
│  exporter.py      ── MD/TXT/DOCX/PDF export               │
│  providers.py     ── Protocol-based backend builders      │
│  routers/                                                 │
│    core.py        ── /, /api/models                       │
│    transcribe.py  ── Process/upload, SSE, retry, delete   │
│    downloads.py   ── Format detection + file serving      │
│    rss.py         ── /api/rss/*                           │
│    export.py      ── /api/export                          │
│    queue.py       ── /api/tasks/active                    │
│  platforms/                                               │
│    _base.py       ── Abstract platform handler            │
│    youtube.py / bilibili.py / generic.py                  │
└───────────────────────────────────────────────────────────┘
```

### Pipeline Flow

```
Input (URL / file upload / RSS)
  → yt-dlp subtitle extraction (fast path, no download)
  → Whisper transcription (fallback, when no subs)
  → LLM sanitize (typos, sentence completion, paragraphing)
  → LLM summary (parallel with sanitize; optional two-step)
  → LLM translation (if target ≠ source language)
  → Exporter (MD/TXT/DOCX/PDF)
```

Summaries stream via SSE first; transcript optimization continues in background.

## Repository Layout

```
ai-transcriber/
├── backend/           # Python backend (the working dir at runtime)
│   ├── main.py        # Entry point: FastAPI app
│   ├── routers/       # HTTP route handlers (flat modules)
│   ├── platforms/     # yt-dlp extractors per platform
│   └── ...
├── frontend/          # React SPA (Vite + TypeScript + Tailwind v4)
│   ├── src/
│   │   ├── App.tsx            # Root, theme provider, router
│   │   ├── i18n/              # dictionaries.ts + I18nContext
│   │   ├── components/        # Navbar, Footer, Markdown, ErrorBanner, IconSprite
│   │   └── hooks/             # useAutoDismissError
│   ├── vite.config.ts         # Build outDir = ../static
│   └── package.json
├── static/            # Built frontend output + legacy assets
├── temp/              # Runtime data (sqlite, tasks, downloads) — in .gitignore
├── scripts/           # Build, sign, package (macOS / Windows)
├── pyinstaller/       # PyInstaller spec for desktop packaging
├── start.py           # Desktop launcher (pywebview + uvicorn)
├── requirements.txt   # Python deps
├── package.json       # Root: dev scripts (dev, stop, build, lint)
├── DESIGN.md          # Full design system reference
├── PRODUCT.md         # Product identity + brand
└── docs/              # Design docs (e.g., bot-integration-design.md)
```

## Development

### Install & Run

```bash
# Backend (from project root)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && pnpm install

# Dev mode (both servers, via concurrently)
pnpm dev
# → API at :8000, Web at :5173 (proxies /api to :8000)

# Quick stop
pnpm stop
```

### Important: Working Directory

The backend runs from inside `backend/` (set by `start.py` via `os.chdir` and by the root `pnpm dev` script). **Always use flat imports in backend modules:**

```python
# Correct (runs from backend/)
from services import summarizer
from task_store import tasks, broadcast_update
from pipeline import process_video_task

# Wrong — no package-relative imports
from .services import summarizer  # ❌
```

### Route Verification

```bash
cd backend && python -c "import main; print(len(main.app.routes))"
# Expect: 27
```

### Key Conventions

1. **Backend is stateless** — user config (API key, base URL, model) comes from frontend via request bodies, not `.env` or server env vars.
2. **Task pipeline is single-file per stage** — each pipeline step (transcribe, summarize, translate, sanitize) is a separate module.
3. **SSE for real-time progress** — `task_store.py` tracks stage/status and broadcasts to connected SSE clients per task ID.
4. **SQLite via `asyncio.to_thread`** — no async ORM; `db.py` wraps `sqlite3` with thread pool calls.
5. **Cancellation is cooperative** — `cancellation.py` exposes `_cancel_events` dict keyed by task ID; pipeline stages check `cancelled()` periodically and raise `TaskCancelledException`.
6. **Frontend i18n** — dictionaries in `frontend/src/i18n/dictionaries.ts`; React context in `I18nContext.tsx`. Four languages: en, zh, ja, ko.
7. **Design tokens** — oklch-based CSS custom properties in `index.css`; dark-first, light-supported. Accent is amber-copper (`oklch(58% 0.13 60)`). Max-width: 720px for prose.

### Frontend Stack

| Layer | Choice |
|-------|--------|
| Framework | React 19 |
| Language | TypeScript 6.0 |
| Build | Vite 8 |
| Styling | Tailwind CSS v3.4 + oklch tokens |
| Router | react-router-dom v7 (HashRouter) |
| UI primitives | Radix UI (tabs, select, dialog, switch, collapsible, tooltip, popover) |
| Icons | Lucide React |
| Markdown | marked |
| Package manager | pnpm |

### Backend Stack

| Layer | Choice |
|-------|--------|
| Framework | FastAPI |
| Server | uvicorn (standard extras) |
| ASR | Faster-Whisper (CTranslate2) |
| Video | yt-dlp |
| LLM | openai SDK (OpenAI-compatible API) |
| Export | python-docx, fpdf2, markdown, reportlab |
| RSS | feedparser (via rss_reader.py) |
| Desktop | pywebview |

## Code Patterns

### Adding a New API Route

1. Create or extend a module in `backend/routers/`
2. Import and `app.include_router()` in `backend/main.py`
3. Use `from services import summarizer, ...` for dependencies
4. Use `from task_store import tasks, broadcast_update, ...` for state
5. Log with `logger = logging.getLogger(__name__)` (configured via `logging_config.py`)

### Adding a New Pipeline Stage

1. Add the stage function to the relevant module (`summarizer.py`, `translator.py`, etc.)
2. Wire it into `pipeline.py`'s `run_post_extract_pipeline` or `process_video_task`/`process_upload_task`
3. Update `task_store.py`'s progress tracking if it's a user-visible stage
4. Check `cancellation.cancelled(task_id)` in long-running loops

### Adding a New Platform Extractor

1. Subclass `base.py` in `backend/platforms/`
2. Implement abstract methods for metadata extraction / subtitle retrieval
3. Register in the platform dispatch in `pipeline.py`

### Frontend: Adding a New Page

1. Create component in `frontend/src/components/`
2. Add route in `App.tsx`
3. Add tab entry in `Navbar.tsx`
4. Add i18n keys in `dictionaries.ts` (all 4 languages)

### Frontend: API Calls

API calls use plain `fetch` with the base URL from `import.meta.env.BASE_URL` (in production `/static/`, in dev `/`). Responses follow FastAPI's error schema: `{ detail: string }`.

## Design Philosophy

Read `DESIGN.md` for the full visual system. Key points:

- **Restrained, tool-like UI** — no gradients, no "magic ✨", no hero sections
- **Dark-first** with a warm neutral palette (amber-copper accent)
- **Content-first** — the transcript/summary dominates the viewport
- **Speed-first perception** — progress shows immediately, summaries stream before transcripts finish
- **Progressive disclosure** — settings collapsed, advanced options behind toggles
- **Single-column**, 720px max-width, centered

## Testing

No formal test suite exists yet. Smoke tests:
```bash
# Backend import check
cd backend && python -c "import main; print('OK')"

# Frontend typecheck + lint
cd frontend && pnpm build   # includes tsc -b

# E2E: dev server + manual browser test
pnpm dev
```

## Docker

```bash
docker-compose up -d     # port 8000, 2G memory limit
```

The Dockerfile uses `python:3.12-slim-bookworm`, installs FFmpeg, runs `pip install -r requirements.txt` with upper-bound deps, copies the project, and starts `python3 backend/main.py`.

## Desktop Packaging (macOS/Windows)

- `start.py` — pywebview + uvicorn in a thread; opens a native window pointing to localhost
- `pyinstaller/ai_transcriber.spec` — PyInstaller config
- `scripts/build_macos.sh` — macOS .app build
- `scripts/sign_and_package.sh` — Code signing + DMG (needs Apple Developer cert)
- `scripts/build_windows.ps1` — Windows .exe build
- `install.sh` / `install.ps1` / `install.bat` — End-user installers

## Environment

- Python 3.8+ (3.12 recommended)
- FFmpeg (required system-level)
- Node.js 18+ (frontend build only)
- No `.env` needed — all user config via UI

## Git Hygiene

- `static/` is in `.gitignore` (CI build artifact)
- `temp/` is in `.gitignore` (runtime data)
- `.env` is in `.gitignore`
- Never commit audio/video files, model cache, or FFmpeg binaries
