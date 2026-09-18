# Infrastructure

`docker-compose.yml` is the M1 local environment. Production should use managed PostgreSQL and S3-compatible storage with separate least-privilege credentials, TLS, backups, centralized rate limiting, and secret management. Kubernetes is intentionally not part of M1.
