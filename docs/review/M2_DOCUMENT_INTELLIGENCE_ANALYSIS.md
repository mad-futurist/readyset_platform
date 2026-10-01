# M2 document intelligence analysis

Status: pre-implementation design, 2026-10-01. M2 is not closed until the verification ledger records a fully green remote run.

## Inspected foundation

The M1 architecture/domain/database/security/status documents, ADRs 001–008, research analyses and M1 final hardening analysis were read before code changes. The requested `docs/PRODUCT_TRANSITION.md` is absent in this checkout; the migration map in `docs/research/DEMO_ANALYSIS.md` is the existing transition evidence and will be preserved with a new factual transition ledger. During verification an untracked historical transition at `docs/transitions/PRODUCT_TRANSITION.md` was read and left untouched.

`Document` owns the logical title, lifecycle, visibility and same-document composite current-version pointer. `DocumentVersion` already has PENDING_UPLOAD, UPLOADED, PROCESSING, READY and FAILED, tenant identity, checksum, size and immutable source key. Only upload states are currently used. Upload validates and scans before writing the private object and committing the row. The storage port has an eagerly opened, closable byte stream, so the worker can spool bounded bytes without loading the entire object into memory.

`document_access_predicate` is the shared relational boundary for owner/admin, organization visibility, user grants and team grants; request dependencies independently require an active membership. Retrieval will reuse that predicate and recheck active membership inside SQL, including services invoked outside routes. `apps/worker` contains only a README. PostgreSQL 17, SQLAlchemy, JSONB and additive Alembic migrations already underpin production; there is no vector extension or asynchronous queue.

Read-only inspection of the demo chunk model/RAG service shows logical-document chunks, synchronous provider coupling and unsafe TLS settings. These are rejected; no implementation is reused. Onyx's non-enterprise indexing models illustrate source-aware chunk descriptors and ACL projection. RAGFlow's task service separates parsing/task lifecycle but has Redis counters and a much larger runtime; M2 does not need this infrastructure. Research trees remain outside every production dependency and build context.

## Intended flow and entities

Clean source object → version + unique ingestion job in one DB transaction → worker lease → bounded spool and checksum verification → ordered extraction blocks → deterministic token-bounded chunks → batched embeddings → fenced atomic replacement of derived rows + READY + SUCCEEDED. No parsing/provider calls occur during upload.

Add tenant/version-scoped `IngestionJob`, `ExtractedArtifact`, `DocumentChunk` and tenant/chunk-scoped `ChunkEmbedding`. Composite FKs prove lineage; unique version/ordinal and chunk/provider/model identities prevent duplicates. Persist bounded normalized blocks as JSONB in one artifact per version, plus extractor/chunker identity, token count, embedding call count and timings. Source binaries remain only in object storage. Extraction has explicit block/text/page bounds; oversized output fails safely instead of expanding PostgreSQL indefinitely.

## Queue and failures

One job per version; PENDING → RUNNING → SUCCEEDED, RETRYABLE or FAILED. PostgreSQL `FOR UPDATE SKIP LOCKED` claims short transactions. Attempts have a fresh UUID lease owner, expiration and periodic renewal. Renew/finalize/fail require the same owner and an unexpired lease; stale workers cannot mutate outputs. Expired RUNNING jobs are reclaimed, including terminal exhaustion. Retryable storage/provider/database failures use capped exponential backoff; deterministic corrupt/unsupported/empty/oversized sources and invalid vectors fail terminally. Persist only fixed error categories/messages, never exception text or source content. Authorized retry locks the job and resets only FAILED; concurrent retry becomes a no-op. Crash expiry is the backstop for SIGTERM while shutdown stops new claims and finishes the current attempt.

## Extraction and chunking

Use maintained pypdf for digitally born PDF page text and python-docx for ordered paragraphs/tables; standard-library UTF-8 parsing handles Markdown/plain text. A narrow extractor returns headings, paragraphs, lists, tables and code with stable ordering and locators. PDF uses one-based pages (layout/heading inference and OCR are explicitly limited); DOCX uses paragraph/table/body indices and heading paths; Markdown/text use line ranges. Scanned PDFs without extractable text fail as unsupported empty extraction.

Use tiktoken cl100k_base for the selected text-embedding family, with a separate chat tokenizer configuration. Chunk within heading and source-location boundaries, accumulate paragraphs toward 400 tokens, enforce 800 max, split oversized blocks at Unicode-safe token boundaries, and use no implicit overlap. Store source span lists and exact split offsets; preserve heading paths. Reproducibility includes extractor/chunker versions, tokenizer and bounds.

## Embedding and retrieval

Provider-neutral embedding/chat ports have deterministic development/test implementations and an OpenAI HTTPS adapter. Explicit models, dimensions, batching, timeouts and credentials; hardened AI rejects fake providers and missing credentials. M2 starts with 1536-dimensional vectors, a checked fixed-width pgvector column and cosine HNSW index. Changing dimensions requires a reviewed additive migration. PostgreSQL extension installation belongs to the migration/provisioning role, never API startup.

Hybrid retrieval combines bounded semantic and PostgreSQL simple full-text candidates with deterministic reciprocal-rank fusion. Crucially, SQL materializes the organization/ACL/current-READY eligible rows before computing distance/ranks. Exact pgvector ranking over this authorized subset avoids global ANN candidate starvation and ensures unauthorized evidence never enters ranking/context. HNSW is provisioned for future measured optimization; this strict query intentionally does not rely on global approximate candidate ranking. PostgreSQL computes similarity; Python only fuses the two already-authorized bounded lists. No organization corpus is loaded into Python. SQLite fast tests exercise transports/state only and do not prove vectors/locks.

## Version semantics and Ask AI

Default retrieval requires active Document.current_version_id = READY version.id. A processing/failed new source removes the logical document from ordinary retrieval immediately; there is no automatic stale fallback. Historical artifacts remain for provenance, but historical search is deferred. Archiving immediately excludes the document.

Search returns organization/document/version/chunk identity, title, version, locator, excerpt and score, never vectors. Stateless read-only Ask retrieves the same authorized evidence, bounds both evidence and complete prompt tokens, and assigns S1…Sn server labels. Documents are untrusted data, never system instructions. The provider returns text plus labels; unknown labels/unsupported uncited output are rejected safely, citations are server mapped to request evidence. No evidence returns an explicit insufficient-knowledge response without generation. Revalidate evidence authorization/current state after generation to prevent a concurrent revocation/version switch from exposing a stale response.

## Confidentiality, verification and non-goals

Sources, extracted text, chunks, embeddings, questions and answers are enterprise-confidential. Logs/audits contain IDs/counts/models/stage timings and safe codes only. Ordinary exceptions must not log SQL parameters/provider content. Operational requirements include provider data-processing/retention/region approval, private storage, worker CPU/memory limits, pgvector provisioning, heartbeat supervision and real-provider acceptance. Tests use generated fixtures and fake providers only.

Verify parser/chunker determinism/Unicode, state/fencing/backoff, SQL composite/dimension integrity, real vector/FTS retrieval, hostile tenant/user/team/grant/revocation cases, current/archived semantics, two PostgreSQL claimers and atomic retry replacement. Preserve all M1 CI gates, regenerate contracts and verify web tests/build. Remote CI is required for closure.

Explicit non-goals: OCR/layout analysis, historical search, re-embedding administration, conversation memory, tools/actions, LMS/onboarding, agents/signals, connectors, billing, generic pipeline engines, external queues/vector stores and microservices.

## Primary library/provider sources

- [pypdf extraction and limitations](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)
- [python-docx ordered body content](https://python-docx.readthedocs.io/en/latest/api/document.html)
- [pgvector exact search, indexing and filtered queries](https://github.com/pgvector/pgvector)
- [OpenAI embeddings contract](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
- [OpenAI structured output contract](https://developers.openai.com/api/docs/guides/structured-outputs)
