# ADR 002: Monorepo with independent deployables

## Context
The web and API have different runtimes and release concerns but share a product contract.

## Decision
Use `apps/api`, `apps/web`, and a minimal `apps/worker`, plus `packages/api-client`, `infra`, `scripts`, and `docs`. Web and API build as separate containers. Demo/reference repositories are ignored research inputs.

## Alternatives considered
Separate repositories increase contract coordination cost at M1. A combined Next/Python deployment couples scaling and release rollback.

## Consequences
One change can update API, client, and tests atomically while deployments remain independent.

## Revisit when
Ownership or compliance boundaries require separate repositories or release trains.
