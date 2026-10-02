# ADR 011: PostgreSQL vectors and authorized hybrid retrieval

Status: IMPLEMENTED; real PostgreSQL/pgvector security tests TESTED.

## Decision

Keep embeddings in PostgreSQL using a 1536-dimensional pgvector column, a composite tenant/chunk FK, dimension check, chunk/provider/model uniqueness, cosine HNSW index and a lexical GIN index. A release migration installs `vector` when permitted; otherwise the operator pre-provisions it. No API replica installs extensions or migrates.

The retrieval query materializes only tenant-scoped, active, current READY evidence selected through the existing live document ACL. Compute exact cosine distances and full-text ranks AFTER that SQL authorization boundary. M2 used simple-language `plainto_tsquery`; the subsequent M2.1 draft variant uses English literal alternatives as described below. Retrieve at most three times top_k from each strategy and apply deterministic reciprocal-rank fusion (constant 60). Embeddings never leave the database in retrieval results. Only bounded authorized candidates enter Python/context.

## Consequences

This query intentionally prefers exact authorized-subset correctness over global approximate candidate selection. The schema's HNSW/GIN indexes are available, but the materialized ranking path does not currently exploit them; performance is a KNOWN LIMITATION at large authorized corpora, not a claim of index-accelerated retrieval. Tune only after measured workloads and retain authorization-before-ranking. M2's simple full-text configuration supported token matching without an English-only stemmer; the M2.1 candidate explicitly accepts English bias for its English frozen corpus. Learned reranking and external search stores are deferred.

Changing embedding dimensions requires an additive schema decision; current configuration fails closed unless dimensions are 1536. Selecting a different provider/model excludes old embeddings until re-ingestion; no automatic cross-model similarity or re-embedding administration exists.

Source: [pgvector exact search, index and filter semantics](https://github.com/pgvector/pgvector).

## Subsequent M2.1 candidate (2026-10-02)

IMPLEMENTED in the draft: take at most 64 literal query terms, retain quoted phrases, quote operator-like user input and OR-combine alternatives for `websearch_to_tsquery("english", ...)`. PostgreSQL handles stop words and stemming; rank with `ts_rank_cd(..., 32)` and deterministic chunk-UUID ties. The original query remains unchanged for semantic embeddings and chat. No generated expansion, new model, weighting/depth search, stored representation change or migration is introduced. The existing simple-language GIN index is unchanged and not claimed to accelerate this query.

TESTED: real PostgreSQL tests cover stop words, stemming, phrase positions and the unchanged authorization-before-ranking boundary. Retrieval-only screening compared structural-prefix, lexical and combined candidates, selecting lexical only. Experimental structural-prefix vectors were not written into production derived rows; their distinct identity is recorded with the offline experiment. No old/new embedding representation can be silently mixed because production embedding input remains exactly `chunk.text`.

TESTED disposition: [actual production API comparison](../../evaluation/m2_1/M2_1_COMPARISON.md) has Hit@5 50/52 → 50/52, PDF 13/15 → 14/15 and NIST 3/5 → 4/5, but a new Q016 top-eight miss and worse warehouse-owner ranking. The favorable offline estimate was not reproduced fully. English stemming, broad OR competition and fresh-ID ties are tradeoffs; the precise offline/production difference is not proven. The concurrent passage-selection generation candidate also loses completeness/scope. Overall verdict **NOT READY — GROUNDING/RETRIEVAL REGRESSION**; neither change is automatically accepted, and the original M2 evidence remains immutable. Evaluate independent retrieval value before adopting a further answer contract.
