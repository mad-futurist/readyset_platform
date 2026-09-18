# Repository instructions

## Production isolation

`demo/` contains legacy demonstration material and `references/` contains external research material. Both trees are non-production inputs only.

Production code and packages under `apps/` and `packages/` must not import, copy, load, execute, serve, bundle, or otherwise depend on code, files, data, assets, configuration, or generated artifacts from `demo/` or `references/`. Production dependency manifests, build scripts, Docker images, tests, and runtime configuration must remain independent of both trees.

Ideas may be reimplemented in the production codebase, but no build-time or runtime link to either research tree may be introduced. Before completing packaging or dependency changes, verify source references, manifests, Docker copy rules, and built artifacts preserve this isolation.

## Engineering constitution

### Architecture and scope

- ReadySet is a modular monolith. `apps/api` owns domain rules and persistence; `apps/web` is an independently deployable client and never receives database or object-storage credentials.
- `apps/worker` is reserved for future asynchronous ingestion. Add queues, workflows, or microservices only for a demonstrated scaling or failure-isolation need.
- Keep `User`, authentication identity, `OrganizationMembership`, and `EmployeeProfile` distinct. Newcomer and mentor are relationships, not global authentication roles.
- Implement only the current milestone. Do not import future features from research inputs; prefer the smallest abstraction that enforces the required guarantee.

### Identity, tenancy, and authorization

- Membership establishes tenant authority. Every tenant-owned query is organization-scoped; client UUIDs never establish authority and cross-tenant lookup fails closed.
- Document ACLs are enforced server-side through reusable policy/query boundaries so future retrieval cannot bypass them.
- Unverified password identities never authenticate. Sessions remain bound to the exact valid `AuthIdentity` that created them. Verified OIDC email matching must never activate an unsafe password identity.
- OAuth uses state, PKCE, nonce, and browser binding. Raw session, recovery, verification, invitation, and provider tokens are never persisted or logged; hardened environments never expose development tokens.

### Data, files, and generated contracts

- Alembic is the only production schema-change path. Never rewrite a published migration; use additive corrective revisions and keep `alembic check` clean.
- Prefer foreign keys and unique constraints for relational invariants. Prove PostgreSQL-specific behavior with PostgreSQL tests; SQLite tests are not that proof.
- Raw files belong in private object storage under server-generated tenant-scoped keys. Validate actual content, require malware scanning in hardened environments, and never make unsafe/unscanned bytes normally downloadable.
- Document source identity is application-immutable: new bytes create a new `DocumentVersion`; future AI artifacts reference that exact version.
- FastAPI OpenAPI is authoritative. Reproduce and drift-check `apps/api/openapi.json` and generated TypeScript declarations; do not hand-maintain duplicate frontend DTOs.

### Completion and documentation

- Correct-looking code is not complete. Security/data-integrity changes require adversarial tests, PostgreSQL tests when database semantics matter, and clean frontend generation/typecheck/tests/build when contracts change.
- Never claim a test passed unless it ran. Classify documentation claims as IMPLEMENTED, TESTED, OPERATIONAL REQUIREMENT, DEFERRED, or KNOWN LIMITATION; resolve code/documentation disagreement before completion.

### Production runtime

- Hardened configuration fails closed. Production containers run non-root; API replicas do not run migrations; one release step does. Production dependencies use committed locks.
- Readiness checks required dependencies. Secrets never enter frontend bundles, logs, generated artifacts, or repository history.
