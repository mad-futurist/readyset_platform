# ADR 012: Current source must be READY for ordinary retrieval

Status: IMPLEMENTED and TESTED on PostgreSQL.

## Decision

Ordinary retrieval requires `Document.status = ACTIVE`, `Document.current_version_id = DocumentVersion.id` and `DocumentVersion.ingestion_status = READY`. Upload changes source current immediately after clean object/version/job commit. Until that exact source succeeds, the document is absent from search and Ask AI.

Older version artifacts remain attached to their immutable source for provenance and history, but are never silently substituted for a processing/failed current source. Archiving excludes evidence immediately. Citations identify the version used; the web can display/download that exact version after normal ACL verification. Post-generation authorization/current-state revalidation invalidates answers when access or current version changes during provider latency.

## Alternatives

An explicit current-ready pointer could preserve availability, but would require clear stale-source presentation and additional lifecycle rules. M2 chooses a smaller fail-closed model that avoids misleading current answers. Historical retrieval and an explicit stale-source product mode are deferred.
