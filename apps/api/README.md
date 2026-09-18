# ReadySet API application

This directory is the backend deployable unit. It contains the FastAPI application, SQLAlchemy models, Alembic migrations, and backend tests. It is packaged independently by `apps/api/pyproject.toml` and does not depend on the Next.js source or Node modules.

## Prerequisites

- Python 3.12 or newer
- Docker Desktop or Docker Engine with Compose, used locally for PostgreSQL and MinIO
- PowerShell for the commands below; equivalent activation commands are noted for macOS/Linux

Node.js is not required to run the API. It is needed only when regenerating the repository's TypeScript API client.

## Prepare the backend

Run these steps from the repository root.

1. Create an isolated virtual environment for the backend:

   ```powershell
   python -m venv apps/api/.venv
   ```

2. Upgrade packaging tools and install the API with its development dependencies:

   ```powershell
   .\apps\api\.venv\Scripts\python -m pip install --upgrade pip
   .\apps\api\.venv\Scripts\python -m pip install -e ".\apps\api[dev]"
   ```

   On macOS/Linux, the interpreter path is `./apps/api/.venv/bin/python`.

3. Copy the example configuration into the API directory, where Pydantic loads it during native development:

   ```powershell
   Copy-Item .env.example apps/api/.env
   ```

   The checked-in defaults work with the Compose services. Keep secrets in `apps/api/.env`; this file is ignored. If using Google sign-in, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and configure the provider callback as `http://localhost:3000/api/v1/auth/google/callback`. The browser always reaches that path through the Next.js same-origin proxy.

4. Start only the backend infrastructure from the repository root:

   ```powershell
   docker compose up -d postgres minio
   docker compose ps
   ```

   PostgreSQL listens on `localhost:5432`. MinIO listens on `localhost:9000`, with its console on `http://localhost:9001`.

5. Apply database migrations from the API directory:

   ```powershell
   Push-Location apps/api
   .\.venv\Scripts\alembic upgrade head
   Pop-Location
   ```

   On macOS/Linux, run `./.venv/bin/alembic upgrade head` from `apps/api`.

## Launch locally

1. Confirm PostgreSQL and MinIO are running with `docker compose ps`.
2. Start FastAPI from the API directory:

   ```powershell
   Push-Location apps/api
   .\.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

3. Verify the service:

   - Health check: `http://localhost:8000/healthz`
   - OpenAPI UI: `http://localhost:8000/docs`
   - OpenAPI document: `http://localhost:8000/openapi.json`

4. Stop Uvicorn with `Ctrl+C`, then return to the repository root:

   ```powershell
   Pop-Location
   ```

5. When finished with the supporting services, stop them without deleting their data:

   ```powershell
   docker compose stop postgres minio
   ```

   Use `docker compose down` to remove the containers and network. Add `--volumes` only when you intentionally want to delete the local PostgreSQL and MinIO data.

## Validate the backend

With PostgreSQL and MinIO running, execute from the repository root:

```powershell
Push-Location apps/api
.\.venv\Scripts\ruff check app tests scripts
.\.venv\Scripts\mypy app
.\.venv\Scripts\pytest --cov=app
.\.venv\Scripts\alembic check
Pop-Location
```

PostgreSQL-only integrity and locking tests run when `RUN_POSTGRES_TESTS=1`; CI enables that flag against its PostgreSQL service. SQLite remains the fast local unit-test backend, not a production target.

Export the source-of-truth OpenAPI snapshot with `python apps/api/scripts/export_openapi.py`, then run `npm run generate:api-client` from the repository root. Commit both generated artifacts together.

To confirm that the backend is independently packageable:

```powershell
.\apps\api\.venv\Scripts\python -m pip wheel --no-deps --wheel-dir apps/api/dist apps/api
```

The wheel output in `apps/api/dist/` is intentionally ignored by `apps/api/.gitignore`.

## Run only the API in Docker

The backend image has an app-local build context and needs no frontend files:

```powershell
docker build -t readyset-api apps/api
```

Running the image manually also requires reachable PostgreSQL and MinIO services plus the corresponding environment variables. The supported local container workflow is therefore:

```powershell
docker compose up --build api postgres minio
```

The container applies Alembic migrations before starting Uvicorn.

## Backend packaging boundary

- Python package: `apps/api/app`
- Migration configuration: `apps/api/alembic.ini` and `apps/api/alembic`
- Package manifest: `apps/api/pyproject.toml`
- API contract snapshot: `apps/api/openapi.json`
- Generated/local files: `apps/api/.venv`, Python caches, coverage data, test caches, wheels, and local environment files
- Frontend source, Node modules, and Next.js build output are not part of the backend package
