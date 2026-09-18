# ReadySet

ReadySet M1.1 is a production-focused B2B SaaS foundation for authenticated organizations, people/teams, and secure versioned enterprise documents. Deployment still depends on the operational requirements in the production runbook; this README does not claim a provider environment has been certified.

The legacy `demo/` and external `references/` trees are read-only research inputs. They are ignored by the root `.gitignore`, excluded from builds, and are not runtime dependencies. The `docs/` tree remains trackable.

## Repository

```text
apps/api       FastAPI, SQLAlchemy 2, Alembic, PostgreSQL
    apps/web       Next.js, React, TanStack Query
apps/worker    M2 ingestion boundary (documentation only in M1)
packages/api-client  generated OpenAPI TypeScript declarations
docs           architecture, ADRs, and research
infra          deployment notes
scripts        developer utilities
```

The frontend and backend have separate manifests, Dockerfiles, ignore rules, and local-development guides:

- [Backend preparation and local launch](apps/api/README.md)
- [Frontend preparation and local launch](apps/web/README.md)

## Start locally

1. Copy `.env.example` to `.env` and optionally add Google OAuth credentials.
2. Run `docker compose up --build`. Compose runs a single migration service before the API and provides PostgreSQL, MinIO, and Redis.
3. Open `http://localhost:3000`; API documentation is at `http://localhost:8000/docs` in development.

Google's OAuth client must allow the public same-origin callback `http://localhost:3000/api/v1/auth/google/callback`. In development, email is captured in memory and raw one-time tokens can be returned by the API. Staging and production refuse those behaviors and require SMTP, Redis, ClamAV, secure origins/cookies, and a pre-created encrypted bucket.

## Native development

```powershell
python -m pip install uv
uv sync --project apps/api --frozen --extra dev
docker compose up -d postgres minio redis
Push-Location apps\api
uv run --frozen alembic upgrade head
uv run --frozen uvicorn app.main:app --reload
Pop-Location
npm install
npm run dev --workspace @readyset/web
```

## Checks

```powershell
Push-Location apps\api
uv run --frozen ruff check app tests scripts
uv run --frozen mypy app
uv run --frozen pytest --cov=app
uv run --frozen alembic check
Pop-Location
npm run lint
npm run typecheck
npm test
npm run build
```

Regenerate the API contract with `uv run --project apps/api --frozen python apps/api/scripts/export_openapi.py` followed by `npm run generate:api-client`. CI exports from the real app and rejects drift. Start with [architecture](docs/architecture/ARCHITECTURE.md), [implementation status](docs/architecture/IMPLEMENTATION_STATUS.md), [security invariants](docs/architecture/SECURITY_INVARIANTS.md), and [production deployment](docs/operations/PRODUCTION_DEPLOYMENT.md).
