# ReadySet: Prototype-to-Production Transition

## Purpose

ReadySet is being rebuilt from a hackathon/demo AI-onboarding application into a production-oriented B2B SaaS platform.

The goal is **not** to patch the prototype until it looks production-ready. The prototype is treated as product research: it proves workflows, user value, AI interactions, and UI ideas. The production platform independently reimplements valuable concepts on top of explicit identity, tenant isolation, authorization, versioned enterprise knowledge, reproducible builds, migrations, tests, and deployable infrastructure boundaries.

This document is the high-level source of truth for:
- where the prototype lives;
- what the prototype proved;
- why it is not the production base;
- what has already been rebuilt in production;
- which concepts were retained, redesigned, removed, or deferred;
- the current architecture and engineering guarantees;
- the roadmap from M1 into document intelligence and later ReadySet product capabilities.

For detailed evidence, see:
- `docs/research/DEMO_ANALYSIS.md`
- `docs/research/REFERENCE_ANALYSIS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/architecture/DOMAIN_MODEL.md`
- `docs/architecture/IMPLEMENTATION_STATUS.md`
- `docs/architecture/SECURITY_INVARIANTS.md`
- `docs/operations/PRODUCTION_DEPLOYMENT.md`
- `docs/review/M1_FINAL_HARDENING_ANALYSIS.md`

---

## 1. Product origin

ReadySet started as an AI onboarding demo intended to explore a larger product idea:

> Turn enterprise knowledge into a structured, adaptive onboarding and learning system that can understand company information, generate useful learning artifacts, coordinate onboarding work, and later support AI agents operating with explicit evidence and permissions.

The prototype explored this broadly and quickly. It includes strategically valuable concepts such as:
- users, newcomers and mentors;
- company documents and knowledge;
- AI-generated onboarding plans;
- onboarding tasks and Kanban workflows;
- courses and lessons;
- assessments;
- AI question answering;
- AI signals with evidence;
- progress snapshots;
- blocked reports;
- mentor digests;
- meetings and notifications;
- company knowledge gaps;
- events and feedback;
- experimental AI/agent-style workflows.

The prototype answered: **“What could ReadySet do?”**

The production repository answers: **“What architecture can safely support ReadySet as a real multi-user B2B product?”**

---

## 2. Where the prototype lives

### Original prototype repositories

The original prototype remains available in separate repositories:
- Backend: `mad-futurist/ai-onboarding-service`
- Frontend: `mad-futurist/ai-onboarding-service-frontend`

They are historical/product references, not production dependencies.

### Local research copy

During the production migration, local prototype clones are kept under:

```text
readyset_platform/
└── demo/
```

The entire `demo/` tree is intentionally ignored by Git and excluded from production builds and runtime artifacts.

### External architecture references

Architecture research repositories are kept locally under:

```text
readyset_platform/
└── references/
```

Examples include Twenty, Onyx, Open edX, Plane, and RAGFlow.

Like `demo/`, `references/` is ignored and never used as a production dependency.

`AGENTS.md` permanently enforces this isolation.

---

## 3. Why the prototype was not promoted directly

The prototype was optimized for exploration speed, not enterprise safety.

Key limitations included:
- no real authenticated request identity;
- browser-selected mentor/newcomer personas;
- client-provided IDs effectively acting as authority;
- no organization/tenant boundary;
- global role strings mixing identity and business state;
- broad resource enumeration;
- documents storing source text directly in PostgreSQL;
- retrieval without tenant/ACL guarantees;
- synchronous document/embedding work;
- no stable document-version identity;
- no secure object-storage boundary;
- no production email/auth recovery model;
- no production-oriented CI/deployment guarantees.

Migration strategy:

```text
Prototype
    │
    │ extract product concepts
    ▼
Domain analysis
    │
    │ redesign security and ownership
    ▼
Production foundation
    │
    │ reintroduce product intelligence
    ▼
Production ReadySet
```

The prototype database schema and migration history are not imported into the production database.

Any future migration of demo data should use explicit one-off import/transform scripts rather than prototype schema assumptions.

---

## 4. Production repository

Production ReadySet lives in:

`mad-futurist/readyset_platform`

Current high-level repository shape:

```text
readyset_platform/
├── apps/
│   ├── api/                FastAPI production backend
│   ├── web/                Next.js production frontend
│   └── worker/             reserved M2 async boundary
├── packages/
│   └── api-client/         generated TypeScript API contract
├── docs/
│   ├── architecture/
│   ├── operations/
│   ├── research/
│   └── review/
├── infra/
├── scripts/
├── docker-compose.yml
├── AGENTS.md
├── demo/                   local, ignored prototype research
└── references/             local, ignored OSS research
```

The production system is a modular monolith, not a premature microservice architecture.

Frontend and backend are independently deployable but remain in one repository so vertical changes can update API, frontend, tests, migrations, and documentation together.

---

## 5. Production target

Long-term conceptual product flow:

```text
Enterprise sources
       │
       ▼
Secure versioned knowledge
       │
       ▼
Extraction / structure / provenance
       │
       ▼
Retrieval and understanding
       │
       ├──► Ask AI with evidence
       ├──► Learning content
       ├──► Onboarding programs
       ├──► Tasks and workflows
       └──► Agent actions with policy/approval
```

Later AI behavior must operate on top of:
- authenticated users;
- explicit organization membership;
- document ACLs;
- stable source versions;
- traceable provenance;
- reproducible processing;
- explicit business state;
- controlled actions.

AI is not the foundation layer. It is built on top of production knowledge and authorization.

---

## 6. M1: production foundation

M1 intentionally excluded advanced prototype AI features.

Objective:

> Production foundation + organizations + people + secure documents.

### Identity and authentication

Production separates:

```text
User
├── AuthIdentity
├── PasswordCredential
└── SessionRecord
```

Implemented foundations:
- email/password;
- email verification;
- password reset;
- Google OAuth/OIDC;
- identity-bound server sessions;
- CSRF protection;
- OAuth state + PKCE + nonce + browser binding;
- safe Google reclaim of an account containing an unverified password identity.

### Multi-tenancy

`Organization` is the tenant boundary.

```text
User
  │
  ▼
OrganizationMembership
  │
  ▼
Organization
```

Current roles:
- OWNER
- ADMIN
- MANAGER
- MEMBER

Newcomer and mentor are intentionally not authentication roles.

Tenant authority comes from current authenticated identity plus active organization membership.

### People

Employee/domain identity is separated from login identity:

```text
User
     │ optional link
     ▼
EmployeeProfile
```

Production includes:
- employee profiles;
- teams;
- team memberships;
- manager relationships;
- organization-scoped relational integrity.

Future onboarding state can therefore attach to employees rather than authentication identities.

### Secure documents

The production document model separates a logical document from its physical source versions:

```text
Document
   │
   └── DocumentVersion
          ├── version_number
          ├── storage_key
          ├── MIME type
          ├── size
          ├── SHA-256
          └── processing lifecycle
```

Raw files live in private S3-compatible object storage, not PostgreSQL.

Accepted source formats currently include PDF, DOCX, Markdown, and plain text.

Uploads include:
- size bounds;
- actual-content validation;
- MIME/content agreement;
- SHA-256;
- malware-scanner boundary;
- server-generated storage keys;
- compensating cleanup on DB failure.

### ACL and version integrity

Documents support:
- organization-wide visibility;
- restricted visibility;
- user grants;
- team grants.

The same server-side ACL boundary protects metadata, version history, and downloads, and is intended for future retrieval/RAG reuse.

Production also guarantees:
- current version belongs to the same logical document;
- new source bytes create a new version;
- concurrent version allocation is serialized;
- future chunks/citations can reference exact versions.

---

## 7. M1.1: production hardening

M1.1 closed the engineering gaps around the foundation.

### Security
- password/Google pre-hijacking protection;
- trusted-proxy semantics;
- Redis-backed shared rate limiting;
- upload/user/org abuse buckets;
- file content validation;
- ClamAV-compatible scanning;
- controlled storage errors;
- safe pre-stream download failures;
- hardened environment validation;
- browser security headers;
- secret-safe structured logging.

### Database
- additive Alembic migrations;
- PostgreSQL-specific integrity tests;
- JSONB flexible metadata;
- tenant composite FKs;
- same-document current-version FK;
- one-active-owner constraint;
- atomic ownership transfer;
- invitation integrity;
- locked concurrent version creation.

### Runtime / CI / deployment
- non-root API and web containers;
- migrations separated from API startup;
- `/livez` and `/readyz`;
- frozen Python dependencies through `uv.lock`;
- OpenAPI drift checks;
- isolated CI jobs for API, storage, Redis, frontend, containers, and security;
- real MinIO and Redis integration tests;
- vulnerability audits;
- full-history secret scanning.

---

## 8. Current visible product

A user can manually exercise a real multi-user SaaS flow.

### Account
- sign up;
- verify email;
- sign in;
- Google sign in when configured;
- resend verification;
- forgot/reset password.

### Organization
- create workspace;
- switch organizations;
- rename organization;
- invite users;
- reissue/revoke invitations;
- accept invitations;
- change member role;
- revoke members;
- transfer ownership.

### People and teams
- create employee profiles;
- browse people;
- create teams;
- use teams as document ACL principals.

### Knowledge
- upload documents;
- choose organization/restricted visibility;
- inspect document details;
- see version history;
- upload new versions;
- download versions;
- assign restricted access to users/teams.

This is the manually testable production foundation on which the AI product is now rebuilt.

---

## 9. Local development

The repository runs locally through Docker Compose.

Core local services:

```text
Next.js
FastAPI
PostgreSQL
MinIO
Redis
```

Development can use the explicit no-op scanner. Hardened staging/production requires a real scanner.

Optional Mailpit support provides a local SMTP inbox for registration, verification, password reset, and invitation flows without sending internet email.

See root `README.md`, `apps/api/README.md`, and `apps/web/README.md`.

---

## 10. Current verified state

Current main snapshot at the time of this document:

`fefb2b4ecc4a60293be08fe9fa73d30fadd2ce8a`

Latest CI run for that commit is green.

The closed M1.1 foundation has verified gates for:
- Ruff;
- strict mypy;
- PostgreSQL migrations;
- Alembic drift;
- PostgreSQL integrity/concurrency;
- MinIO integration;
- Redis integration;
- frontend lint/typecheck/tests/build;
- API/web Docker builds;
- non-root runtime;
- dependency audits;
- full-history secret scanning.

The later `Test account` commit preserves M1.1 architecture and adds local-development improvements around CSV environment parsing and optional Mailpit email testing.

---

## 11. Prototype concept disposition

| Prototype concept | Production direction |
|---|---|
| User account | Redesigned into User + AuthIdentity + Membership |
| Mentor/newcomer global roles | Removed as auth roles; later business relationships |
| NewcomerProfile | EmployeeProfile + future OnboardingEnrollment |
| Documents | Rebuilt as Document + versioned object-storage sources |
| Document chunks / embeddings | M2, version-scoped |
| Ask AI | After ACL-safe retrieval |
| Courses / lessons / assessments | Later learning milestone |
| 30/60/90 onboarding plan | Later onboarding milestone |
| Tasks / Kanban / blocked reports | Later work/onboarding milestone |
| AI signals / progress snapshots | Later event/analytics milestone |
| Mentor digest | Later, from authoritative events |
| Meetings / notifications | Deferred |
| Demo persona switcher | Removed |
| Demo seed/orchestration | Removed |
| Useful UI/product ideas | Research input, independently reimplemented |

---

## 12. Roadmap

### M1 / M1.1 — CLOSED

Foundation:
- identity;
- organizations;
- people/teams;
- secure documents;
- ACL;
- versioning;
- production engineering/security baseline.

### M2 — Document Intelligence

```text
DocumentVersion
      │
      ▼
IngestionJob
      │
      ├── extract
      ├── preserve structure/provenance
      ├── chunk by source version
      ├── embed
      └── index
                │
                ▼
        ACL-safe retrieval
                │
                ▼
       evidence-backed Ask AI
```

M2 establishes the production knowledge-processing layer. It should not rebuild every demo feature.

### M3 — Generic learning model + AI course generation

Expected model direction:

```text
Course
 └── Module
      └── LearningUnit
           └── ContentBlock[]
```

### M4 — Onboarding + tasks
- onboarding programs/enrollments;
- plans;
- tasks;
- mentor relationships;
- reviews;
- blocked state;
- 30/60/90 views.

### M5 — Agent runtime
Use `workflow + tools + state + policy + approvals`, not unconstrained autonomous loops.

### M6 — Enterprise integrations
Examples: Jira, SharePoint/Drive, Teams/Slack and work systems.

### M7 — Signals, analytics and compliance
Build signals from authoritative events and provenance.

---

## 13. Rules for using the prototype going forward

Use the prototype to answer:
- What workflow had value?
- Which screens/interactions are worth rebuilding?
- What states existed?
- Which AI artifacts were useful?

Do not use it as authority for:
- authentication;
- tenancy;
- authorization;
- production DB schema;
- storage;
- retrieval security;
- deployment;
- migrations;
- production API contracts.

When rebuilding a prototype feature:
1. identify the product intent in `demo/`;
2. read production domain/security constraints;
3. redesign for current production entities;
4. implement independently;
5. add tenant/security tests;
6. update OpenAPI/client contracts;
7. update architecture/status documentation when boundaries change.

---

## 14. Definition of progress

ReadySet is not more production-ready because more prototype screens are copied.

Progress means a valuable capability is reintroduced while preserving:
- tenant isolation;
- authorization;
- provenance;
- version identity;
- explicit state;
- testability;
- observability;
- migration safety.

Transition strategy:

```text
broad prototype
     ↓
small trusted foundation
     ↓
document intelligence
     ↓
learning/onboarding workflows
     ↓
controlled agents/integrations
     ↓
full production product
```
