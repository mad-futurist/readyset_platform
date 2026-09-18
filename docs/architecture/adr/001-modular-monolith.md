# ADR 001: Modular monolith

## Context
M1 has tightly related identity, organization, people, document, and audit transactions. The team needs quick local development without losing module boundaries needed by later ingestion.

## Decision
Build one FastAPI deployable with explicit modules and one database. Domain services own use cases; organization-scoped repositories own data access. A later worker imports application services/contracts but does not become a separate domain authority.

## Alternatives considered
Microservices add distributed authorization, transactions, deployment, and observability before any scaling evidence. A single unstructured app would make tenant rules easy to bypass.

## Consequences
Cross-module transactions and local tests are straightforward. Module boundaries require code review rather than network isolation.

## Revisit when
A workload needs independent scaling/failure isolation and has a stable asynchronous contract—likely document ingestion, not core identity.
