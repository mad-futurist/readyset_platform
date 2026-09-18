# ReadySet API application

This directory is the backend deployable unit. It contains the FastAPI application, SQLAlchemy models, Alembic migrations, and backend tests. It is packaged independently by `apps/api/pyproject.toml` and does not depend on the Next.js source or Node modules.

## Prerequisites

- Python 3.12 or newer
- Docker Desktop or Docker Engine with Compose, used locally for PostgreSQL, MinIO, and Redis
- `uv` for frozen dependency synchronization from `uv.lock`
- PowerShell for the commands below; equivalent activation commands are noted for macOS/Linux

Node.js is not required to run the API. It is needed only when regenerating the repository's TypeScript API client.

## Prepare the backend

Run these steps from the repository root.

1. Synchronize the committed lock with development tools:

   ```powershell
   uv sync --project apps/api --frozen --extra dev
   ```

2. Copy the example configuration into the API directory, where Pydantic loads it during native development:

   ```powershell
   Copy-Item .env.example apps/api/.env
   ```

   The checked-in defaults work with the Compose services. Keep secrets in `apps/api/.env`; this file is ignored. If using Google sign-in, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and configure the provider callback as `http://localhost:3000/api/v1/auth/google/callback`. The browser always reaches that path through the Next.js same-origin proxy.

3. Start only the backend infrastructure from the repository root:

   ```powershell
   docker compose up -d postgres minio redis
   docker compose ps
   ```

   PostgreSQL listens on `localhost:5432`, Redis on `localhost:6379`, and MinIO on `localhost:9000`, with its console on `http://localhost:9001`.

4. Apply database migrations from the API directory:

   ```powershell
   Push-Location apps/api
   uv run --frozen alembic upgrade head
   Pop-Location
   ```

## Launch locally

1. Confirm PostgreSQL, MinIO, and Redis are running with `docker compose ps`.
2. Start FastAPI from the API directory:

   ```powershell
   Push-Location apps/api
   uv run --frozen uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

3. Verify the service:

   - Liveness: `http://localhost:8000/livez`
   - Dependency readiness: `http://localhost:8000/readyz`
   - Compatibility alias: `http://localhost:8000/healthz`
   - OpenAPI UI: `http://localhost:8000/docs`
   - OpenAPI document: `http://localhost:8000/openapi.json`

4. Stop Uvicorn with `Ctrl+C`, then return to the repository root:

   ```powershell
   Pop-Location
   ```

5. When finished with the supporting services, stop them without deleting their data:

   ```powershell
   docker compose stop postgres minio redis
   ```

   Use `docker compose down` to remove the containers and network. Add `--volumes` only when you intentionally want to delete the local PostgreSQL and MinIO data.

## Test email locally with Mailpit

The default Compose configuration uses the in-memory `capture` backend. To send registration, verification, password-reset, and invitation messages through a local SMTP server, enable the optional Mailpit profile from the repository root:

```powershell
$env:EMAIL_BACKEND = "smtp"
$env:SMTP_HOST = "mailpit"
$env:SMTP_PORT = "1025"
$env:SMTP_STARTTLS = "false"
docker compose --profile smtp up --build -d
```

Open the Mailpit inbox at `http://localhost:8025`, then register a new address through the application. Mailpit accepts local messages without SMTP credentials and displays the verification link. These values are for local development only; staging and production require authenticated SMTP with STARTTLS.

To return to the default capture backend in the current PowerShell session:

```powershell
Remove-Item Env:EMAIL_BACKEND,Env:SMTP_HOST,Env:SMTP_PORT,Env:SMTP_STARTTLS
docker compose up --build -d
```

## Validate the backend

With PostgreSQL, MinIO, and Redis running, execute from the repository root:

```powershell
Push-Location apps/api
uv run --frozen ruff check app tests scripts
uv run --frozen mypy app
uv run --frozen pytest --cov=app
uv run --frozen alembic check
Pop-Location
```

PostgreSQL-only integrity and locking tests run when `RUN_POSTGRES_TESTS=1`; CI enables that flag against its PostgreSQL service. SQLite remains the fast local unit-test backend, not a production target.

Export the source-of-truth OpenAPI snapshot with `uv run --project apps/api --frozen python apps/api/scripts/export_openapi.py`, then run `npm run generate:api-client` from the repository root. Commit both generated artifacts together.

To confirm that the backend is independently packageable:

```powershell
uv build --project apps/api --wheel --out-dir apps/api/dist
```

The wheel output in `apps/api/dist/` is intentionally ignored by `apps/api/.gitignore`.

## Run only the API in Docker

The backend image has an app-local build context and needs no frontend files:

```powershell
docker build -t readyset-api apps/api
```

Running the image manually also requires reachable PostgreSQL, MinIO, and Redis services plus the corresponding environment variables. The supported local container workflow is therefore:

```powershell
docker compose up --build api postgres minio redis
```

The container starts only Uvicorn as a non-root user. Run `alembic upgrade head` once as a separate release/migration job before rolling out API replicas; Compose provides the `migrate` service as the local example. Dependencies are installed from the committed `uv.lock` with `uv sync --frozen`.

## Backend packaging boundary

- Python package: `apps/api/app`
- Migration configuration: `apps/api/alembic.ini` and `apps/api/alembic`
- Package manifest: `apps/api/pyproject.toml`
- API contract snapshot: `apps/api/openapi.json`
- Generated/local files: `apps/api/.venv`, Python caches, coverage data, test caches, wheels, and local environment files
- Frontend source, Node modules, and Next.js build output are not part of the backend package
