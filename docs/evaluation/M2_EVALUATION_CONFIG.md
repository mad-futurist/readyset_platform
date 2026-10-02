# Frozen M2 real-provider baseline

IMPLEMENTED: baseline source head `14717614cf9625865d69c4c6b76643248d5f2521`.
Frozen at 2026-10-02T09:39:36.551622+00:00; dataset SHA-256 `5acef85bd33f943145cf21c33a95e357fdf2d5666e86dadb416dba59f5ea6741`. Sixty questions, eight negatives (13.3%). Ground truth frozen before any ReadySet QA answers. No tuning or controlled variant planned.

| Setting | Baseline |
|---|---|
| Embedding provider/model/dimensions | OpenAI / text-embedding-3-small / 1536 |
| Chat provider/model | OpenAI / gpt-4.1-mini-2025-04-14 |
| Chunk target / max / overlap | 400 / 800 / 0 tokens |
| Embedding tokenizer / batch | cl100k_base / 32 |
| Retrieval top K / fusion | 8 / reciprocal rank fusion k=60, exact cosine + lexical, candidates 3×K each |
| Context / per chunk / answer | 6000 / 800 / 1000 tokens |
| Chat tokenizer | o200k_base |
| Chunker | structure-v1:cl100k_base:target=400:max=800:overlap=0 |
| Extractors | PDF pypdf (locked version); DOCX python-docx (locked version); markdown-lines-v1; utf8-lines-v1; exact runtime identities recorded per artifact |
| Generation | Production adapter defaults; no temperature/seed override, snapshot model; responses remain stochastic |

IMPLEMENTED: isolated PostgreSQL 17 / pgvector 0.8.2, private local MinIO bucket `readyset-evaluation`, synthetic test environment. API and real independent worker processes use locked backend dependencies. Alembic performs the only schema changes. No direct derived-state writes. Search/Ask use the whole authorized baseline corpus, without question-specific document filters. Extraction inspection reads committed artifacts after ingestion, not a replacement pipeline.

Measurement only: an OpenAIClient subclass calls the unchanged production post method and records request kind, model, timing and numeric usage. API context variables attribute observations to synthetic request IDs. A retriever subclass times the unchanged superclass. No prompts, adapter payloads, chunking, rankings or provider responses are altered. Worker gate used only for replacement scenarios holds a real embedding call before sending while a leased job is PROCESSING; baseline timing excludes gated tests.

Provider contract: Chat Completions, strict JSON schema, max_completion_tokens, finish_reason=stop, refusal rejection. The selected snapshot supports these features. store=false is already set by ReadySet. No tool declarations/actions. Embedding sends chunk text or question text; generation sends question and authorized excerpts with title/version/locator. No real enterprise/user content. store=false does not assert zero retention or a contractual privacy guarantee.

Pricing checked 2026-10-02: embedding $0.02/M input tokens; chat $0.40/M input, $0.10/M cached input, $1.60/M output. Actual cached input is observed; use these rates only in evaluation artifacts. USD, no currency conversion. Official sources: [embedding model](https://developers.openai.com/api/docs/models/text-embedding-3-small), [chat model and snapshot](https://developers.openai.com/api/docs/models/gpt-4.1-mini), [pricing](https://developers.openai.com/api/docs/pricing).

KNOWN LIMITATION: local sequential sample, no concurrency/load benchmark. Ten-document p95 is descriptive only. Retrieval duration minus query-provider round trip estimates combined SQL/policy/Python overhead; it is not a SQL execution-plan measurement. Public-source download duration was not instrumented when downloading originals, so it will be reported unavailable rather than fabricated. Worker object-store download is timed separately.

Scoring: manually review answer against frozen expected facts and original source; 0 materially wrong, 1 major errors, 2 important omissions, 3 correct/sufficient, 4 complete/contextualized. Evidence anchors plus exact-source/page assist ranking judgments; manual review resolves aliases and chunk splits without changing ground truth. Hit@K means any required evidence group; Recall@K means fraction of required groups (all anchors, exact source, page when specified) recovered. MRR uses first relevant rank; negatives excluded. Citation support must be material, not merely same-document. Coverage is supported verifiable claims / all such answer claims; abstentions have no claims and coverage is n/a. Separate provenance checks existing chunk, tenant, version, excerpt and source locator. Baseline source versions are never modified until all QA is captured.
