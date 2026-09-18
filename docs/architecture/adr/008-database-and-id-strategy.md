# ADR 008: PostgreSQL, SQLAlchemy, Alembic, UUIDs

## Context
M1 needs relational integrity, tenant-safe joins, migrations, and identifiers suitable for public APIs.

## Decision
Use PostgreSQL in production, SQLAlchemy 2 models, Alembic migrations, and application-generated UUIDv4 primary keys. `EmployeeProfile.profile_metadata` and `AuditEvent.event_metadata` use PostgreSQL JSONB through a SQLAlchemy dialect variant; SQLite fast tests receive compatible generic JSON. Migration `f6f5b16f7d31` converts published PostgreSQL JSON columns additively with explicit casts. SQLite is not a supported production database. Marked PostgreSQL tests run in CI with `RUN_POSTGRES_TESTS=1` and cover composite current-version integrity, parent-row locking under concurrent version uploads, and the one-active-owner partial index.

## Alternatives considered
Integer IDs increase casual enumeration and complicate distributed creation. UUIDv7 improves locality but adds a dependency/compatibility decision not required for M1. JSON-first persistence weakens constraints.

## Consequences
Public IDs are non-sequential and portable. Indexes are larger than integers; authorization remains mandatory.

## Revisit when
Write volume proves UUIDv4 locality material or a platform-standard UUIDv7 implementation is adopted.
