# ADR 003: Provider-neutral in-product authentication for M1

## Context
M1 requires email/password and Google OIDC, while future customers may require Entra ID, enterprise OIDC, SAML, MFA, and directory lifecycle. Current WorkOS AuthKit, Clerk, and Auth0 offerings can provide these capabilities. External credentials and a vendor decision are not available for a reproducible local milestone.

## Decision
Implement a deliberately narrow authentication core: `User`, extensible `AuthIdentity`, Argon2id password credential, shared-purpose one-time verification/reset tokens, identity-bound opaque hashed server-side sessions, and Google Authorization Code + PKCE + nonce plus a browser-binding cookie. Authorization and ReadySet memberships remain local regardless of authentication provider.

Registration does not authenticate. Password login requires that password identity's verification; verification of another provider never upgrades it. `(provider, provider_subject)` is authoritative. A Google-verified normalized email may attach Google to the one active matching user, but subject/email conflicts, unverified claims, disabled users, and uniqueness races fail closed. Legacy sessions without identity provenance are invalidated.

## Alternatives considered
WorkOS AuthKit is the preferred managed candidate because its multi-organization and enterprise SSO model matches the roadmap. Clerk offers excellent Next.js UX and organizations. Auth0 is mature and flexible. All introduce vendor control-plane, billing, outage, data-processing, and migration considerations; all reduce security maintenance.

## Consequences
M1 works locally and provider identities can migrate. ReadySet temporarily owns sensitive password/session/recovery operations and must meet a higher security/operational bar. Email delivery is a provider-neutral port: development/test captures messages and may expose raw tokens only when explicitly enabled; staging/production require TLS-capable SMTP when password auth or invitations are enabled. Password reset revokes all sessions and outstanding reset tokens.

## Revisit when
Before public production, when MFA/SCIM/SAML is committed, or when security staffing is insufficient. Human review should strongly consider replacing credential handling with WorkOS while retaining the ReadySet user/membership model.
