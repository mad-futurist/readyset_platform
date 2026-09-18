# ReadySet web application

This directory is the frontend deployable unit. It is a Next.js application and does not install or run the Python API package. Browser requests to `/api/*` are proxied by Next.js to the backend configured by `API_INTERNAL_URL`.

The web application consumes TypeScript API declarations from the separate `@readyset/api-client` workspace in `packages/api-client`. Run npm commands from the repository root so npm can resolve that workspace dependency.

## Prerequisites

- Node.js 22 or newer
- npm 10 or newer (included with current Node.js releases)
- A running ReadySet API on `http://localhost:8000`; follow [`../api/README.md`](../api/README.md) to start it

Docker is optional for the frontend itself. It is useful for starting the API's PostgreSQL and MinIO dependencies.

## Prepare the frontend

From the repository root:

1. Install the root workspaces. Use `npm ci` for a clean, reproducible install from `package-lock.json`:

   ```powershell
   npm ci
   ```

2. Normally no frontend environment file is required. The default API origin is `http://localhost:8000`. If the API runs elsewhere, create `apps/web/.env.local` with:

   ```dotenv
   API_INTERNAL_URL=http://localhost:8000
   ```

   `API_INTERNAL_URL` is read by Next.js and is not exposed as a browser-side `NEXT_PUBLIC_*` variable. During development it is read when the dev server starts; for a production image it must be supplied as a Docker build argument because Next.js serializes rewrites during the build.

3. If the backend OpenAPI contract changed, export the real FastAPI schema and regenerate the shared client declarations before starting the frontend:

   ```powershell
   .\apps\api\.venv\Scripts\python apps/api/scripts/export_openapi.py
   npm run generate:api-client
   ```

   Both `apps/api/openapi.json` and `packages/api-client/src/schema.d.ts` are checked in. CI rejects either artifact if it is stale.

## Launch locally

1. Start the backend first and confirm `http://localhost:8000/readyz` returns a successful response.
2. In a second terminal, from the repository root, start the frontend development server:

   ```powershell
   npm run dev --workspace @readyset/web
   ```

3. Open `http://localhost:3000`.
4. Stop the server with `Ctrl+C`.

The frontend sends same-origin requests to `/api/*`; Next.js forwards them to `API_INTERNAL_URL`. The browser therefore does not need to know the backend container hostname.

## Validate the frontend

Run these commands from the repository root:

```powershell
npm run lint --workspace @readyset/web
npm run typecheck --workspace @readyset/web
npm run test --workspace @readyset/web
npm run build --workspace @readyset/web
```

The production build is written to `apps/web/.next/`, which is intentionally ignored by `apps/web/.gitignore`.

## Run only the frontend in Docker

The frontend image needs the repository root as its build context because it consumes `packages/api-client`:

```powershell
docker build -f apps/web/Dockerfile --build-arg API_INTERNAL_URL=http://host.docker.internal:8000 -t readyset-web .
docker run --rm -p 3000:3000 readyset-web
```

On Linux, add `--add-host=host.docker.internal:host-gateway` to `docker run` if the API runs directly on the host. Rebuild the image when the production API origin changes. For the supported full-stack Docker workflow, use `docker compose up --build` from the repository root; Compose supplies `http://api:8000` at build time.

## Frontend packaging boundary

- Runtime code: `apps/web/src`
- Static files: `apps/web/public`
- Frontend manifest: `apps/web/package.json`
- Shared generated contract: `packages/api-client`
- Generated/local files: `apps/web/node_modules`, `apps/web/.next`, coverage, TypeScript build metadata, and local environment files
- Backend source, Python environments, database migrations, and server secrets are not part of the frontend package
