# ADR 003: Provider-neutral in-product authentication for M1

## Context
M1 requires email/password and Google OIDC, while future customers may require Entra ID, enterprise OIDC, SAML, MFA, and directory lifecycle. Current WorkOS AuthKit, Clerk, and Auth0 offerings can provide these capabilities. External credentials and a vendor decision are not available for a reproducible local milestone.

## Decision
Implement a deliberately narrow authentication core: `User`, extensible `AuthIdentity`, Argon2id password credential, email verification/reset tokens, opaque hashed server-side sessions, and Google Authorization Code + PKCE + nonce. Authorization and ReadySet memberships remain local regardless of authentication provider.

## Alternatives considered
WorkOS AuthKit is the preferred managed candidate because its multi-organization and enterprise SSO model matches the roadmap. Clerk offers excellent Next.js UX and organizations. Auth0 is mature and flexible. All introduce vendor control-plane, billing, outage, data-processing, and migration considerations; all reduce security maintenance.

## Consequences
M1 works locally and provider identities can migrate. ReadySet temporarily owns sensitive password/session/recovery operations and must meet a higher security/operational bar. Email delivery is an adapter and local development returns captured links only in non-production mode.

## Revisit when
Before public production, when MFA/SCIM/SAML is committed, or when security staffing is insufficient. Human review should strongly consider replacing credential handling with WorkOS while retaining the ReadySet user/membership model.
