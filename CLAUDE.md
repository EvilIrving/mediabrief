# AGENTS.md — MediaBrief

This file is operating law for agents working in this repo. `CLAUDE.md` is the same file; keep them byte-identical.

It tells you how to move in this codebase without breaking it. It is not a product spec, not a file inventory, and not the Harness guide. For those:

- Product identity → `PRODUCT.md` / `DESIGN.md`
- In-app Harness (loop, Tool catalog, how to add a Tool or scene) → `AINative.md` + `AINativePlan.md`
- Shipping / signing / download page → `ProductizationPlan.md`
- Cross-session decisions → `PROJECT_MEMORY.md`

---

## Project

MediaBrief turns video/audio/podcast links (30+ platforms via yt-dlp) and local files into transcripts and AI summaries. Subtitles first, Whisper fallback, then LLM cleanup. RSS for recurring sources. UI and summaries in EN/ZH/JA/KO.

**Shipping target is macOS on Apple Silicon.** Windows is out of scope. Docker, Compose, and `install.sh` are not this product line; that lives on `self-hosted`.

## Shape

```
frontend/   React 19 + TS + Vite + Tailwind v3.4 → builds to ../static/
            Dev: Vite :5173, proxies /api → :8000
backend/   Python 3.12 + FastAPI + asyncio
            HTTP in routers/ · orchestration in pipeline.py · work in stage modules
            Runtime cwd is backend/ → always use flat imports
```

```
Input (URL / upload / RSS)
  → yt-dlp subtitles (fast path)
  → if both subtitles and audio fail → media-recovery Harness
  → else Whisper when there are no subs
  → LLM sanitize ∥ LLM summary
  → optional translation
  → export
```

Download Detect is a separate path: formats go through `present_download_list` (`download_list_scene.py` / `format_curator.py`), not a side `chat.completions`.

## Layout (only what you need to land)

```
backend/           runtime working dir; flat imports
  routers/          HTTP only
  platforms/        yt-dlp adapters; auto-discovered
  prompts/          layered LLM prompts (roles + task layers)
  tests/            pytest, run from backend/
frontend/src/
  features/<name>/  pages (TranscribePage, DownloadPage, …)
  components/       shared UI
  i18n/             dictionaries.ts — all user-visible strings, 4 languages
static/             build output (gitignored)
temp/               runtime data (gitignored)
start.py            desktop launcher
AINative.md         how the Harness actually runs
AINativePlan.md     how to add a Tool or scene
```

## Run

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd frontend && pnpm install

pnpm dev     # API :8000, web :5173
pnpm stop
pnpm test    # backend pytest + frontend vitest
pnpm test:api
pnpm test:web
```

Backend cwd is `backend/` (`start.py` and `pnpm dev` both chdir there):

```python
from services import summarizer          # correct
from .services import summarizer         # wrong
```

## Conventions that prevent damage

1. **HTTP / orchestration / work stay apart.** `routers/` never does the work. Stage modules never import a router. New processors go through `services.py`; task state through `task_store.py`.
2. **Config is not `.env`.** Transcribe/summary still take API key / base URL / model from the request when the client sends them. App settings (LLM, bots, TTS, transcription prefs) persist in SQLite via `settings_store.py`. Recovery model comes from `release_config.py`. Do not invent a new env-file config path.
3. **Cancellation is `CancelledByUser`.** `cancellation.current()` is the token; call `token.check()` in long loops. Raise `CancelledByUser`. There is no `TaskCancelledException`. Wrap blocking LLM/media calls with timeouts (`_llm_call`, `_run_media_proc`).
4. **FFmpeg/FFprobe by absolute path.** `start.py` exports `AIT_FFMPEG` / `AIT_FFPROBE` / `AIT_FFMPEG_LOCATION`. `video_processor.py` passes `ffmpeg_location` to yt-dlp and runs binaries through `_run_media_proc`. Never call `ffmpeg`/`ffprobe` by bare name.
5. **yt-dlp is not version-frozen in packaged builds.** `yt_dlp_updater.py` keeps a writable copy ahead of the bundle and refreshes weekly from PyPI stable.
6. **Whisper.** Default is `large-v3-turbo` (downloads in the background on first launch). `base` is the embedded offline fallback (`BUILTIN_MODEL`). Pipeline calls `get_transcriber()` per task, not the frozen `transcriber` singleton. `wait_for_default_model` stays a host latch; do not register it as a Harness Tool.
7. **User-visible strings live in `i18n/dictionaries.ts`**, all four languages. No hardcoded display copy in components. Toasts go through `useAutoDismissError` + `<Toast>` / `<ErrorBanner>`.
8. **Comments explain why**, in the repo's short Chinese style. Do not narrate the code.
9. **Layered prompts** live in `backend/prompts/`: `Role` (identity + directives + output_contract → system) → `Prompt` (Role + task layers) → `render(**vars)` → OpenAI `messages`. Roles in `prompts/roles.py`; stage modules only bind a role to a task. Debug: `AIT_PROMPT_DEBUG=1` / `AIT_PROMPT_DUMP_DIR=<dir>`. See the header of `backend/prompts/__init__.py`.
10. **Harness work is not a new framework.** Same Tool has two entries: host calls `execute` when the rule is enough; the model may choose the same `execute`. Closed-set args, sanitized observations, no chat page, no plugin loader, no `harness/` package. Read `AINative.md` before changing the loop; follow `AINativePlan.md` to add a Tool or scene.

## How to add things

**API route** — module under `backend/routers/` → `app.include_router()` in `main.py` → depend on `services` / `task_store` → `logging.getLogger(__name__)`.

**Pipeline stage** — function in the owning module → wire into `run_post_extract_pipeline` / `process_video_task` / `process_upload_task` → update progress in `task_store.py` if the user can see it → `token.check()` in long loops.

**Platform adapter** — subclass `platforms/_base.py` as a new file in `platforms/`. `platforms/__init__.py` auto-discovers it. Do not register it in `pipeline.py`. Existing adapters: youtube, bilibili, douyin, generic.

**Harness Tool or scene** — `AINativePlan.md`. Do not invent a second LLM client path for something that already has `execute`.

**Frontend page** — `frontend/src/features/<name>/<Name>Page.tsx` → route in `App.tsx` → tab in `Navbar.tsx` → i18n keys in all four languages. Shared pieces stay under `components/`, `lib/`, `hooks/`, `context/`.

**Frontend API** — `fetch` with `import.meta.env.BASE_URL` (`/static/` in production, `/` in dev). Errors are `{ detail: string }`.

## Frontend / backend stack

| Frontend | | Backend | |
|---|---|---|---|
| React 19 | Vite 8 | FastAPI | uvicorn |
| TypeScript 6.0 | Tailwind v3.4 + oklch | mlx-whisper | yt-dlp |
| react-router HashRouter | Radix + Lucide | openai SDK | pywebview |
| pnpm | marked | python-docx / fpdf2 / reportlab | feedparser |

Design: restrained, dark-first, amber-copper accent, 720px prose column. Read `DESIGN.md`. No gradients, no "magic ✨", no hero.

## Testing

```bash
pnpm test
# backend: tests in backend/tests/, pytest.ini, asyncio_mode = auto
# frontend: vitest + jsdom, co-located *.test.ts(x)
```

Backend tests use flat imports. Do not hit the network for LLM: test parsers and tagged-output helpers. Frontend: mock `fetch` at `lib/api.ts`. i18n tests require key parity across en/zh/ja/ko.

`cd backend && python -c "import main"` is only a smoke import, not the test suite.

## Desktop packaging

- `start.py` — pywebview + uvicorn
- `pyinstaller/ai_transcriber.spec`
- `scripts/build_macos.sh` / `sign_and_package.sh` / `release_macos.sh`

Do not add Docker or Windows installers on `main`.

## Environment & git

- Python 3.12, FFmpeg, Node 18+ (frontend build)
- No `.env` required
- Do not commit `static/`, `temp/`, `.env`, media files, model cache, or FFmpeg binaries
