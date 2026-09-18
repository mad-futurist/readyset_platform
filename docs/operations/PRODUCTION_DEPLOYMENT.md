# Production deployment requirements

This is provider-neutral. Select and validate an actual cloud/runtime before deployment.

## Topology and isolation

```text
public TLS Next.js origin
          |
       /api/*
          v
private FastAPI service -> PostgreSQL
                        -> private S3-compatible bucket
                        -> Redis
                        -> ClamAV/clamd
                        -> TLS SMTP
```

Deploy staging and production with separate accounts/projects, networks, databases, buckets, Redis databases, OAuth clients, email credentials, keys, and backup policies. The browser receives none of these credentials. Store runtime secrets in the platform secret manager, never in images or frontend build arguments.

## Release order

1. Build immutable API and web images from the committed lockfiles.
2. Back up the database and verify dependency health.
3. Run exactly one API image as a release job with `alembic upgrade head` using a migration role.
4. Stop if migration fails. Do not start new API replicas against a partial schema.
5. Roll out API replicas as the non-root runtime user; their normal database role should not have schema-migration privileges where the platform permits separation.
6. Wait for `/readyz`; then roll out the non-root Next.js image.
7. Exercise sign-in, upload/scan/download, and tenant isolation smoke tests.

The API image starts only Uvicorn. Docker Compose models the migration job separately. Rollback means restoring the prior application images when the migration is backward-compatible. A data/schema rollback requires an explicitly reviewed downgrade or restore; never assume every Alembic downgrade is lossless.

## Required services and configuration

- **PostgreSQL:** supported version, TLS in transit, encrypted storage, connection limits, monitoring, automated backups, point-in-time recovery, and a least-privilege runtime role.
- **Object storage:** private pre-created bucket. Runtime credentials need object read/write/delete and bucket access checks, not bucket creation. Prefer workload identity/IAM roles; static key pairs are optional. Configure `AES256` or `aws:kms` (and its key ID) and enforce compatible bucket encryption. Block public access and lifecycle changes outside controlled infrastructure.
- **Redis:** shared, authenticated/TLS endpoint for application rate limiting. `RATE_LIMIT_BACKEND=redis` and a `rediss://` `REDIS_URL` are mandatory in staging and production. Plain `redis://` is a development/test-only transport.
- **Trusted proxy:** leave `TRUST_PROXY_HEADERS=false` when FastAPI receives direct client connections. When a reverse proxy or load balancer is the immediate peer, set `TRUST_PROXY_HEADERS=true` and list only its exact network ranges in `TRUSTED_PROXY_CIDRS`. The API accepts `X-Forwarded-For` only from those peers and walks the chain right-to-left past trusted hops. Untrusted or malformed forwarding data falls back to the immediate peer. Keep the proxy's overwrite/append behavior and these CIDRs aligned.
- **Malware scanning:** maintained ClamAV/clamd reachable only from the API network. `SCANNER_BACKEND=clamav` is mandatory while uploads are enabled. Scanner outage makes uploads fail closed and readiness fail.
- **Email:** TLS-capable SMTP account and routable sender. Committed account/invitation state remains authoritative if delivery fails; users retry verification and administrators reissue invitations. Reset responses never disclose account or SMTP state.
- **Google OAuth:** separate production client, exact HTTPS `${PUBLIC_WEB_URL}/api/v1/auth/google/callback`, secret-manager client secret, and tested consent-screen/domain configuration.
- **TLS and edge:** terminate modern TLS, preserve the same public origin for `/api/*`, enforce request/body limits compatible with `MAX_UPLOAD_BYTES`, and do not cache authenticated responses. HSTS is emitted by Next.js in production.

Hardened configuration fails validation for HTTP origins, insecure cookies, development token exposure, capture email where delivery is required, memory limiting, non-TLS Redis, trusted-proxy mode without explicit CIDRs, absent malware scanning, bucket auto-creation, absent storage encryption, local/default credentials, wildcard CORS, and callback mismatch.

## Health, logs, and monitoring

- Probe `/livez` for process liveness. It performs no dependency I/O.
- Probe `/readyz` before routing traffic. It checks `SELECT 1`, bucket access, the configured limiter, and the scanner when uploads are enabled. It returns only `ready` or `unavailable`.
- Collect structured JSON stdout/stderr. Index timestamp, level, request ID, method, path, status, latency, and safe user/organization IDs. Do not ingest cookies, auth/recovery/invitation/OAuth tokens, passwords, file bodies, or service secrets.
- Alert on readiness failures, 5xx rate, scanner/Redis/storage failures, SMTP failure rate, latency, DB saturation, and backup failures.

## Backup and restore

PostgreSQL requires automated encrypted backups, point-in-time recovery, a documented retention period, and scheduled restore drills into an isolated environment. Object storage requires provider durability, versioning or another recovery mechanism appropriate to deletion risk, encryption, lifecycle/retention policy, and restore/download drills. Backups are not sufficient until a restore has been tested. Record RPO/RTO, owners, evidence, and the last successful drill. Never restore production data into a less protected staging environment without approved sanitization.

## Preflight and human decisions

Before public production, decide and record: runtime/cloud provider, managed-auth versus the self-managed M1 core, ClamAV deployment/maintenance owner, email provider, backup retention/RPO/RTO, public Apache-2.0 licensing intent, data residency, and incident response ownership. Run all CI gates plus platform-specific migration, restore, rollback, load, and security tests in staging.
