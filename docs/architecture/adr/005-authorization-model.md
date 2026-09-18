# ADR 005: Small capability policy plus relational document ACLs

## Context
Organization administration and restricted enterprise knowledge need more than a single role, but M1 does not need a dynamic authorization engine.

## Decision
Map OWNER/ADMIN/MANAGER/MEMBER to named capabilities centrally. People/team/document services call policy functions. Document visibility is organization or restricted; restricted access uses concrete user and team grant tables. OWNER/ADMIN retain administrative access.

## Alternatives considered
Route-local role checks are inconsistent. Generic polymorphic/JSON grants lose foreign-key integrity. A full RBAC/ABAC rule engine is premature.

## Consequences
Policy is understandable, queryable, and reusable by future retrieval. Adding principal types needs schema/work, intentionally.

## Revisit when
Customers need custom roles, administrator-blind repositories, external ACL precedence, deny rules, or conditional attributes.
