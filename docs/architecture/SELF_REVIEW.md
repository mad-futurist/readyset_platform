# Architecture self-review

| Question | Result |
|---|---|
| Can one user belong to two organizations? | Yes; membership uniqueness is per organization/user and organization selection is verified per request. |
| Can the same Google account map safely? | Yes; unique `(google, sub)` is authoritative, and repeat login reuses that identity. |
| Can password and Google represent one person? | Yes. Verified Google normalized email may attach to an active user. It transactionally removes a matching unverified password identity/credential and consumes old verification tokens; a verified password identity survives. Ambiguous, conflicting, unverified, disabled, and race cases fail closed. |
| Can registration authenticate before email verification? | No. Registration creates the account/identity/token and sends verification, but emits no session. Password login requires that exact password identity to be verified. |
| Can an old session change authentication meaning? | No. Sessions store `auth_identity_id` and each request revalidates that identity and user. The corrective migration deletes legacy sessions rather than guessing provenance. |
| Is OAuth state bound to the browser? | Yes. The callback requires both single-use server state and the matching short-lived HttpOnly callback-path cookie, in addition to PKCE and nonce. |
| What if email changes? | Provider subject remains stable. Primary email change requires verification and collision checks; identities retain provider email as observed metadata. |
| What if membership is revoked? | Context resolution checks active status every request; no tenant query or download is allowed. Sessions may remain valid for other organizations. |
| Can Org A infer Org B resources? | Scoped lookup returns 404 without title, status, size, filename, grant, or timing-dependent storage operation. |
| Can a signed URL cross tenants? | M1 emits none. Future signing accepts only a server-loaded authorized version/key. |
| Are keys scoped? | Yes, generated from organization/document/version UUIDs, never from filenames. |
| Can admins access restricted docs? | OWNER/ADMIN can; this is explicit and auditable. Revisit if customers require administrator-blind vaults. |
| Does OWNER imply all permissions? | Yes for M1. Only the current owner can atomically transfer ownership to an active member; the old owner becomes ADMIN. Ordinary role/revoke endpoints cannot create or remove OWNER, and a partial unique index prevents two active owners. |
| Team deleted? | Memberships and team grants cascade; documents remain and may become inaccessible except to owner/admin. |
| Employee leaves? | Membership is revoked; profile remains and can be marked inactive. Grants no longer confer access without active membership. |
| New document version? | The parent document is locked before version-number allocation. An application-immutable source row is added and its same-document composite FK permits it to become current; old versions remain authorized through the parent. |
| Can chunks attach to a version? | Yes; M2 adds a mandatory `document_version_id`. |
| Can AI answers be reproduced? | Future citations record version and chunk IDs; source versions are retained. |
| Can connector ACLs map later? | Yes; external source/principal mappings can coexist with concrete M1 grants and compile into the same predicate. |
| Can onboarding reference employees? | Yes; future enrollment points to organization-owned `EmployeeProfile`, not `User`. |
| Can enterprise SSO be added? | Yes; `AuthIdentity` adds provider/subject records without replacing users or memberships. |

Corrections made during review include tracked generated contracts; identity-bound sessions and browser-bound OAuth; explicit Google reclaim; synchronous email delivery status; content-derived file validation and mandatory hardened malware scanning; Redis rate limiting; typed private storage; JSONB metadata on PostgreSQL; composite tenant integrity; atomic ownership/version behavior; dependency-aware readiness; non-root locked images with a separate migration job; and proxied storage access. Version source identity is application-immutable. Audit is append-oriented through APIs, not protected from privileged database roles.
