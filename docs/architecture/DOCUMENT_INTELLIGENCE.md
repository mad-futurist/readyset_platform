# Document intelligence (M2)

## Pipeline and lineage

IMPLEMENTED: clean upload writes a private source object, then commits DocumentVersion and its unique IngestionJob in the same transaction. The API performs no parsing or embeddings during upload. Migration `b17a9d2e6c40` also queues existing M1 UPLOADED versions, preserving source identity. The worker independently runs `apps/worker/run.py` against the same backend package/lock and has no public HTTP interface.

Organization → Document → immutable DocumentVersion → IngestionJob / ExtractedArtifact / DocumentChunk → ChunkEmbedding. Composite FKs enforce tenant identity on every derived hop. Unique version/ordinal and chunk/provider/model identities prevent duplication. Normalized blocks include type/text/order/heading path/source locator. Chunks retain contributing locators, character spans, SHA-256, token counts and reproducible chunker identity.

## Jobs and product state

Job states are PENDING → RUNNING → SUCCEEDED, RETRYABLE or FAILED. Version state is UPLOADED → PROCESSING → READY or FAILED. Scheduled retry changes FAILED → PROCESSING; explicit terminal retry changes FAILED → UPLOADED. READY has no ordinary retry transition. Retry of an already pending/running/succeeded job is an idempotent no-op.

PostgreSQL SKIP LOCKED selects one available job, increments attempts and assigns a fresh UUID lease. A thread renews every lease-duration/3 using a separate short session. All finalization/failure requires locked job ownership and unexpired database wall-clock time. Parsing/download/provider calls happen outside DB transactions. Reclaim of an expired last attempt marks terminal FAILED. Transient provider/storage/database errors use capped exponential retry; corrupt, empty, unsupported, source-integrity and invalid-vector failures are terminal. Only fixed safe codes/messages enter job/version records.

The worker atomically replaces artifact/chunks/embeddings and marks version READY/job SUCCEEDED. A crash during that transaction rolls back. A late old attempt cannot commit over a reclaimed lease. Duplicate external provider work remains possible under at-least-once execution; exactly-once billing is not promised.

SIGTERM/SIGINT stops new claims and finishes the current attempt. Deployment grace is 120 seconds by default; forced termination relies on lease expiry. A private `/tmp/readyset-worker.health` timestamp is updated in the polling loop and during lease renewal; `python worker.py --health` checks freshness. Liveness is not proof of ingestion progress or queue freshness. Alert on queue age, failures and missing renewal in deployment monitoring.

## Extraction and chunks

IMPLEMENTED: pypdf page text, python-docx ordered body paragraphs/tables/headings, UTF-8 Markdown/text. See ADR 010 for format limits. Locators use one-based PDF pages, DOCX paragraph/table/body indices, and text/Markdown line ranges. Oversized blocks include exact character offsets so a locator never relies only on chunk ordinal. Empty pages do not manufacture evidence.

Token-aware chunking targets 400 and caps 800 tokens, within heading/page boundaries, without overlap. Long blocks split on whitespace where useful and at Unicode-safe character boundaries. Chunker identity includes tokenizer/target/max/overlap; extractor identity records implementation/library version. The bounded JSONB artifact stores normalized blocks rather than duplicate binary sources. Memory/CPU container limits remain an OPERATIONAL REQUIREMENT for adversarial compressed files.

## Providers and indexes

Provider-neutral EmbeddingProvider and ChatProvider have deterministic fake adapters and real OpenAI HTTPS adapters. Production adapter requests are transport-mocked in tests; live paid provider validation is an OPERATIONAL REQUIREMENT. Embeddings are batched with input count/token constraints. Transient status/transport failures enter job retry; invalid requests/responses do not loop forever. Provider credentials are SecretStr environment values, never records/DTOs/browser config.

1536-dimensional pgvector embeddings carry provider/model/dimensions and confidential derived data. PostgreSQL validates both metadata dimension and actual vector width. An HNSW cosine index and lexical GIN index exist. Retrieval currently uses exact ranking over a materialized authorized subset (ADR 011); no claim is made that the strict query uses ANN acceleration.

## Retrieval and ACL

POST `/api/v1/knowledge/search` is independently testable. Inputs are query, optional bounded top_k and document-ID filters. IDs only restrict already authorized rows. The shared document ACL uses live active membership, actual admin role, visibility, ownership, explicit user grant or granted team membership/active employee profile. Candidate SQL joins chunk → exact version → logical document, filters organization/ACL/ACTIVE/current/READY, THEN computes similarity/lexical ranks. Unauthorized chunks never enter ranking, provider context, response metadata or secondary storage reads.

Only current READY knowledge is searched. Processing/FAILED current sources do not fall back to old knowledge; archiving excludes immediately. Historical artifacts remain for provenance, but historical retrieval is DEFERRED. Responses expose organization/document/version/chunk IDs, title, version number, locator, excerpt and fusion score; never embedding values.

## Ask AI and citations

POST `/api/v1/knowledge/ask` is stateless and read-only. Retrieval supplies bounded authorized evidence. Complete serialized prompt (including question/title/locator/system instructions) plus a framing reserve is token-bounded; per-chunk and answer limits are separate. Oversized entries are excluded, with no empty-context provider call. Both endpoints require authenticated active organization membership and session CSRF.

The system prompt treats documents, titles, locators and question as untrusted data and gives no tools/actions. Server labels S1…Sn map to exact evidence. Structured provider output returns answer and labels; unknown labels or uncited output cause an explicit insufficient-evidence response. Actual citation objects are built only by the server. The server rechecks current access/state after generation and invalidates a response if any supplied evidence changed eligibility. Model correctness/semantic entailment and absolute prompt-injection immunity are KNOWN LIMITATIONS; server authorization and provenance are independently enforced and tested.

## Configuration and confidentiality

`AI_ENABLED` defaults false; local Compose explicitly enables fake providers. Hardened enabled AI requires real providers, explicit supported embedding model, production chat model and secret credentials. Configure poll interval, lease, attempts/backoff, extraction bounds, tokenizer/chunk sizes, embedding batch/model/dimensions, retrieval/top_k/context/per-chunk and answer budgets, chat model/tokenizer and timeout. Containers checksum/cache cl100k_base and o200k_base data at build time; fake runtime does not download resources or spend credits. Source setup with uv may need an initial official tokenizer-cache download.

Source, blocks, chunks, embeddings, questions and answers are confidential. Structured worker logs/audits contain safe job/tenant/version IDs, attempts/stages/counts/timings/model/usage only. Generic request failures log category/request ID without exception payload; SQL hides bound parameters. No raw question/answer analytics or billing system exists. The selected AI provider's retention, training, region, contractual handling and allowed tenant data are OPERATIONAL REQUIREMENTS.

## Evidence and acceptance

Parser/chunker/job unit suites use only committed generated fixtures. PostgreSQL tests prove extension/type/index creation, composite lineage/dimension constraints, live ACL-filtered vector/lexical retrieval, current/archived state, unknown citations, malicious source containment, generation-time eligibility change, competing claimers, SKIP LOCKED, expired lease fencing and concurrent retry. MinIO/Redis/M1 security gates remain separate. CI has api-core, worker, vector-retrieval-integration, storage, Redis, web, containers and security jobs. Exact executed results and remote closure are recorded in `docs/review/M2_VERIFICATION.md`.

Manual local flow: `docker compose up --build`; register/create workspace, upload `apps/api/tests/fixtures/ingestion/policies.pdf`, observe Uploaded/Processing/Ready, ask about the support desk and inspect page-3 provenance. Fake chat explicitly prefixes its extractive preview. Upload a changed version; search excludes the source until that version is ready. Use a second member/restricted grants and revoke access. Upload synthetic malformed PDF and inspect safe failure/retry. UI polling is three seconds, so fast jobs may skip a visibly rendered Processing frame.

DEFERRED: OCR, complex PDF layout, historical search, admin re-embedding, connectors, learning/onboarding, signals/agents, autonomous tools, long-term memory, billing, external queue/search platforms and generic DAG engines.
