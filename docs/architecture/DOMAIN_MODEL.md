# Domain model

## Identity is not employment

`User` is a product-wide human account. It holds stable account presentation data, not an organization's HR truth. A person can authenticate before joining an organization, belong to two organizations, and retain an account after leaving one.

`AuthIdentity` is evidence that an external or local authentication method maps to a user. `(provider, provider_subject)` is authoritative and unique. Google fields never appear on `User`. Password hashes are stored in a password credential attached to an email/password identity. A password identity grants access only after that exact identity is email-verified. A Google identity requires a provider-verified email and may link to the one existing user with the same normalized primary email; unverified claims, conflicting subjects, disabled users, and ambiguous links fail closed. Linking Google never verifies or enables an unverified password identity.

`SessionRecord` belongs to both a user and the exact authentication identity that created it. Password login creates a password-bound session and Google login creates a Google-bound session. Every authenticated request revalidates the user and identity; legacy sessions without trustworthy provenance are deleted by the hardening migration.

`OrganizationMembership` is the authorization join between user and tenant. OWNER/ADMIN/MANAGER/MEMBER are deliberately small organization roles. They are translated to capabilities in one policy module.

`EmployeeProfile` is organization-owned person/employment data. It may optionally link to a current `User`; an invited or pre-hire person can exist first. Team and manager relationships use employee profiles within the same organization. A revoked membership does not delete the employee record.

## Onboarding is not identity

"Newcomer" is not a user class or role. A future `OnboardingEnrollment` will reference an `EmployeeProfile`, its plan, dates, mentor assignments, and lifecycle. The profile survives completion. Mentor is likewise a relationship scoped to an enrollment or plan, not a permanent account role.

## Documents and files

`Document` is the logical, organization-owned knowledge item: title, classification, owner, visibility, lifecycle, and current version pointer.

`DocumentVersion` is an immutable uploaded source artifact: storage key, safe display filename, content type, size, checksum, creator, version number, and ingestion state. New bytes always create a new version. Future extraction, chunks, embeddings, and citations attach to the version that produced them, making AI answers reproducible.

The file is not extracted text, a chunk, or an indexed representation. These later artifacts have independent lifecycles and can be regenerated without changing source history.

## Document access

Organization-visible documents are readable by every active member. Restricted documents are readable by their owner, organization OWNER/ADMIN, explicitly granted users, or members of explicitly granted teams. Manage access and version upload require a document management capability plus ownership/admin semantics defined by policy. Grants use relational user/team tables rather than opaque JSON.

Future connector ACL mappings can add external principals and source bindings without changing M1 grants. Query-time retrieval must reuse the same effective access predicate.
