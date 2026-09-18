# M1.1 implementation status

Status words are evidence labels, not a general claim that a deployment is safe without its required services.

| Area | Implementation | Tests | Production dependency | Status |
|---|---|---|---|---|
| Authentication | Password registration, verification, reset, Argon2id credentials | Unit/adversarial auth tests | SMTP; secret manager | TESTED |
| Google OAuth | Authorization Code, PKCE, nonce, state and browser binding; explicit reclaim | Mocked adversarial provider tests | Google client and exact callback | TESTED |
| Sessions | Opaque hashed cookies bound to exact identity | Identity/revocation tests | PostgreSQL; TLS | TESTED |
| Organizations | Create, select, rename | Unit/API tests | PostgreSQL | TESTED |
| Membership/RBAC | Central capability policy, revoke, role change, atomic owner transfer | Unit and PostgreSQL owner-index tests | PostgreSQL | TESTED |
| People | Tenant-scoped employee profiles | Unit tenant tests | PostgreSQL | TESTED |
| Teams | Tenant-scoped teams and members | Unit tenant tests | PostgreSQL | TESTED |
| Documents | Tenant-scoped metadata and proxied files | ACL/adversarial tests | Private S3-compatible bucket | TESTED |
| Versions | Parent lock, sequential numbering, same-document current pointer | PostgreSQL integrity/concurrency tests | PostgreSQL | TESTED |
| ACL | Reusable server-side user/team predicate | Cross-tenant/restricted tests | PostgreSQL | TESTED |
| File content validation | PDF signature/EOF, DOCX structure, UTF-8 text checks and MIME match | Valid/invalid/mismatch tests | Bounded API upload | TESTED |
| Malware scan | Synchronous scanner port and clamd adapter; development/test fake/no-op | Clean/infected/unavailable tests | Reachable maintained ClamAV service | TESTED |
| Object storage | Typed S3 adapter, least-privilege access check, optional SSE/KMS, explicit local bucket creation | Memory tests pass; MinIO-marked test awaits service execution | Private pre-created bucket, IAM/workload identity | IMPLEMENTED |
| Rate limiting | In-memory local adapter; atomic Redis fixed-window production adapter; auth/upload dimensions | Unit tests pass; Redis-marked test awaits service execution | Redis; trusted edge peer normalization | IMPLEMENTED |
| Email | Capture and SMTP; committed state is authoritative; delivery status where disclosure is safe | Sender and failure-semantics tests | TLS SMTP provider | TESTED |
| Audit | Append-oriented API behavior through `record_audit` | Event assertions | Log retention and DB access controls | IMPLEMENTED |
| PostgreSQL | Alembic schema, relational invariants, JSONB metadata | Baseline integrity suite passed; new migration/drift execution awaits service availability | Managed/operated PostgreSQL | IMPLEMENTED |
| Frontend | Auth recovery, document/version/ACL, member/invitation operations | Vitest transport/workspace/auth tests and production build | Public TLS origin and same-origin API proxy | TESTED |
| OpenAPI contract | FastAPI export and generated TypeScript declarations | CI drift check | None | TESTED |
| Docker | Locked API build; API/web non-root; migration command separated | CI image build definitions | OCI runtime | IMPLEMENTED |
| CI | Unit, PostgreSQL, MinIO, Redis, contract, web, images and security gates defined | GitHub Actions workflow | GitHub-hosted services/network | IMPLEMENTED |
| Logging | Request completion fields; JSON in hardened environments; controlled exception logging | Error-envelope test | Central collection/redaction controls | IMPLEMENTED |
| Readiness | `/livez`; `/readyz` checks DB, storage, limiter and required scanner | Mocked readiness tests | Orchestrator probes | TESTED |
| Backups | Provider-neutral requirements documented | Restore drill is external | PITR-capable PostgreSQL and object durability | OPERATIONAL REQUIREMENT |
| Deployment | Ordered migration/release/runbook documented | Must be rehearsed per platform | Provider selection and secret manager | OPERATIONAL REQUIREMENT |
| RLS | Application/repository scoping remains the M1 tenant boundary | Tenant adversarial tests | Revisit for regulated deployments | DEFERRED |
| RAG/M2 | No parsers, chunks, embeddings, LMS, agents, queues, or connectors | Scope/isolation review | M2 decision | DEFERRED |

## Known limitations

- Document source identity is application-immutable, not protected by a database update trigger.
- Audit rows are append-oriented through application APIs; privileged database and migration roles can modify them.
- Synchronous SMTP can fail after authoritative state commits. Registration and invitation responses represent this explicitly; reset and verification-resend remain non-enumerating.
- Local verification without PostgreSQL, MinIO, Redis, Docker, and ClamAV does not prove their operational gates.
