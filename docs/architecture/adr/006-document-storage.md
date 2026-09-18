# ADR 006: S3-compatible storage with API-proxied M1 transfer

## Context
Raw enterprise files must not live in PostgreSQL or expose storage credentials. Direct signed transfers scale better, while M1 must keep authorization and lifecycle coherent.

## Decision
Define an object-storage port implemented by S3/MinIO and an in-memory test store. Generate organization/document/version-scoped non-guessable keys. M1 streams bounded uploads and authorized downloads through the API.

## Alternatives considered
Presigned PUT/GET reduces API bandwidth but needs pending-upload records, completion verification, CORS, abandoned-object cleanup, checksum semantics, and careful expiry. Database blobs are rejected.

## Consequences
The secure vertical slice is simpler and every transfer shares policy enforcement, at the cost of API bandwidth. Uploads are size-limited.

## Revisit when
File size/throughput requires direct transfer. Add short-lived method/key-bound URLs and a two-phase completion endpoint without changing document/version tables.
