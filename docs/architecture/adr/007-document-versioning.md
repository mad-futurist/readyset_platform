# ADR 007: Immutable source versions

## Context
Future parsing, embeddings, and AI citations must be reproducible after a file changes.

## Decision
`Document` is mutable logical metadata. Every binary upload creates an immutable `DocumentVersion` with checksum and storage identity. A current-version pointer changes only after a successful upload transaction. Versions are not overwritten.

## Alternatives considered
One mutable file row loses provenance. Putting extracted text on `Document` couples source and index lifecycle.

## Consequences
Storage grows and retention needs future policy, but M2 artifacts and citations can reference exact sources.

## Revisit when
Legal retention/erasure, deduplication, or version pruning requirements are defined.
