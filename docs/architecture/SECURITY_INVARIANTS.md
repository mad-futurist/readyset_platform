# Security invariants

These are executable design constraints, not UI conventions.

1. The current user is derived only from a valid, unexpired, non-revoked opaque session whose token is stored only as a hash server-side.
2. Organization context exists only after an active membership lookup. Revocation affects the next request, including requests carrying an old cookie.
3. Every tenant-owned query contains an organization predicate. Cross-tenant object IDs return no metadata and do not generate storage URLs or reads.
4. Capabilities are resolved centrally from membership role. Route handlers do not compare magic role strings.
5. OWNER and ADMIN can administer all documents in their organization, including restricted documents; MANAGER can create/manage documents it owns and people/teams as defined by policy; MEMBER has read/upload capabilities only as granted by policy.
6. Restricted document reads require owner/admin, explicit active-user grant, or active team membership plus team grant. The identical predicate protects metadata, version lists, download, and future retrieval.
7. Storage keys are generated server-side as `organizations/{org_uuid}/documents/{document_uuid}/versions/{version_uuid}/source`; filenames and client IDs never determine a key.
8. The browser never receives storage credentials. M1 proxies uploads/downloads after authorization. Any future presigned URL is short-lived, method-specific, bound to one generated key, and created only after the same authorization check.
9. Passwords use Argon2id through a maintained library. Plaintext passwords and reset/verification/invitation/session tokens are never persisted or logged.
10. Provider identity linking requires a stable `(provider, subject)`. Email-based linking occurs only for provider-verified, normalized email. Email changes do not change provider subject.
11. Invitations use random one-time hashed tokens, explicit expiry, normalized email binding, and organization/role set by an authorized inviter.
12. Cookie-authenticated mutations require a matching CSRF token header/cookie and an allowed Origin. Session cookies are HttpOnly, Secure in production, SameSite=Lax, and narrowly scoped.
13. Pydantic input schemas explicitly enumerate writable fields. Actor IDs, storage keys, checksums, membership state, organization ownership, and audit actors are server assigned.
14. UUIDs reduce casual enumeration but are never treated as authorization. Cross-tenant results are indistinguishable from absent resources.
15. Uploads are streamed with a configured byte limit, allowed MIME allowlist, sanitized display filename, and server-computed SHA-256. Content-type claims are not a future malware guarantee; production requires malware/content inspection before broad rollout.
16. Audit records capture security-relevant success events and selected failures without secrets or full file contents. Application code cannot update/delete audit rows.
17. Secrets enter through environment/secret management. Debug mode and API docs are disabled or restricted in production. CORS uses an explicit origin list with credentials; wildcard credentialed CORS is forbidden.
18. Authentication and upload endpoints are rate-limit integration points. The local M1 implementation includes bounded in-process protection; production requires a shared limiter at the edge or Redis.
19. Database and object-storage service credentials are least privilege and distinct by environment. Backups and logs inherit tenant confidentiality requirements.

## Required adversarial coverage

Tests cover foreign organization document/document-version UUIDs, spoofed organization/user IDs, revoked membership reuse, unauthorized download generation/read, restricted documents without grants, cross-tenant people/team operations, and role capability boundaries.
