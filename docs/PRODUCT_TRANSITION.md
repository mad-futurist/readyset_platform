# Product transition ledger

This file was absent at M2 planning time. An untracked historical transition document was also found at `docs/transitions/PRODUCT_TRANSITION.md` during verification and was left untouched. The preserved M1 concept migration map is `docs/research/DEMO_ANALYSIS.md`; this ledger records subsequent production behavior without rewriting that history. No demo/reference implementation is imported.

| Prototype concept | M1 decision (historical) | M2 production status |
|---|---|---|
| Logical documents/source bytes | Redesign | TESTED: tenant-scoped Documents and application-immutable private DocumentVersions |
| Document chunks / embeddings | DEFERRED | IMPLEMENTED and TESTED: structured extraction, exact version provenance, deterministic token-aware chunks, provider-neutral embeddings and PostgreSQL/pgvector |
| Ask AI | DEFERRED | IMPLEMENTED and TESTED with fake/transport-mocked providers: stateless ACL-safe retrieval and server-mapped citations; live provider deployment is an OPERATIONAL REQUIREMENT |
| Demo identity/persona authority | Remove | Preserved M1 session/identity/membership guarantees |
| Courses/onboarding/learning/tasks | DEFERRED | DEFERRED M3+; no entities added |
| Agents/signals/connectors/memory | DEFERRED | DEFERRED M3+; Ask AI has no actions/tools |

M2 closure requires the verification ledger's final green remote CI record. Provider/vendor approval remains operational.
