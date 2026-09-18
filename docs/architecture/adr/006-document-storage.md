# ADR 006: S3-compatible storage with API-proxied M1 transfer

## Context
Raw enterprise files must not live in PostgreSQL or expose storage credentials. Direct signed transfers scale better, while M1 must keep authorization and lifecycle coherent.

## Decision
Define an object-storage port implemented by S3/MinIO and an in-memory test store. Generate organization/document/version-scoped non-guessable keys. M1 stages bounded uploads, validates actual content, synchronously scans them, and only then writes to storage before committing database state. Authorized downloads are proxied through the API. Hardened runtimes only check a pre-created bucket; explicit auto-creation is local/test behavior. Ambient workload identity is supported, and bucket-enforced encryption or configured AES256/KMS encryption is required operationally.

## Alternatives considered
Presigned PUT/GET reduces API bandwidth but needs pending-upload records, completion verification, CORS, abandoned-object cleanup, checksum semantics, and careful expiry. Database blobs are rejected.

## Consequences
The secure vertical slice is simpler and every transfer shares policy enforcement, at the cost of API bandwidth. Uploads are size-limited. If the database fails after object write, the API attempts a compensating delete, logs cleanup failure, and preserves the original exception. Deterministic keys make later orphan reconciliation possible; no cleanup worker exists in M1.

## Revisit when
File size/throughput requires direct transfer. Add short-lived method/key-bound URLs and a two-phase completion endpoint without changing document/version tables.
