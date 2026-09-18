# ADR 004: Shared schema, mandatory organization scoping

## Context
Organizations are the security boundary; users may belong to many. M1 needs strong isolation without operating a database per customer.

## Decision
Use a shared PostgreSQL schema. Every tenant-owned table has `organization_id`; child/join tables use composite constraints where useful. Request context verifies active membership, and repositories require organization ID in every predicate. Return 404 for cross-tenant identifiers.

PostgreSQL RLS is not enabled in M1. Application sessions currently use one database role and connection pooling makes safe per-transaction tenant variables additional operational complexity. RLS would not replace object-storage or service authorization.

## Alternatives considered
Database/schema per tenant is operationally heavy. RLS now offers defense in depth but risks a false sense of coverage and migration/admin bypasses.

## Consequences
Isolation is explicit and testable, but application bugs remain a risk; repository review and adversarial tests are mandatory.

## Revisit when
Before regulated enterprise launch or once a robust transaction-local tenant context and separate migration/bypass roles can be enforced; then add RLS as defense in depth.
