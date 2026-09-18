# Infrastructure

`docker-compose.yml` is the M1 local environment. The supported public topology is a single HTTPS Next.js origin with `/api/*` proxied to a private FastAPI origin. Configure `PUBLIC_WEB_URL` and the Google callback to that public origin; configure `API_INTERNAL_URL` only as the web server's internal proxy target. Cookies stay host-only.

Production should use managed PostgreSQL and S3-compatible storage with separate least-privilege credentials, TLS, backups, centralized rate limiting, SMTP delivery, and secret management. `ENVIRONMENT=staging|production` validates these prerequisites and refuses local/default credentials, insecure URLs/cookies, capture email, development token exposure, or an unacknowledged shared limiter. Kubernetes is intentionally not part of M1.
