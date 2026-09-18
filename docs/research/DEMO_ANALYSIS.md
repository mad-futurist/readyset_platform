# ReadySet demo analysis

## Scope and method

The backend models, migrations, route handlers, services, configuration, and the frontend providers, API layer, and principal product screens were inspected. The demo is useful product research, but it is not a safe production base.

## What exists

The FastAPI demo uses synchronous SQLAlchemy sessions, integer identifiers, route-local database queries, and no authenticated request context. `User.role` mixes identity with a product persona. `NewcomerProfile` combines employment data, onboarding state, a mentor assignment, and a one-to-one user subtype. Documents store source text directly in PostgreSQL; chunks and embeddings attach to the logical document rather than to an immutable file version. Courses, plans, tasks, assessments, events, AI conversations, signals, and Arena features are tightly connected to these demo identities.

The Next.js frontend calls handwritten Axios services. `DemoProvider` seeds the database, enumerates every user, and stores selectable mentor/newcomer IDs and roles in browser storage. IDs supplied by the browser are treated as authority. There is no session, organization selector, access-control boundary, secure file upload, or generated contract.

## Security and architecture findings

- Any caller can list or retrieve all users, people, documents, and chunks.
- Routes accept `user_id`, `mentor_id`, and other identifiers without proving identity or membership.
- There is no tenant column or provable tenant ownership path.
- Role strings are scattered and have no centralized capability policy.
- Document content and embeddings are persisted synchronously in the primary database.
- Update routes use broad attribute assignment from DTO fields.
- The frontend owns persona selection and therefore effectively owns authorization.
- Integer identifiers amplify enumeration risk, although unguessable UUIDs alone would not constitute authorization.
- Migration history shows rapid prototype evolution and duplicate/overlapping onboarding migrations; it should not be imported.

## Migration map

| Demo concept | Production decision | Reason |
|---|---|---|
| `User` | **REDESIGN** | Keep a human account, but separate login identities, memberships, and employee data. |
| `User.role` | **REMOVE / DEMO-ONLY** | Mentor/newcomer is business state, not a global authentication role. |
| `NewcomerProfile` | **REDESIGN** | M1 uses organization-owned `EmployeeProfile`; later onboarding enrollment carries newcomer state. |
| mentor/newcomer relationship | **DEFER TO LATER MILESTONE** | Preserve the product concept, later referencing employee profiles or onboarding enrollments. |
| persona switcher/localStorage IDs | **REMOVE / DEMO-ONLY** | Identity must come from a verified server session. |
| `Document` title/domain/type | **KEEP AS DOMAIN CONCEPT** | Useful discovery and organization metadata. |
| `Document.content` | **REDESIGN** | Logical document and immutable stored versions are separate; binaries live in object storage. |
| `DocumentChunk` and embeddings | **DEFER TO LATER MILESTONE** | M2 attaches extracted artifacts and chunks to a specific `DocumentVersion`. |
| source URL / repository link | **DEFER TO LATER MILESTONE** | Connector sources need a separate source/connection model and permission sync. |
| onboarding plans, phases, weeks, tasks | **DEFER TO LATER MILESTONE** | Retain the product concepts and explicit state transitions, not the current schema. |
| task comments and notifications | **DEFER TO LATER MILESTONE** | Useful collaboration concepts after onboarding/task ownership is redesigned. |
| courses, lessons, assessments | **DEFER TO LATER MILESTONE** | Learning content is separate from organization people and source documents. |
| AI conversations/questions/feedback | **DEFER TO LATER MILESTONE** | Later conversations must cite versioned retrieval evidence and enforce document ACLs. |
| signals and progress snapshots | **DEFER TO LATER MILESTONE** | Preserve intent; redesign around tenant-safe event sources. |
| `OnboardingEvent` | **KEEP AS DOMAIN CONCEPT** | Append-oriented events are valuable, but M1 implements a generic security/product audit foundation. |
| Arena and guided-demo seed | **REMOVE / DEMO-ONLY** | Demo orchestration is not production state. |
| UI primitives and visual language | **KEEP AS DOMAIN CONCEPT** | May inform later design; production UI is independently implemented. |
| handwritten frontend DTOs | **REDESIGN** | OpenAPI is authoritative; generated client adoption is incremental in M1. |

## Conclusion

No demo schema or application code is migrated. The production system independently reimplements the proven concepts of people, teams, a knowledge library, explicit lifecycle states, and append-oriented activity, behind authenticated tenant-safe APIs.
