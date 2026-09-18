# ReadySet

ReadySet M1 is a production-oriented B2B SaaS foundation for authenticated organizations, people/teams, and secure versioned enterprise documents. It is a modular monolith with independently deployable FastAPI and Next.js applications.

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
2. Run `docker compose up --build`.
3. Open `http://localhost:3000`; API documentation is at `http://localhost:8000/docs` in development.

Google's OAuth client must allow the public same-origin callback `http://localhost:3000/api/v1/auth/google/callback`. In development, email is captured in memory and raw one-time tokens can be returned by the API. Staging and production refuse to start with those development behaviors; SMTP and the other hardened settings in `.env.example` must be configured.

## Native development

```powershell
python -m venv apps/api/.venv
.\apps\api\.venv\Scripts\python -m pip install -e ".\apps\api[dev]"
docker compose up -d postgres minio
Push-Location apps\api
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\uvicorn app.main:app --reload
Pop-Location
npm install
npm run dev --workspace @readyset/web
```

## Checks

```powershell
Push-Location apps\api
.\.venv\Scripts\ruff check app tests scripts
.\.venv\Scripts\mypy app
.\.venv\Scripts\pytest --cov=app
.\.venv\Scripts\alembic check
Pop-Location
npm run lint
npm run typecheck
npm test
npm run build
```

Regenerate the API contract cross-platform with `python apps/api/scripts/export_openapi.py` followed by `npm run generate:api-client`, or use `scripts/export-openapi.ps1` on Windows. CI exports from the real FastAPI app and rejects drift in both generated files. Architecture starts at [ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md); security invariants are in [SECURITY_INVARIANTS.md](docs/architecture/SECURITY_INVARIANTS.md).
