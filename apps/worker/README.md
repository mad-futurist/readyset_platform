# ReadySet worker

M1 intentionally has no asynchronous runtime. M2 will place version-scoped parsing, extraction, chunking, embedding, and indexing consumers here. Jobs will reference `organization_id` and `document_version_id`, be idempotent, and update ingestion state without accepting browser identity fields.
