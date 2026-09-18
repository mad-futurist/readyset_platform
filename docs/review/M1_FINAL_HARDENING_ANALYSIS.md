# M1.1 final hardening analysis

Date: 2026-09-18  
Baseline: `967070c8c36f3f1fe04c42615690ea2df877e3d6`

## Method and verified baseline

This review inspected the current tracked source, migrations, tests, CI, container definitions, dependency manifests, generated contract, architecture/ADR set, and the historical M1 hardening report. The working tree was clean at review start. Documentation was treated as a claim set and checked against code. `demo/` and `references/` remain read-only, ignored inputs and were not executed or modified.

The baseline CI evidence supplied for this task is preserved as the starting point: Ruff, strict mypy, empty-PostgreSQL migration, Alembic drift check, 36 backend tests including the PostgreSQL-marked integrity/concurrency cases, deterministic OpenAPI generation, ESLint, strict TypeScript, seven Vitest tests, and the Next.js production build. M1.1 must add controls without weakening the same-document current-version FK, parent-row version serialization, one-active-owner partial index, ownership transfer, tenant-principal FKs, or the CASCADE semantics of `fk_document_user_grant_principal_membership`.

## Remaining findings

| Class | Finding | Current behavior | Actual risk | Required correction | Enforcement point | Tests | Status at review start |
|---|---|---|---|---|---|---|---|
| P0 SECURITY | Residual Google/password pre-hijack reclaim | Google can reclaim an account that contains an unverified password identity, but the identity, credential, and verification token survive. | A victim clicking the attacker's old verification link can activate the attacker-chosen password. | On verified Google reclaim, consume all verification tokens and delete the matching unverified password identity/credential; never verify it. Preserve legitimately verified password identities. | Google callback transaction and FK cascades | Database-state adversarial tests for old login/token/resend and legitimate dual identity | Open |
| P1 DATA INTEGRITY | JSONB documentation drift | `EmployeeProfile.profile_metadata` and `AuditEvent.event_metadata` use generic SQLAlchemy `JSON`; ADR 008 claims PostgreSQL JSONB. | Schema and operational documentation disagree; PostgreSQL JSON operators/indexing assumptions would be false. | Use a JSON type with a PostgreSQL JSONB variant and an additive type-conversion migration. | ORM type plus Alembic | Empty migration, drift check, PostgreSQL suite | Open |
| P0 SECURITY | Upload validation trusts browser MIME | The upload allowlist checks `UploadFile.content_type`; bytes are not identified. | Arbitrary/binary content can be persisted and downloaded under an allowed MIME. | Validate PDF structure, DOCX ZIP/OpenXML entries, and UTF-8 text/Markdown; normalize actual type and reject mismatches. | Upload staging boundary | Valid/fake/mismatched PDF, DOCX, ZIP, text, and binary cases | Open |
| P0 SECURITY | No malware scan gate | Files become downloadable after MIME/size checks only. | Known malicious content can enter storage and normal download paths. | Add scanner port, fake/no-op test implementations, clamd adapter, synchronous fail-closed scan before storage, and hardened config validation. | Upload pipeline and readiness | Clean, infected, unavailable, no-persist, hardened-config cases | Open |
| P0 SECURITY | Rate limiting is process-local and uploads are unlimited | Auth uses one in-memory address bucket; hardened config merely asserts an external limiter. Uploads have no limiter. | Replica bypass, global proxy-IP collisions, and authenticated upload abuse. | Add a limiter port with memory and atomic Redis implementations; hardened environments require Redis. Apply address plus hashed email buckets to auth and user+organization buckets to uploads. | Rate-limit adapter and route dependencies | Threshold, scope isolation, Redis integration, hardened rejection, upload cases | Open |
| P1 PRODUCTION | Object storage startup conflates all errors with missing bucket | `ensure_bucket()` catches every exception and attempts creation; static keys are mandatory. | Permission/network/TLS failures are misdiagnosed, and runtime credentials require excessive permission. | Typed storage errors; explicit dev/test auto-create only; hardened access check without creation; ambient credentials; optional provider-side SSE parameters. | Storage adapter, config, readiness | Unit error translation plus MinIO put/read/delete/unavailable integration | Open |
| P1 DATA INTEGRITY | Upload compensation is silent | DB failure triggers delete, but cleanup failure can mask or disappear without an operational signal. | Orphan objects cannot be diagnosed and the original failure may be obscured. | Preserve original exception, log failed compensation with deterministic key, never compensate after commit. | Document upload transaction boundary | DB-failure compensation and cleanup-failure tests | Open |
| P1 PRODUCTION | Post-commit SMTP failures return ambiguous 503 | Registration/reset/invitation state commits before SMTP; a send failure can imply the transaction failed. | Retried registration/invitation conflicts with already-authoritative state and reset may enumerate delivery behavior. | Return explicit delivery status for registration/invitations/resend; keep reset response enumeration-safe; retain resend/reissue recovery. | Email use cases and response schemas | Failing sender tests and frontend messaging | Open |
| P1 OPERATIONS | No dependency-aware readiness | `/healthz` only proves the process responds. | Traffic can reach replicas without database, bucket, Redis, or required scanner connectivity. | Add `/livez` without I/O and `/readyz` with sanitized dependency checks; retain compatibility alias. | FastAPI system endpoints | Ready and each dependency failure mocked | Open |
| P1 OPERATIONS | Request logs are unstructured and unexpected errors lack a controlled envelope | No request-completion JSON log exists; generic exceptions rely on framework behavior. | Correlation and incident response are weak; internal exception text/trace behavior is not explicitly controlled. | Vendor-neutral JSON logging in hardened environments, safe request fields, full server-side exception logging, generic request-ID error response. | Logging setup, middleware, exception handler | Structured-field/redaction and generic-error tests | Open |
| P0 SECURITY | Public web security headers are incomplete | API sends two headers; Next.js public boundary has no configured HSTS/frame/CSP/permissions policy. | Browser hardening depends on deployment defaults and framing/object injection remains under-specified. | Add deliberate production-safe Next headers and a CSP that does not break hydration. | `next.config.ts` | Config/header assertion and production build | Open |
| P1 PRODUCTION | API replicas run migrations on startup | API Docker `CMD` runs Alembic before Uvicorn. | Concurrent replicas race schema changes and runtime credentials need migration privilege. | API starts only Uvicorn; Compose/release process uses one explicit migration job. | Dockerfile, Compose, deployment docs | Image build and Compose validation | Open |
| P0 SECURITY | Containers run as root | API and web runtime stages declare no user. | A container escape or runtime compromise has unnecessary privileges. | Dedicated non-root users and minimal writable paths in both images. | Dockerfiles | Image build and runtime-user inspection where available | Open |
| P1 PRODUCTION | Python dependencies are not reproducibly locked | Broad ranges are resolved by pip on every CI/image build. | Identical commits can receive different transitive dependencies. | Add committed `uv.lock`; pin uv; use frozen sync in CI and production image; document updates. | `pyproject.toml`, lock, CI, Docker | Frozen clean sync | Open |
| P1 TESTING | Supply-chain and deployable images are not CI gates | CI lacks dependency audit, secret scan, and Docker builds. | Known high-severity dependencies, leaked secrets, or broken images can merge despite source tests. | Add Python/Node high-threshold audits, redacted committed-secret scan, and clean API/web image builds. | GitHub Actions | CI jobs themselves | Open |
| P2 MAINTAINABILITY | PostgreSQL health probes target the wrong default database | CI and Compose call `pg_isready -U readyset` without `-d`. | Noisy nonexistent-database logs obscure real service health. | Probe the configured database explicitly. | CI and Compose health checks | Compose config/CI | Open |
| P1 TESTING | Storage/Redis semantics lack real-service coverage | Memory storage and in-process limiter are the only fast tests; CI has PostgreSQL only. | S3/Redis protocol, atomicity, and failure translation can regress. | Add explicit `storage` and `redis` markers, MinIO/Redis services, focused integration cases, and keep unit fakes. | Integration tests and CI | Real MinIO and Redis jobs/cases | Open |
| P2 MAINTAINABILITY | DocumentVersion/audit immutability prose overclaims | Version docs say immutable and security docs say application code cannot modify audit rows; no database trigger/role proves either absolute claim. | Reviewers infer guarantees that do not exist. | State application-immutable source semantics and append-oriented audit convention with privileged-role limitation. | ADR 007 and security docs | Documentation reconciliation | Open |
| P1 OPERATIONS | Frontend omits operational backend flows | Password reset request/resend, document detail/version/ACL actions, and member/owner/invitation administration require manual API calls. | Operators and users cannot safely exercise implemented controls through the product. | Add minimal generated-type-backed UI and API methods without a new component framework. | Next.js client | Security-sensitive transport/component tests | Open |
| P2 MAINTAINABILITY | Permanent repository rules are incomplete | `AGENTS.md` contains production isolation only. | Future changes can unknowingly weaken established architecture/security/operations constraints. | Add the concise M1 engineering constitution while preserving isolation. | `AGENTS.md` | Human/document review | Open |
| P2 MAINTAINABILITY | No current implementation/operations ledger | Historical hardening report ends with broad completion language; no status matrix or provider-neutral deployment/backup runbook exists. | Desired, tested, operational, deferred, and limited behavior is conflated. | Add implementation status, production deployment/backup requirements, a historical note, and traceable security invariants. | Architecture/operations/review docs | Final code-to-doc reconciliation | Open |
| DEFERRED | PostgreSQL RLS | Application/repository scoping remains the M1 tenant boundary. | A future query bug can bypass scoping. | Keep explicitly deferred until transaction-local tenant context and distinct migration/runtime roles are operationally designed. | ADR 004/status ledger | Existing adversarial tenant tests | Deferred |
| DEFERRED | M2 product intelligence/workflows | No parsing jobs, chunks, embeddings, RAG, LMS, agents, connectors, or workflow engine exist. | Scope expansion would obscure production-foundation work. | Keep deferred; only content identification and malware scanning are in M1.1. | Scope rules/status ledger | Repository isolation/scope review | Deferred |

## Implementation sequence

1. Establish permanent repository rules and configuration/adapter foundations.
2. Close Google reclaim and upload security paths with adversarial unit tests.
3. Add JSONB migration and preserve all existing PostgreSQL invariants.
4. Add Redis, storage, readiness, logging, and controlled error operations.
5. Harden containers, migration release flow, dependency locking, and CI services/security gates.
6. Complete the minimum operational frontend flows and regenerate the contract.
7. Reconcile architecture/security/operations documentation against verified behavior.
8. Run every locally available frozen dependency, backend, contract, frontend, Compose, image, and integration gate; leave any unavailable external/runtime gate explicitly unverified.

## Final disposition

This is the current status ledger; the detailed table above intentionally preserves review-start evidence.

| Finding | Final status |
|---|---|
| Google/password reclaim | IMPLEMENTED and unit-tested with database-state assertions |
| PostgreSQL JSONB truth | IMPLEMENTED by additive migration; PostgreSQL execution pending an available service |
| Actual file-content validation | IMPLEMENTED and unit-tested |
| Malware scan gate | IMPLEMENTED and fake-adapter tested; real clamd is an OPERATIONAL REQUIREMENT |
| Shared/upload rate limiting | IMPLEMENTED and unit-tested; real Redis test is CI-defined and locally pending |
| Object storage hardening | IMPLEMENTED; MinIO integration is CI-defined and locally pending |
| Upload compensation | IMPLEMENTED and unit-tested |
| Synchronous email semantics | IMPLEMENTED and unit-tested |
| Liveness/readiness | IMPLEMENTED and unit-tested with dependency fakes |
| Structured logging/unexpected errors | IMPLEMENTED; controlled envelope tested |
| Public web security headers | IMPLEMENTED; Next production build verified locally |
| Separate migration release step | IMPLEMENTED in image/Compose/runbook; image execution pending Docker availability |
| Non-root containers | IMPLEMENTED in Dockerfiles; runtime inspection pending Docker availability |
| Reproducible Python dependencies | IMPLEMENTED with committed `uv.lock` and frozen CI/image commands |
| Security/image CI gates | IMPLEMENTED in workflow; remote run pending |
| Correct PostgreSQL probes | IMPLEMENTED in Compose and CI |
| MinIO/Redis integration coverage | IMPLEMENTED and CI-wired; locally pending services |
| Immutability/audit wording | IMPLEMENTED in reconciled docs |
| Frontend operational flows | IMPLEMENTED; typecheck, tests and production build verified locally |
| Engineering constitution | IMPLEMENTED |
| Status/deployment/backup/traceability docs | IMPLEMENTED |
| PostgreSQL RLS | DEFERRED |
| M2 intelligence/workflows | DEFERRED and untouched |

M1.1 is not declared complete until the PostgreSQL, MinIO, Redis, Docker-image, secret-scan, and remote CI gates execute successfully.

## Local verification record

Executed on 2026-09-18:

- `uv sync --frozen --extra dev`: passed from the committed lock (Python 3.12.13, 88 packages after the audited pytest update).
- Ruff: passed.
- strict mypy: passed, 22 source files.
- pytest with coverage: 56 passed, 7 skipped service-marked tests, 2 warnings, 87% application coverage.
- `pip-audit`: no known vulnerabilities; the local `readyset-api` project is correctly skipped because it is not a PyPI distribution.
- `npm ci`: passed; `npm audit --audit-level=high`: 0 vulnerabilities.
- generated OpenAPI/client reproduction: byte-stable SHA-256 hashes after a second export/generation.
- ESLint and strict TypeScript: passed.
- Vitest: 3 files, 9 tests passed.
- Next.js production build: passed; 9 static routes generated.
- Compose model: `docker compose config --quiet` passed.
- CI YAML parse and `git diff --check`: passed.
- Alembic PostgreSQL offline SQL generation through `f6f5b16f7d31`: passed.

Not executed locally: online Alembic upgrade/check, PostgreSQL-marked tests, MinIO test, Redis test, gitleaks, and API/web image builds. Docker Desktop's engine did not become responsive and local PostgreSQL timed out. These gates are defined in CI but must pass there before M1.1 is called complete.
