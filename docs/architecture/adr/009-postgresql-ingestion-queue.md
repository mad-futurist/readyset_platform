# ADR 009: PostgreSQL ingestion jobs with leases

Status: IMPLEMENTED in M2.

## Decision

One unique job per immutable DocumentVersion is created in the upload transaction. Independently deployed workers import the backend domain package. Short `FOR UPDATE SKIP LOCKED` transactions claim PENDING/RETRYABLE or expired RUNNING jobs. Every attempt receives a fresh UUID lease owner and uses PostgreSQL wall-clock time, not transaction-start time, for renewal/finalization.

Renewals require an unexpired lease. Finalization locks and checks ownership, replaces derived rows, and atomically commits READY/SUCCEEDED. Expiry exhaustion becomes terminal rather than remaining RUNNING. Retryable provider/storage/DB errors have capped exponential backoff. Manual manager retry resets only terminal FAILED jobs, preserving the unique row.

## Consequences

At least once execution may cause redundant parsing/provider work after expiry, but a stale worker cannot publish outputs. Heartbeat renewal and fencing are required together. SIGTERM stops claiming and lets the current attempt finish; lease expiration recovers forced termination. Database-backed transactions remove any need for Redis queue, Celery, Kafka or Temporal in M2. These can be revisited after measured throughput or failure-isolation evidence.
