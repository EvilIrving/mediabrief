# Plans

Design and planning documents for AI Transcriber.

| Document | Description |
|----------|-------------|
| [`queue-sse-convergence.md`](queue-sse-convergence.md) | Converge queue SSE + task SSE into a single queue stream with detail REST |
| [`db-split.md`](db-split.md) | Split `backend/db.py` (~996 lines) into `db_core.py` / `db_tasks.py` / `db_queue.py` / `db_rss.py` |
