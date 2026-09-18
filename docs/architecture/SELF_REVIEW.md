# Architecture self-review

| Question | Result |
|---|---|
| Can one user belong to two organizations? | Yes; membership uniqueness is per organization/user and organization selection is verified per request. |
| Can the same Google account map safely? | Yes; unique `(google, sub)` is authoritative. |
| Can password and Google represent one person? | Yes; verified normalized email may attach a new identity to the existing user. Ambiguous/unverified linking fails closed. |
| What if email changes? | Provider subject remains stable. Primary email change requires verification and collision checks; identities retain provider email as observed metadata. |
| What if membership is revoked? | Context resolution checks active status every request; no tenant query or download is allowed. Sessions may remain valid for other organizations. |
| Can Org A infer Org B resources? | Scoped lookup returns 404 without title, status, size, filename, grant, or timing-dependent storage operation. |
| Can a signed URL cross tenants? | M1 emits none. Future signing accepts only a server-loaded authorized version/key. |
| Are keys scoped? | Yes, generated from organization/document/version UUIDs, never from filenames. |
| Can admins access restricted docs? | OWNER/ADMIN can; this is explicit and auditable. Revisit if customers require administrator-blind vaults. |
| Does OWNER imply all permissions? | Yes for M1, including organization and document administration; ownership transfer must precede owner removal. |
| Team deleted? | Memberships and team grants cascade; documents remain and may become inaccessible except to owner/admin. |
| Employee leaves? | Membership is revoked; profile remains and can be marked inactive. Grants no longer confer access without active membership. |
| New document version? | Immutable version row is added; after successful storage/current-pointer update it becomes current. Old versions remain authorized through the parent document. |
| Can chunks attach to a version? | Yes; M2 adds a mandatory `document_version_id`. |
| Can AI answers be reproduced? | Future citations record version and chunk IDs; source versions are retained. |
| Can connector ACLs map later? | Yes; external source/principal mappings can coexist with concrete M1 grants and compile into the same predicate. |
| Can onboarding reference employees? | Yes; future enrollment points to organization-owned `EmployeeProfile`, not `User`. |
| Can enterprise SSO be added? | Yes; `AuthIdentity` adds provider/subject records without replacing users or memberships. |

Corrections made during review: organization IDs are duplicated on child/join tables with composite integrity constraints; membership status is checked per request instead of cached in session; document grants require an active membership; versions are immutable and archived documents retain their source history; M1 uses proxied storage access so authorization cannot be bypassed by stale signed URLs.
