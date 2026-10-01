# ADR 010: Bounded structured extraction and token-aware chunks

Status: IMPLEMENTED; synthetic corpus TESTED. OCR/layout analysis DEFERRED.

## Decision

Use pypdf for page-scoped digitally born PDF text; python-docx for document-order body paragraphs/tables and heading styles; standard-library parsing for UTF-8 text/Markdown. Keep one narrow extraction port. Store ordered blocks and format-specific locators in a bounded JSONB artifact per version, alongside chunker/extractor identities and processing metrics. Source binaries remain private object-storage objects.

Use tiktoken cl100k_base for the supported text-embedding-3 family. Chunk within headings/page boundaries, group paragraphs toward 400 tokens, enforce 800 maximum, and split oversized blocks at whitespace or Unicode character boundaries. No implicit overlap. Persist split character offsets, contributing block spans, heading paths and a checksum. Chunk UUIDv5 identities include version, ordinal, content and chunker identity; they are deterministic and application-immutable within a completed ingestion.

## Alternatives and limitations

A generic parser framework, OCR and full AST would add operational weight without a second product use case. PDF text order depends on the source; headings/tables are not reconstructed semantically and image-only pages are not OCRed. DOCX body extraction excludes headers/footers, tracked revisions and image text. Line-oriented Markdown supports ATX headings and fenced code, with other syntax retained as textual paragraphs; it is not a complete CommonMark AST.

Character, block, page, ZIP-expansion and source-byte limits control ordinary growth; hostile PDF decompression still requires worker memory/CPU limits. Artifacts are bounded at 2 million text characters/20,000 blocks by default; larger sources require explicit configuration review. Docker caches official tokenizer assets with fixed SHA-256 checksums, so runtime tokenization needs no network download.

Sources: [pypdf extraction limitations](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), [python-docx document-order body traversal](https://python-docx.readthedocs.io/en/latest/api/document.html).
