# ADR 008: PostgreSQL, SQLAlchemy, Alembic, UUIDs

## Context
M1 needs relational integrity, tenant-safe joins, migrations, and identifiers suitable for public APIs.

## Decision
Use PostgreSQL in production, SQLAlchemy 2 models, Alembic migrations, and application-generated UUIDv4 primary keys. Flexible metadata alone uses JSONB. SQLite is not a supported production database; fast tests may use it only where behavior is equivalent, with PostgreSQL integration tests in CI/local Compose.

## Alternatives considered
Integer IDs increase casual enumeration and complicate distributed creation. UUIDv7 improves locality but adds a dependency/compatibility decision not required for M1. JSON-first persistence weakens constraints.

## Consequences
Public IDs are non-sequential and portable. Indexes are larger than integers; authorization remains mandatory.

## Revisit when
Write volume proves UUIDv4 locality material or a platform-standard UUIDv7 implementation is adopted.
