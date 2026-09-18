# Security invariants

These are executable design constraints, not UI conventions.

1. The current user is derived only from a valid, unexpired, non-revoked opaque session whose token is stored only as a hash server-side. Each session is bound to the exact `AuthIdentity` that created it; the identity must still exist, belong to the same active user, use a supported provider, and a password identity must remain verified.
2. Organization context exists only after an active membership lookup. Revocation affects the next request, including requests carrying an old cookie.
3. Every tenant-owned query contains an organization predicate. Cross-tenant object IDs return no metadata and do not generate storage URLs or reads.
4. Capabilities are resolved centrally from membership role. Route handlers do not compare magic role strings.
5. OWNER and ADMIN can administer all documents in their organization, including restricted documents; MANAGER can create/manage documents it owns and people/teams as defined by policy; MEMBER has read/upload capabilities only as granted by policy.
6. Restricted document reads require owner/admin, explicit active-user grant, or active team membership plus team grant. The identical predicate protects metadata, version lists, download, and future retrieval.
7. Storage keys are generated server-side as `organizations/{org_uuid}/documents/{document_uuid}/versions/{version_uuid}/source`; filenames and client IDs never determine a key.
8. The browser never receives storage credentials. M1 proxies uploads/downloads after authorization. Any future presigned URL is short-lived, method-specific, bound to one generated key, and created only after the same authorization check.
9. Passwords use Argon2id through a maintained library. Plaintext passwords and reset/verification/invitation/session tokens are never persisted or logged.
10. Provider identity linking requires a stable unique `(provider, subject)`. Google linking requires a provider-verified email. Matching normalized email may attach Google to one active user, but never verifies an existing password identity; subject/email conflicts, disabled users, unverified claims, and uniqueness races fail closed.
11. Password registration creates no session. Verification and reset use random, hashed, expiring, single-use tokens. Reset consumes all outstanding reset tokens for the user, revokes every session, and records an audit event. Raw tokens are exposed only when explicitly enabled in development/test.
12. Google Authorization Code uses PKCE S256 and nonce. Each server-side single-use state also stores a hash of a random browser-binding cookie. The callback requires both; the HttpOnly, SameSite=Lax, short-lived, callback-path cookie is Secure in hardened environments and removed on success or terminal failure.
13. Invitations use random one-time hashed tokens, explicit expiry, normalized email binding, and organization/role set by an authorized inviter. Reissue rotates the token on the same pending row; revocation invalidates it.
14. Cookie-authenticated mutations require a matching CSRF token header/cookie and an allowed Origin. Session cookies are HttpOnly, Secure in staging/production, SameSite=Lax, host-only, and narrowly scoped.
15. Pydantic input schemas explicitly enumerate writable fields and reject explicit null for non-null fields. Actor IDs, storage keys, checksums, membership state, organization ownership, and audit actors are server assigned.
16. UUIDs reduce casual enumeration but are never treated as authorization. Cross-tenant results are indistinguishable from absent resources.
17. Uploads are streamed with a configured byte limit, allowed MIME allowlist, sanitized display filename, and server-computed SHA-256. Content-type claims are not a future malware guarantee; production requires malware/content inspection before broad rollout.
18. Audit records capture security-relevant success events and selected failures without secrets or full file contents. Application code cannot update/delete audit rows.
19. Staging/production accept only explicit hardened configuration: HTTPS public/callback/CORS URLs, Secure cookies, SMTP when password auth or invitations are enabled, non-local service credentials/endpoints, no development token exposure, and confirmation of a shared limiter. API docs are disabled.
20. Authentication and upload endpoints are rate-limit integration points. The local M1 implementation includes bounded in-process protection; hardened environments require a trusted shared limiter at the edge or Redis, represented by an explicit deployment assertion.
21. Database and object-storage service credentials are least privilege and distinct by environment. Backups and logs inherit tenant confidentiality requirements.

## Required adversarial coverage

Tests cover password/Google pre-hijacking, identity-bound sessions, OAuth browser binding/replay/provider failure/conflicts, disabled users, reset-token/session invalidation, owner transfer, invitation reissue/revocation, explicit-null PATCHes, foreign organization document/version UUIDs, spoofed organization/user IDs, revoked membership reuse, unauthorized downloads, restricted documents without grants, cross-tenant people/team operations, and role boundaries. PostgreSQL-marked tests exercise the same-document current-version FK, serialized version allocation, and the one-active-owner index in CI.
