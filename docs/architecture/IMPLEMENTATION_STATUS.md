# Implementation status

The foundation table records verified M1.1 history; the M2 ledger below records the new milestone.

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
| Malware scan | Synchronous scanner port and clamd adapter; development/test fake/no-op | Adapter behavior tested for clean/infected/unavailable; no real clamd CI service | Reachable maintained ClamAV service and signatures | TESTED (ADAPTER); OPERATIONAL REQUIREMENT (CLAMD) |
| Object storage | Typed S3 adapter, eager stream open, least-privilege access check, optional SSE/KMS, explicit local bucket creation | Pre-header 404/503 route tests and real MinIO lifecycle/missing/compensation/authorization tests | Private pre-created bucket, IAM/workload identity | TESTED |
| Rate limiting | In-memory local adapter; atomic Redis fixed-window production adapter; auth/upload dimensions; explicit trusted-proxy resolution | Unit/config/proxy tests and real Redis shared-state/TTL/threshold/scope test | TLS Redis; exact proxy CIDRs/topology | TESTED |
| Email | Capture and SMTP; committed state is authoritative; delivery status where disclosure is safe | Sender and failure-semantics tests | TLS SMTP provider | TESTED |
| Audit | Append-oriented API behavior through `record_audit` | Event assertions | Log retention and DB access controls | IMPLEMENTED |
| PostgreSQL | Alembic schema, relational invariants, JSONB metadata | Empty-DB online upgrade through `f6f5b16f7d31`, clean drift check, JSONB assertion and integrity/concurrency suite | Managed/operated PostgreSQL | TESTED |
| Frontend | Auth recovery, document/version/ACL, member/invitation operations | Vitest transport/workspace/auth tests and production build | Public TLS origin and same-origin API proxy | TESTED |
| OpenAPI contract | FastAPI export and generated TypeScript declarations | CI drift check | None | TESTED |
| Docker | Locked API build; API/web non-root; migration command separated | API/web images build; runtime users verified as `readyset`/`node` | OCI runtime | TESTED |
| CI | Isolated core/PostgreSQL, MinIO, Redis, contract/web, image and security jobs | GitHub Actions run `35351063508` green on closure implementation commit `5da1c18453379ceaca3f03038ee63c610ca55ff0` | GitHub-hosted services/network | TESTED |
| Logging | Request completion fields; JSON in hardened environments; controlled exception logging | Error-envelope test | Central collection/redaction controls | IMPLEMENTED |
| Readiness | `/livez`; `/readyz` checks DB, storage, limiter and required scanner | Mocked readiness tests | Orchestrator probes | TESTED |
| Backups | Provider-neutral requirements documented | Restore drill is external | PITR-capable PostgreSQL and object durability | OPERATIONAL REQUIREMENT |
| Deployment | Ordered migration/release/runbook documented | Must be rehearsed per platform | Provider selection and secret manager | OPERATIONAL REQUIREMENT |
| RLS | Application/repository scoping remains the M1 tenant boundary | Tenant adversarial tests | Revisit for regulated deployments | DEFERRED |
| RAG/M2 (at M1 closure) | Historical M1 deferral; superseded by the M2 ledger below | See M2 evidence | See M2 operations | HISTORICAL DEFERRED |

## Known limitations

- Document source identity is application-immutable, not protected by a database update trigger.
- Audit rows are append-oriented through application APIs; privileged database and migration roles can modify them.
- Synchronous SMTP can fail after authoritative state commits. Registration and invitation responses represent this explicitly; reset and verification-resend remain non-enumerating.
- CI proves PostgreSQL, MinIO and Redis protocol behavior plus container construction; the selected production providers and real maintained ClamAV deployment remain operational responsibilities.

## M2 document intelligence

| Area | Implementation/evidence | Status |
|---|---|---|
| Worker | Independently runnable shared-package process, non-root image, heartbeat and graceful stop | IMPLEMENTED; image/runtime checks in verification ledger |
| Ingestion jobs | Transactional upload enqueue, unique version job, SKIP LOCKED, renewable fenced leases, backoff/reclaim/manual retry | TESTED on PostgreSQL |
| Extraction | Bounded structured PDF/DOCX/Markdown/text with source locators and synthetic corpus | TESTED |
| Chunking | Deterministic tokenizer bounds, structural/page boundaries and Unicode-safe split spans | TESTED |
| Embeddings | Fake and OpenAI ports, batched inputs, fixed 1536 dimensions | TESTED with mocks and 2026-10-02 real OpenAI evaluation; production provider approval remains OPERATIONAL REQUIREMENT |
| Vector index | Additive pgvector/type/HNSW/GIN migration, composite integrity and clean drift | TESTED on PostgreSQL |
| Retrieval | SQL ACL before exact vector/lexical ranking, live grants/member role, current READY and archived semantics | TESTED on PostgreSQL |
| Ask AI | Stateless read-only bounded context, source instructions treated as data, post-generation eligibility check | TESTED with fake and 60-question real-provider baseline; semantic grounding has measured limitations |
| Citation provenance | Organization/document/version/chunk/locator, server labels, unknown-label rejection | TESTED |
| Frontend | Ingestion polling/status/retry, workspace Ask AI, citation source-version metadata | IMPLEMENTED; exact web checks in verification ledger |
| Provider decisions | Vendor terms/retention/region, key management, real-provider acceptance | OPERATIONAL REQUIREMENT |
| Scale/OCR | Exact authorized-subset ranking; no OCR or complete PDF/DOCX layout reconstruction | KNOWN LIMITATION |
| M3+ | LMS, onboarding, agents/actions, connectors, memory, billing and generic pipelines | DEFERRED |

M2 closure and exact CI results are tracked in `docs/review/M2_VERIFICATION.md`; fake tests do not establish live-provider quality. The separate 2026-10-02 [real-provider evaluation](../evaluation/M2_REAL_PROVIDER_EVALUATION.md) preserves the baseline: 10 documents, 60 questions, 100% citation provenance, 88.5% citation support, 3.67/4 factual correctness. Verdict: **READY WITH TARGETED M2.1 FIXES**. A real-model bare unknown source-label validation defect was fixed; retrieval/citation entailment weaknesses remain KNOWN LIMITATIONS. M3 remains DEFERRED.

M2 IMPLEMENTED and TESTED closure: remote CI run `36876978380`, implementation head `c3e859082bc31cc0f1e51f72b471135d218360ea`, all eight jobs green including packaged fake-provider acceptance. The final delivery head is rechecked remotely before delivery.
