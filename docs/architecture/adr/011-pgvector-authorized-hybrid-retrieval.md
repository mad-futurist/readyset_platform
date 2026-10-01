# ADR 011: PostgreSQL vectors and authorized hybrid retrieval

Status: IMPLEMENTED; real PostgreSQL/pgvector security tests TESTED.

## Decision

Keep embeddings in PostgreSQL using a 1536-dimensional pgvector column, a composite tenant/chunk FK, dimension check, chunk/provider/model uniqueness, cosine HNSW index and a lexical GIN index. A release migration installs `vector` when permitted; otherwise the operator pre-provisions it. No API replica installs extensions or migrates.

The retrieval query materializes only tenant-scoped, active, current READY evidence selected through the existing live document ACL. Compute exact cosine distances and simple-language full-text ranks AFTER that SQL authorization boundary. Retrieve at most three times top_k from each strategy and apply deterministic reciprocal-rank fusion (constant 60). Embeddings never leave the database in retrieval results. Only bounded authorized candidates enter Python/context.

## Consequences

This query intentionally prefers exact authorized-subset correctness over global approximate candidate selection. The schema's HNSW/GIN indexes are available, but the materialized ranking path does not currently exploit them; performance is a KNOWN LIMITATION at large authorized corpora, not a claim of index-accelerated retrieval. Tune only after measured workloads and retain authorization-before-ranking. PostgreSQL simple full-text configuration supports token matching without choosing an English-only stemmer. Learned reranking and external search stores are deferred.

Changing embedding dimensions requires an additive schema decision; current configuration fails closed unless dimensions are 1536. Selecting a different provider/model excludes old embeddings until re-ingestion; no automatic cross-model similarity or re-embedding administration exists.

Source: [pgvector exact search, index and filter semantics](https://github.com/pgvector/pgvector).
