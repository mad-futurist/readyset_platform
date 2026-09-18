# Infrastructure

`docker-compose.yml` is the M1 local environment. The supported public topology is a single HTTPS Next.js origin with `/api/*` proxied to a private FastAPI origin. Configure `PUBLIC_WEB_URL` and the Google callback to that public origin; configure `API_INTERNAL_URL` only as the web server's internal proxy target. Cookies stay host-only.

Production requires operated PostgreSQL, a private pre-created encrypted S3-compatible bucket, Redis application rate limiting, a maintained clamd scanner while uploads are enabled, TLS SMTP, a secret manager, and tested backup/restore. `ENVIRONMENT=staging|production` rejects local/default credentials, insecure URLs/cookies, capture email, development token exposure, memory-only limiting, no-op scanning, and bucket auto-creation. Kubernetes is intentionally not part of M1. See `docs/operations/PRODUCTION_DEPLOYMENT.md`.
