# Security invariants

This is a traceability spec. “Enforced by” names code/schema boundaries; “Verified by” names automated evidence. Operational requirements remain deployment responsibilities.

## Session identity binding

**Invariant:** A current user comes only from an unexpired, non-revoked opaque session bound to the exact existing verified `AuthIdentity` and active `User` that created it.

**Enforced by:** `SessionRecord.auth_identity_id`; `security.create_session`; `dependencies.get_current_user`; hashed cookie tokens; password reset revocation.

**Verified by:** `test_register_login_logout_and_password_is_not_returned`, `test_password_reset_revokes_sessions_and_all_reset_tokens`, Google identity tests.

**Operational dependency:** TLS, Secure cookies, secret-safe logs, PostgreSQL availability.

## Unverified password identity and Google reclaim

**Invariant:** An unverified password identity never authenticates. When verified Google proves ownership of the same normalized email, every outstanding verification token is consumed and the unverified password identity is deleted; its credential and impossible sessions cascade. The password is never silently verified. A legitimately verified password identity survives Google linking.

**Enforced by:** password login verification predicate; `google_callback` row lock/reclaim transaction; password-credential and session cascade FKs; resend lookup requires an extant unverified password identity.

**Verified by:** `test_unverified_password_prehijack_does_not_survive_google_link` asserts token, identity and credential state; `test_verified_password_user_links_google_and_repeat_login_is_idempotent` asserts dual identity.

**Operational dependency:** correct Google issuer/client validation and exact callback configuration.

## OAuth request and provider integrity

**Invariant:** Google login requires provider-verified email, stable provider subject, PKCE S256, nonce, single-use state, and a matching browser-binding cookie. Replay, missing binding, conflicting subject/email, disabled user, and provider failure fail closed.

**Enforced by:** `OAuthLoginState`, hashed state/binding, callback transaction, Google token verification, unique `(provider, provider_subject)`.

**Verified by:** `test_oauth_binding_replay_unverified_claims_and_subject_conflict_fail_closed`, cookie/provider/race/disabled-user tests.

**Operational dependency:** Google availability and correct HTTPS redirect registration.

## Tenant isolation

**Invariant:** Organization membership establishes authority. Tenant resources are selected with organization predicates; caller UUIDs never confer access. Foreign identifiers fail as absent before storage access.

**Enforced by:** `get_organization_context`, `DocumentRepository`, organization-scoped routes, composite tenant FKs, capability policy.

**Verified by:** cross-tenant document/version, people/team, spoofed-ID, revoked-membership, and PostgreSQL integrity tests.

**Operational dependency:** runtime DB credentials limited to the application schema. PostgreSQL RLS is DEFERRED.

## Document ACL

**Invariant:** Restricted reads require owner/admin, an active explicitly granted user, or active team membership plus a team grant. The same predicate protects metadata, history and download; management is checked separately.

**Enforced by:** `document_access_predicate`, `DocumentRepository`, `can_manage_document`, membership-backed user grant FK.

**Verified by:** `test_restricted_document_requires_grant_and_team_grant_works`, cross-tenant and unauthorized-storage tests.

**Operational dependency:** future retrieval/RAG must call the same policy boundary; it is not implemented in M1.

## Storage access and source identity

**Invariant:** The browser never receives storage credentials. Keys are server-generated and tenant/document/version scoped. New bytes create a new key and row; no update endpoint rewrites a source. Runtime errors are translated and bucket creation is disabled in hardened environments.

**Enforced by:** `S3ObjectStorage`, document upload/download routes, deterministic key format, configuration validation.

**Verified by:** memory-storage route tests, unauthorized-storage test, MinIO-marked lifecycle/missing-object test, compensation test.

**Operational dependency:** private pre-created bucket, least-privilege IAM/workload identity, TLS, bucket or configured SSE/KMS encryption. Source identity is application-immutable, not DB-trigger-immutable.

## Upload content validation

**Invariant:** A browser MIME or filename never establishes type. Accepted content must match supported PDF structure, DOCX ZIP entries, or sane UTF-8 text and its declared MIME.

**Enforced by:** `_stage_upload` and `file_validation.validate_content` before scanner, storage, or database writes; bounded upload size and SHA-256.

**Verified by:** valid/fake PDF, valid/arbitrary-ZIP DOCX, text/binary and MIME mismatch cases in `test_upload_validation`.

**Operational dependency:** edge body limits must not exceed application policy unexpectedly.

## Malware scanning

**Invariant:** In hardened environments with uploads enabled, a real scanner is configured. Only CLEAN staged content reaches object storage. Infected or unavailable scans fail closed without a usable version or source object.

**Enforced by:** `FileSecurityScanner`, `ClamAVFileSecurityScanner`, upload ordering, hardened `Settings` validation, `/readyz`.

**Verified by:** `test_malware_scan_fails_closed_before_storage` and hardened configuration tests.

**Operational dependency:** maintained, isolated clamd service and signature updates. No-op is allowed only by non-hardened configuration.

## Rate limiting

**Invariant:** Hardened deployments use the shared Redis implementation. Authentication is bucketed by hashed direct-peer address and, where available, hashed normalized email. Uploads are bucketed by authenticated user, organization and address. Arbitrary forwarding headers are ignored.

**Enforced by:** `RateLimiter` port, atomic Redis Lua increment/expiry, route checks, hardened configuration.

**Verified by:** memory allow/block/scope test, Redis-marked shared integration test, configuration tests.

**Operational dependency:** available Redis and trusted proxy/peer normalization. Rate limits are abuse controls, not an authorization boundary.

## Production configuration

**Invariant:** Unknown environments and unsafe staging/production combinations fail validation before serving traffic; development tokens never appear in hardened environments.

**Enforced by:** typed `Environment` and `Settings.validate_deployment`; docs disabled in hardened environments; non-root Dockerfiles; separate migration command.

**Verified by:** parameterized hardened configuration tests, image-build CI definition, contract/build gates.

**Operational dependency:** secret manager, provider-specific TLS/network/IAM validation, deployment rehearsal.

## Tokens, CSRF and invitations

**Invariant:** Raw session, OAuth, verification, reset and invitation tokens are not persisted or logged. Mutations require session-bound CSRF plus allowed Origin. Invitation reissue rotates the token; revocation and acceptance invalidate it.

**Enforced by:** SHA-256 token hashes, scoped cookies, `require_csrf`, invitation lifecycle transaction.

**Verified by:** auth/invitation/CSRF tests and secret-scan CI definition.

**Operational dependency:** logs and tracing must not capture bodies, cookies or query strings containing callbacks/tokens.

## Relational integrity

**Invariant:** Current version belongs to the same document; parent locking serializes version allocation; at most one active owner exists; tenant principals use membership-backed FKs where appropriate; the user-grant membership FK cascades consistently in model and migration.

**Enforced by:** composite FK/unique constraints, `SELECT ... FOR UPDATE`, PostgreSQL partial unique index, Alembic migrations.

**Verified by:** `test_current_version_must_belong_to_same_document`, `test_parent_lock_serializes_concurrent_version_numbers`, `test_database_allows_only_one_active_owner`, `alembic check`.

**Operational dependency:** PostgreSQL; SQLite tests are not evidence for these semantics.

## Audit truth

**Invariant:** No public API mutates or deletes audit rows and application writes go through `record_audit`. Records are append-oriented by application convention.

**Enforced by:** route surface and audit helper.

**Verified by:** security-event assertions in auth/document/organization tests.

**Operational dependency:** privileged database and migration roles can still modify rows; access control, retention and external log integrity remain operational controls.
