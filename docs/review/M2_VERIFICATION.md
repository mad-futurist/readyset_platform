# M2 verification and security review

Status: IMPLEMENTED and TESTED; M2 implementation closed by fully green remote CI run 36876978380 on c3e859082bc31cc0f1e51f72b471135d218360ea. The final delivery head is also required to pass CI before delivery. This ledger never treats mocked providers as live-provider validation.

## Architecture implemented

Shared-backend modular monolith with an independent non-HTTP worker; PostgreSQL queue/leases, bounded spool/extraction/chunking/batched embeddings, current-version authorized hybrid retrieval and stateless evidence-backed Ask AI. No production imports/build/runtime dependencies on demo/references.

## New entities and migrations

Additive `b17a9d2e6c40`: IngestionJob, ExtractedArtifact, DocumentChunk, ChunkEmbedding, safe version failure fields, pgvector/HNSW/GIN, composite tenant lineage and unique identities. Published migrations remain unchanged; existing clean M1 uploaded versions are queued.

## Worker/job semantics

SKIP LOCKED, one unique job/version, renewable UUID attempt leases, database wall-clock fencing, expired reclaim/exhaustion, capped backoff, manager retry and atomic output/state commit. At least once execution can repeat external work; stale attempts cannot publish. Private heartbeat health and graceful shutdown; runtime limits/grace/supervision remain operational.

## Extraction implementation

pypdf page text; python-docx ordered body/heading/table extraction; line-based UTF-8 Markdown/text. All fixtures are generated synthetic content. Locator correctness, order, empty pages, Unicode and corrupt/oversized input are tested. OCR and full layout semantics are limited/deferred.

## Chunking strategy

Structure/page boundaries, 400 target/800 max cl100k tokens, Unicode-safe long-block split spans, no implicit overlap, reproducible configuration and version-scoped deterministic identities.

## Embedding/index implementation

Fake and OpenAI embedding ports, batching, finite/nonzero/dimension checks, fixed 1536 PostgreSQL vector width and metadata, HNSW cosine/lexical GIN schema indexes. Strict retrieval computes exact ranking inside an authorized materialized SQL subset; use of ANN acceleration is deferred pending measured secure optimization.

## Retrieval and ACL enforcement

Live membership/admin role plus the existing document ACL precede all candidate ranking. Only active current READY versions are eligible. User/team grants, cross-tenant filters and generation-time state changes are adversarially tested. Archived/new processing/failed sources are absent; no silent stale fallback.

## Ask AI and citation contract

Search works independently. Ask AI uses a complete-prompt/per-chunk/answer token budget, treats sources as untrusted data, has no actions/memory and maps S-labels on the server. Unknown/uncited output is rejected; no evidence skips chat. Post-generation eligibility recheck invalidates stale responses.

## Frontend changes

Knowledge status polling, safe failure/retry, current/history metadata, Ask AI, page/section/version/excerpt citations and exact-version source metadata/download. All DTOs are generated from FastAPI OpenAPI.

## Security tests and closure questions

| Question | Boundary/evidence |
|---|---|
| Can Org A retrieve Org B chunks? | No: tenant/ACL SQL and cross-tenant exact-query/UUID filter tests |
| Can an ungranted member retrieve restricted chunks? | No: user/team/owner/admin policy, tested before/after grants |
| Can stale grants/roles/membership leak through embeddings? | Live SQL policy, revoke tests and cached-owner-context test |
| Can a model invent citations? | Unknown labels invalidate answer; returned citation objects are server-mapped request evidence |
| Can source instructions bypass authorization? | Model context is authorized data; malicious-source fake-provider capture test |
| Can retries duplicate chunks? | Unique version/ordinal, deterministic IDs and fenced atomic output transaction/redelivery tests |
| Can two workers process one job? | One valid active lease at a time, competing claimer/SKIP LOCKED tests; redundant expired-attempt work is possible but cannot publish |
| Can failed current versions cause silent stale answers? | Current READY equality, processing/failure/new-version/archive PostgreSQL scenarios |
| Can raw enterprise text leak to ordinary logs? | Safe fixed codes/metrics/audits, SQL parameter hiding and content redaction test; external collector configuration is operational |
| Can provider credentials reach the browser? | Environment-only SecretStr backend config; generated contracts/client contain no keys; package/image isolation reviewed |

## PostgreSQL/pgvector integration evidence

2026-10-01 local isolated `pgvector/pgvector:0.8.2-pg17` container, separate from research and application data:

- Empty-database `alembic upgrade head` through `b17a9d2e6c40`: passed.
- `alembic check`: “No new upgrade operations detected.”
- PostgreSQL/pgvector test suite: 10 passed, covering composite lineage, real database vector width/metadata, extension/index existence, cosine query, ACL/version/citations, concurrency, lease fencing and concurrent retry.
- Final full backend/service suite: 111 passed, 2 warnings, 89% coverage, no skips; includes 4 M1 PostgreSQL, 10 pgvector, 3 MinIO, 1 Redis and 3 worker-runtime tests.
- Additional adversarial complete-prompt/excerpt/answer token-bound test: 1 passed separately after the full run (112 total test cases in final source).
- Ruff passed; strict mypy passed all 34 source files.

## Exact CI results

Initial remote run [36875964405](https://github.com/mad-futurist/readyset_platform/actions/runs/36875964405) on `b9632a994341b43b815b0b7f525b16884c81b68f`: api-core, worker, vector-retrieval-integration, redis-integration, web and security passed. Storage/container jobs failed before application acceptance because the existing official MinIO image now returns registry authorization errors. Corrected local/CI packaging builds a SHA256-verified official security-release source archive with upstream locked Go modules; production storage remains externally operated.

Closure implementation run [36876978380](https://github.com/mad-futurist/readyset_platform/actions/runs/36876978380), PR #1, head `c3e859082bc31cc0f1e51f72b471135d218360ea`: completed SUCCESS, all eight jobs green.

| Job | Observed result |
|---|---|
| api-core | SUCCESS: frozen sync, Ruff, strict mypy (34 files), empty-DB migration, clean Alembic drift, 108 tests, 88% coverage (4 service tests deselected) |
| worker | SUCCESS: 16 tests |
| vector-retrieval-integration | SUCCESS: migration/drift and 10 real PostgreSQL/pgvector tests |
| storage-integration | SUCCESS: pinned official source image, 3 MinIO integration tests |
| redis-integration | SUCCESS: 1 Redis integration test |
| web | SUCCESS: OpenAPI/TypeScript drift, lint/typecheck, 12 tests and production build |
| containers | SUCCESS: API/web/worker/MinIO images, non-root users, one release migration, live upload-to-answer/ACL/retry acceptance and worker health |
| security | SUCCESS: pip-audit, npm audit and full-history redacted Gitleaks |

No application checks were relaxed to resolve the initial registry failure. The final delivery response links the run for the final delivery head, avoiding a self-referential commit/run assertion.

## Local web/runtime/security evidence

After audited dependency updates: frontend lint/typecheck, 12 tests and Next 16.3.8 production build passed. API/web/worker images built; runtime users `readyset`/`node`/`readyset` verified. API and worker tokenization succeeded with `--network none`. Compose model passed. Live independently packaged API/worker/PostgreSQL/MinIO acceptance passed: page-3 PDF citation to exact version, replacement-version isolation, restricted grant/revoke and membership revocation, safe corrupt-PDF failure and manager retry. Committed-history Gitleaks scan passed; final commit history is also gated remotely. Backend audit initially found PyJWT CVE-2026-101918; lock was updated to 2.15.1 and audit then reported no known vulnerabilities. npm audit found Next.js GHSA-vcvr-r3jv-pc5j; lock was updated to 16.3.8 and audit reported zero vulnerabilities. No live external AI calls were made during this original closure; the later evaluation below uses real OpenAI.

## Remaining known limitations

Exact authorized-subset ranking scales with accessible corpus; indexed ANN acceleration is not claimed. No OCR/complete PDF layout or complete DOCX peripheral content. Fake chat is a local extractive preview; semantic answer accuracy and citation entailment require real-model evaluation. At least once processing can duplicate provider cost. Local/CI MinIO uses an archived upstream security-release source build; select and maintain production S3 separately. Worker heartbeat is liveness, not progress. PostgreSQL RLS and privileged-role immutability remain M1 limitations.

## Operational AI-provider decisions

Approve vendor retention/training/region/contractual terms and permitted tenant data; supply backend credentials through secret manager; choose a supported embedding model and approved chat model/tokenizer; provision vector; supervise private workers with CPU/memory/grace limits; rehearse staging acceptance. No paid provider calls ran during the original closure/CI. The separate 2026-10-02 disposable evaluation exercised paid providers on public/synthetic data.

## Subsequent real-provider evaluation (2026-10-02)

TESTED: [frozen report and machine-readable evidence](../evaluation/M2_REAL_PROVIDER_EVALUATION.md), 10 supported-format sources, 60 prewritten questions, independent worker/OpenAI embeddings/PostgreSQL, real structured chat. Baseline Hit@5 96.2%, MRR 0.825, correctness 3.67/4, citation support 88.5%, provenance 100%, strict absent-question abstention 7/8. Live tenant/ACL/revocation and two PROCESSING-to-READY replacement scenarios passed. A supplemental injection exposed bare `S999` in answer prose; the bracket-only validation gap was fixed with eleven adversarial regression cases and affected live-provider retests. Full local suite after correction: 123 backend tests (PostgreSQL, storage and Redis enabled), 12 frontend tests, lint/typecheck/build, clean Alembic and generated contracts. Final-head remote CI is checked before delivery; the delivery response links that run without making a self-referential commit claim.

KNOWN LIMITATION: source-support entailment remains weaker than identifier provenance; the evaluation verdict is READY WITH TARGETED M2.1 FIXES. No prompt/ranking/model tuning was merged, and the pre-fix baseline is preserved. Production provider contracts, load, malware-scanner deployment and restore drills remain OPERATIONAL REQUIREMENTS.

## M2.1 candidate verification (2026-10-02)

IMPLEMENTED in the draft: bounded English literal-term lexical search inside the existing authorized SQL subset; structured `sufficient` plus source-label/passage-ID selections; exact original-source reconstruction and selected-only citations. Maximum twelve selections is enforced in both the provider schema and server. Stored extraction/chunks/embedding inputs, models, schema, ACL/current-version/lease rules and public DTOs are unchanged. Production containers do not include evaluation scripts or artifacts; demo/references isolation is preserved.

TESTED locally: final full backend with real PostgreSQL/pgvector, MinIO and Redis: 145 passed, two warnings, no skips (57.28 seconds), including the final provider-schema bound. A preceding rerun failed the preexisting locked-job test once; isolated rerun passed, and its shared queue fixture now makes jobs already due relative to the database clock, independent of host/DB clock differences. Production scheduling is unchanged. Provider suite passed 12 tests. Focused grounding/security/lexical tests passed 45; PostgreSQL/vector/lexical tests passed 13. Ruff and strict mypy (35 source files) passed. Empty-database migration and clean Alembic drift passed; published migrations are unchanged. OpenAPI/TypeScript generation drift is clean. Frontend lint/typecheck, twelve tests and Next 16.3.8 production build passed. Local API and worker images built with non-root `readyset`; API tokenization succeeded without network. The final delivery head must pass all eight existing CI jobs; its observed run is linked in the delivery response rather than asserted in its own commit. CI makes no live paid provider calls.

TESTED real providers: [comparison and complete evidence](../evaluation/m2_1/M2_1_COMPARISON.md), unchanged frozen 60-question hash and ten source hashes, fresh database/bucket/organization/users/worker/embeddings. Ten uploads reached READY, 260 chunks and 68,000 embedding tokens; extraction blocks/locators match M2. Two incomplete trials, a partial security run and transport-only retries are disclosed separately; no low-quality 200 response was retried or replaced. Fifteen full live security scenarios, four stronger injection/restricted/S999 supplements and two real-product constrained-evidence supplements passed. Primary metrics exclude supplements/trials. The exact supplied credential was absent from workspace/build/log files and Git history; original twenty evaluation artifacts remained byte-identical.

| Quality measure | M2 baseline | M2.1 candidate |
|---|---:|---:|
| Overall Hit@5 | 50/52 | 50/52 |
| PDF Hit@5 | 13/15 | 14/15 |
| NIST Hit@5 | 3/5 | 4/5 |
| Correctness /4 | 3.67 | 3.50 |
| Material citation precision | 77/87 (88.5%) | 66/68 (97.1%) |
| Claim coverage | 166/173 (96.0%) | 150/154 (97.4%) |
| Technical provenance | 87/87 | 68/68 |
| Absent-question abstention | 7/8 | 8/8 |
| False abstention | 0/52 | 0/52 |

KNOWN LIMITATION, acceptance-blocking: valid but irrelevant passage selections are not mechanically rejected. Q013 selects an introduction rather than phase names, Q016 loses the required waiting-period passage, and Q058 selects Atlas rather than warehouse ownership. The quote-construction tests prove source containment and unknown-reference rejection, not universal semantic relevance. Verdict **NOT READY — GROUNDING/RETRIEVAL REGRESSION**; engineering/security success does not establish M2.1 quality acceptance. Both changes remain independently reviewable in the draft. All sixty answers were manually reviewed twice by the same assessor, with the Q008 score disagreement and Q016 source-audit correction recorded; independent human agreement is unavailable.

KNOWN LIMITATION: the primary persistence-only worker timing was lost when a security restart reused its log path. It is explicitly unavailable; DB stage/job totals remain measured. The collector now separates security logs. Local sequential latency samples are not production SLAs. Provider/data approval, private storage/scanning, release migration/backup/load rehearsal remain OPERATIONAL REQUIREMENTS.

## Explicitly deferred M3+ work

Learning/course/onboarding/task models, agents/tools/actions, signals, connectors/sync, long-term memory, billing, external queues/search engines and generic pipelines remain deferred.

Local development TLS proxy: MinIO Go module downloads initially failed certificate verification inside the builder, while standard-network CI passed. The builder accepts an optional public-CA BuildKit secret for enterprise proxy trust; TLS/checksum verification stays enabled and the CA is not copied into the runtime image.
