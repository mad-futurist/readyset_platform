# ReadySet worker

M2 runs version-scoped ingestion using the installed backend domain package and its committed dependency lock. No HTTP server is exposed. PostgreSQL claims use SKIP LOCKED, renewable attempt leases and fenced transactional outputs; object downloads spool before extraction/chunking/batched embedding.

Build from the repository root: `docker build -f apps/worker/Dockerfile -t readyset-worker .`.

Source setup: `uv sync --project apps/api --frozen`; configure DATABASE_URL, storage and explicit AI provider settings, then `uv run --project apps/api --frozen python apps/worker/run.py`. `--once` processes at most one available job. `--health` checks the private heartbeat file; container HEALTHCHECK uses it.

`docker compose up --build` runs the migration release job, API, web, PostgreSQL/pgvector, MinIO, Redis and worker. Compose explicitly selects fake embeddings/chat; no paid provider is used. Fake chat is an extractive local preview, not production QA. Hardened AI must use production providers/credentials and an approved data-handling policy.

See [document intelligence](../../docs/architecture/DOCUMENT_INTELLIGENCE.md) and ADRs 009–012. Graceful shutdown stops new claims and finishes the active attempt; lease expiry is the forced-crash backstop. Use runtime CPU/memory limits, supervise heartbeat/queue age and alert on sanitized failure categories.
