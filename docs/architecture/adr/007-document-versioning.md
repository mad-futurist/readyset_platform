# ADR 007: Application-immutable source versions

## Context
Future parsing, embeddings, and AI citations must be reproducible after a file changes.

## Decision
`Document` is mutable logical metadata. Every source upload creates a new `DocumentVersion` with checksum and unique storage identity. No update API changes version identity, storage keys are not reused, bytes are not overwritten, and the current pointer changes separately after successful storage and database work. This is application immutability; M1 does not add a database trigger that blocks privileged SQL updates.

## Alternatives considered
One mutable file row loses provenance. Putting extracted text on `Document` couples source and index lifecycle.

## Consequences
Storage grows and retention needs future policy, but M2 artifacts and citations can reference exact sources.

## Revisit when
Legal retention/erasure, deduplication, or version pruning requirements are defined.
