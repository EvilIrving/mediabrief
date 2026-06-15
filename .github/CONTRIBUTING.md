# Contributing to AI Transcriber

Thanks for contributing! This guide covers setup, tooling, and conventions.

## Prerequisites

| Dependency | Minimum | Check |
|-----------|---------|-------|
| Python | 3.12 | `python3 --version` |
| Node.js | 18+ | `node --version` |
| pnpm | latest | `pnpm --version` |
| FFmpeg | any | `ffmpeg -version` |

macOS: `brew install ffmpeg pnpm`  
Linux: `apt install ffmpeg` + `npm install -g pnpm`

## Getting Started

```bash
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber

# Backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && pnpm install
```

## Development Scripts

| Script | Command | What it does |
|--------|---------|-------------|
| Dev (both) | `pnpm dev` | API at :8000 + Web at :5173, proxies `/api` to backend |
| API only | `pnpm serve:api` | Backend only, port 8000 |
| Web only | `pnpm dev:web` | Frontend only, port 5173 |
| Stop all | `pnpm stop` | Kill ports 8000/5173 + uvicorn + desktop launcher |
| Build | `pnpm build` | Install deps + tsc + Vite production build |
| Lint | `pnpm lint` | Frontend ESLint + typecheck |
| Test | `pnpm test:api` | Backend pytest |

## Architecture

```
frontend/ (React 19 + Vite + Tailwind v4)  →  built to ../static/
backend/  (Python 3.12 + FastAPI + asyncio)
```

Key principles:
- **Backend is stateless** — user config (API keys, models) comes from frontend via request bodies, never `.env` or server env vars.
- **Flat imports** — backend runs from inside `backend/`, all root modules use `from services import X` not `from .services`.
- **Three-layer separation** — `routers/` (HTTP) → `pipeline.py` (orchestration) → `services/` (work). No reverse dependencies.
- **SSE for progress** — task state broadcasts via `task_store.py` to connected SSE clients.
- **SQLite via `asyncio.to_thread`** — no async ORM, `db.py` wraps `sqlite3`.
- **Cooperative cancellation** — long-running ops check `cancellation.cancelled(task_id)`.
- **Frontend i18n** — all UI strings in `dictionaries.ts` across en/zh/ja/ko.

Full details in [`AGENTS.md`](../AGENTS.md) and [`DESIGN.md`](../DESIGN.md).

## Code Style

### Backend (Python)

```python
# ✓ Correct
from services import summarizer                          # flat import
from task_store import tasks, broadcast_update
from db import get_task as _db_get_task                  # _ prefix for "internal but borrowed"
from cancellation import cancelled

effective_key = (api_key or "").strip()                  # normalize inputs early

async def process_item(task_id: str):                    # verb-first snake_case
    for segment in segments:
        if cancelled(task_id):                           # cancel check in loops
            raise TaskCancelledException(task_id)
        ...
```

- One concern per file. Flat modules at `backend/` root.
- Verb-first `snake_case` functions. Full words over abbreviations.
- `_` prefix for module-private helpers.
- Normalize inputs at boundary, fail loud on config errors.
- Comment the **why**, not the what.

### Frontend (TypeScript)

```tsx
// ✓ Correct
const { t } = useI18n()                                  // i18n for all display strings
const { error, setError, dismissError } = useAutoDismissError()

return (
  <>
    {error && <ErrorBanner message={error} onDismiss={dismissError} />}
    <button>{t('start_transcription')}</button>
  </>
)
```

- `PascalCase` components, `camelCase` functions, `useXxx` hooks.
- All UI copy in `i18n/dictionaries.ts` across all 4 languages.
- Transient errors via `useAutoDismissError` + `<Toast>` / `<ErrorBanner>`.
- API calls use `fetch` with `import.meta.env.BASE_URL`.
- Tailwind CSS utility classes. Only custom CSS for design tokens in `index.css`.
- Pages in `components/`, hooks in `hooks/`, utilities in `lib/`.

## Testing

```bash
# Backend import check
cd backend && python -c "import main; print(len(main.app.routes))"

# Frontend typecheck + lint
cd frontend && pnpm lint && pnpm build

# Full smoke test (requires dev running)
pnpm dev
```

CI runs these automatically on PRs: frontend build, backend E2E smoke, and CodeRabbit review.

## Pull Request Process

1. Create a feature branch: `git checkout -b feature/description`
2. Follow existing code patterns and conventions above
3. Run smoke tests locally
4. Open a PR against `main` with a clear description
5. Link related issues in the PR body

## Project Structure

```
ai-transcriber/
├── backend/           # Python FastAPI backend
│   ├── main.py        # App assembly, CORS, static mount
│   ├── routers/       # HTTP route handlers (core, transcribe, downloads, rss, export, queue, bots)
│   ├── platforms/     # yt-dlp extractors per platform (youtube, bilibili, generic)
│   ├── feeds/         # RSS feed adapters (youtube, generic)
│   ├── bots/          # Telegram / Slack bot integrations
│   ├── pipeline.py    # Task orchestration (post-extract pipeline)
│   ├── services.py    # Processor singletons
│   ├── task_store.py  # Task state, SSE broadcast
│   ├── db.py          # SQLite persistence (asyncio.to_thread)
│   └── ...
├── frontend/          # React SPA (Vite + TypeScript + Tailwind v4)
│   └── src/
│       ├── App.tsx              # Root, theme provider, router
│       ├── components/          # Shared components
│       ├── features/            # Page components by feature
│       ├── i18n/                # dictionaries.ts + I18nContext
│       └── hooks/               # useAutoDismissError
├── static/            # Built frontend output (CI artifact, gitignored)
├── temp/              # Runtime data (gitignored)
├── scripts/           # Build, sign, package (macOS, Windows)
├── plans/             # Design & planning documents
└── .github/
    ├── workflows/     # CI: build, changelog, e2e
    └── review-bot-rules/  # CodeRabbit review rules
```

## Questions?

Open a [Discussion](https://github.com/EvilIrving/ai-transcriber/discussions) or join the conversation on [GitHub Issues](https://github.com/EvilIrving/ai-transcriber/issues).
