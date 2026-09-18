# Reference repository analysis

All repositories below were used only to study architecture. No source code was copied into ReadySet.

## Twenty

**Inspected:** `WorkspaceAuthContext`, workspace auth middleware/guard, membership DTOs, permission resolution, workspace repository/query paths, and row-level permission application.

**Useful patterns:** authentication produces a request-scoped context containing the actor, workspace, membership, and role; request guards reject workspace-agnostic access; query infrastructure applies workspace and resource filters centrally rather than relying on UI behavior.

**Rejected for M1:** dynamic metadata, generated per-workspace schemas, CRM objects, generic query runners, cached permission graphs, and arbitrary row-level permission rule engines. ReadySet has a fixed schema and four roles.

**License:** the principal server is AGPLv3 with additional terms and some enterprise-licensed files; selected packages are MIT. We reuse concepts only and independently implement them.

**ReadySet decision:** resolve `OrganizationContext` from an authenticated session plus an active membership, require it at the route boundary, and require organization-scoped repositories. Use explicit capability policies and document ACL predicates.

## Onyx

**Inspected:** non-`ee/` document access models and query-time ACLs, user-file/source separation, connector/index-attempt concepts, and Celery worker boundaries. Enterprise permission synchronization was noted only at a high level and not used.

**Useful patterns:** fail closed when permission state is absent; project a user's effective ACL into retrieval queries; keep browser affordance permissions non-authoritative; distinguish uploaded/source files, logical/indexed documents, connectors, and indexing attempts; perform heavy ingestion outside synchronous HTTP requests.

**Rejected for M1:** search-engine ACL encoding, connector credential pairs, document sets, Celery topology, Vespa/OpenSearch integration, connector permission synchronization, and enterprise-only group hierarchy logic.

**License:** content outside `ee/` is MIT; `ee/` is under the Onyx Enterprise License. No code is reused. Enterprise code was not inspected beyond filenames/high-level concepts, per policy.

**ReadySet decision:** use relational user/team grants as the authoritative M1 ACL, enforce the same predicate for metadata and binary access, and reserve version-scoped ingestion records for M2.

## RAGFlow

**Inspected:** file/document association, tenant-scoped file records, object-storage locations, document parsing status/progress, and task/retry separation.

**Useful patterns:** binaries and metadata have different lifecycles; parsing state belongs to a processing lifecycle; asynchronous tasks can be retried and should attach to a stable source/version; storage operations carry tenant context.

**Rejected for M1:** parser configuration matrices, knowledge-base coupling, chunk counters, retrieval stores, pipelines, and current task orchestration.

**License:** Apache-2.0. Concepts only were used; ReadySet's implementation is independent.

**ReadySet decision:** `DocumentVersion` is the immutable ingestion unit. M1 records upload state and leaves parsing/chunking/indexing for a later worker.

## Plane

**Inspected:** workspace, active membership/invitation models, and workspace permission classes.

**Useful patterns:** membership is explicit and can be revoked; list querysets and mutation permissions must both be scoped; invitations are distinct from memberships.

**Rejected for M1:** project/task hierarchy and Plane's numeric role mapping.

**License:** AGPLv3. Architectural observation only; no code is reused.

**ReadySet decision:** active organization membership is checked on every request and role names are mapped centrally to capabilities.

## Open edX

**Inspected:** repository boundaries and the separation implied between platform users, organizations/content ownership, and learning applications.

**Useful pattern:** learning content and enrollment are separate concerns from the base identity account.

**Rejected/deferred:** LMS course structures, modulestore/content systems, enrollment machinery, and plugin architecture.

**License:** AGPLv3. No code is reused.

**ReadySet decision:** M1 does not place learning or onboarding state on `User`; future LMS/onboarding modules attach through organization-owned employee profiles.

## Authentication option research (September 2026)

Primary vendor documentation was compared for WorkOS AuthKit, Clerk Organizations, and Auth0 Organizations. All support password/social authentication and organization-oriented flows; WorkOS is particularly aligned with future enterprise SSO and directory sync. A managed provider reduces credential, recovery, MFA, and enterprise federation burden, but introduces external availability, billing, data-processing, and migration dependencies.

M1 implements a small provider-neutral authentication core inside ReadySet so the full system runs locally and the domain model remains authoritative. It uses Argon2id, opaque server-side sessions, one-time verification/reset tokens, and Google OIDC. This is a conscious M1 tradeoff, not a claim that in-house authentication is strategically superior. Revisit before public production or enterprise SSO; WorkOS AuthKit is the leading managed alternative.

Sources: [WorkOS users and organizations](https://workos.com/docs/authkit/users-organizations), [WorkOS AuthKit overview](https://workos.com/docs/authkit/overview), [Clerk organization configuration](https://clerk.com/docs/guides/organizations/configure), [Auth0 organization connections](https://auth0.com/docs/manage-users/organizations/configure-organizations/enable-connections), [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
