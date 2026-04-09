# Phase 3: Service Productization

## Goal

Turn the current PageIndex FastAPI application from a mostly single-tenant operator console into a clearer **PageIndex service** baseline that is ready for:

- controlled multi-tenant evolution
- stronger runtime and API boundaries
- higher-concurrency service behavior
- future open-source packaging as a distinct `pageindex-service` style project

Phase 3 is intentionally split into two groups:

- Product capability iteration: `3.1` to `3.4`
- Foundational capability upgrade: `3.5`

Before Phase 3 starts, **Phase 2 must be formally closed**.

## Current Review Entry

For the current frontend productization closeout and pre-test review, read:

- [phase3_frontend_closeout_report.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/phase3_frontend_closeout_report.md)

## Codebase Reality Check

This plan is based on the current implementation, not only the earlier spec.

### What already exists

- Backend routes for auth, documents, jobs, skills, chat, providers, and metrics
- Tenant-scoped data models across most business objects
- API key auth and bearer auth through a shared principal path
- Provider profiles and provider resolution
- Skill-scoped sessions and multi-turn chat metadata
- Parse job separation via Redis worker mode
- A usable frontend for overview, documents, skills, chat, control-plane, and activity

### What is still materially incomplete

#### 1. Product tenancy is still effectively single-tenant

The code carries `tenant_id` widely, but bootstrap still creates only one default tenant and one admin user:

- `app/core/bootstrap.py`

Current login is still driven by one configured admin username/password:

- `app/core/auth.py`

So the system is **tenant-aware in schema**, but **not yet a real multi-tenant product**.

#### 2. Chat concurrency is not separated yet

Parse jobs can run via Redis worker:

- `app/services/task_queue_service.py`
- `app/worker.py`

But chat execution still runs in the API process:

- `app/services/chat_service.py`

`QUEUE_NAME_CHAT` already exists in config:

- `app/core/config.py`

But it is not wired into actual chat queue execution yet.

#### 3. Multi-manual skill configuration exists, but execution is still single-document

Skills can bind multiple `document_ids`:

- `app/models/chat_skill.py`
- `app/services/skill_service.py`
- `frontend/src/pages/SkillsPage.tsx`

However skill run currently resolves only one document:

- if request payload includes `document_id`, that single document is used
- otherwise the first linked document is used

See:

- `app/api/routers/chat.py`

Metrics also still hardcode:

- `manual_count = 1`

See:

- `app/services/chat_service.py`
- `app/services/pageindex_service.py`

So current state is:

- frontend can configure multi-document skills
- data model can persist multi-document binding
- execution path is still single-document

Phase 3 must treat this as a real gap and verify PageIndex-core feasibility before promising true multi-manual retrieval.

#### 4. Web UI is good enough for now

Current Phase 3 direction is **not** to redesign the frontend surface first.

The current web should be preserved unless backend/product changes require narrow UI adjustments.

## Phase 3 Structure

## 3.1 Product Capabilities: Tenant and Workspace Evolution

### Objective

Upgrade the system from “single default tenant with tenant-shaped tables” to an actual tenant-aware service baseline.

### Scope

- explicit tenant lifecycle model
- tenant/workspace creation and management model
- user-to-tenant membership model
- service rules for tenant isolation, ownership, and defaults
- future team support design, even if team UI stays minimal in this phase

### Required design topics

- whether tenant and workspace are identical concepts or separate
- whether one user can belong to multiple tenants
- who can create tenants
- default provider ownership rules
- tenant-level quotas and limits
- tenant-scoped API keys and provider secrets
- tenant-safe artifact and trace storage layout

### Implementation direction

- keep current `tenant_id` discipline
- replace bootstrap-only tenant assumptions with explicit creation and lookup flows
- move away from hardcoded single-admin auth assumptions

Batch 1 implementation note:

- backend foundation now includes formal `workspaces` and `tenant_memberships`
- auth resolves tenant membership plus default workspace and no longer validates login purely against one configured admin credential pair
- legacy bootstrap-admin login compatibility is limited to a one-time upgrade window before the password is normalized into the database
- schema evolution is moving to Alembic-based migration files
- legacy provider backfill keeps system-managed providers tenant-scoped and assigns legacy user-created providers to the tenant default workspace
- tenant/workspace CRUD and context switching APIs are still follow-up work

### Acceptance direction

- at least two tenants can exist without cross-tenant leakage
- tenant-scoped reads and writes are enforced consistently
- provider, document, skill, run, session, trace, and metrics access stay tenant-bounded

## 3.2 Product Capabilities: Concurrency and Execution Isolation

### Objective

Make the service behave predictably under parallel load instead of relying on API-process execution for chat.

### Scope

- chat execution queue strategy
- worker concurrency model
- per-tenant concurrency limits
- task cancellation and timeout rules
- backpressure and queue visibility
- idempotency for client retries where appropriate

### Required design topics

- whether chat should move to Redis-backed worker flow like parse jobs
- how SSE attaches to background execution
- whether to stream directly from worker, poll run state, or bridge through pub/sub
- how to preserve session ordering under concurrent requests
- whether multiple runs may execute simultaneously against one session

### Implementation direction

- reuse the existing parse queue pattern where possible
- wire the currently unused `QUEUE_NAME_CHAT`
- define worker-safe run state transitions
- add observability for queued, running, failed, cancelled chat jobs

### Acceptance direction

- concurrent runs do not corrupt session ordering or run status
- queue backlog and worker health are observable
- one tenant cannot starve the whole service without limits being visible

## 3.3 Product Capabilities: Knowledge Base and Multi-Manual Retrieval

### Objective

Evolve the product from document chat toward a stable knowledge-container model that can support:

- skills bound to reusable knowledge scopes
- multi-manual retrieval
- later compliance-oriented APIs

### Scope

- validate true multi-manual retrieval feasibility against PageIndex core
- introduce a formal `knowledge_base` resource above documents
- support KB-oriented querying and document/version resolution

### Important reality check

Do not assume that current skill multi-document binding means the retrieval engine already supports true cross-manual reasoning.

Current code only guarantees:

- skill configuration can reference multiple documents
- runtime execution still selects one document

Therefore Phase 3 must start with a feasibility spike:

1. determine whether PageIndex core can support true multi-manual querying by orchestration at service layer
2. if yes, define the aggregation strategy
3. if no, narrow the product contract before building public APIs

### Candidate Phase 3 outputs

- `knowledge_bases`
- `knowledge_base_documents`
- skills bound to `knowledge_base_id` rather than raw `document_ids`
- query across one or more enabled manuals inside one KB
- citation payloads with full source provenance

Batch 2 implementation note:

- backend schema/API now includes `knowledge_bases`, `knowledge_base_documents`, and `chat_skills.knowledge_base_id`
- KB CRUD and skill-to-KB binding are now part of the backend surface
- `skills.document_ids` remains as a compatibility shim and is synchronized from KB membership where needed
- chat queue / worker changes, federated multi-manual execution, and compliance APIs remain deferred to later batches

### Acceptance direction

- KB becomes the first-class grouping resource rather than ad hoc document lists
- if true multi-manual support is implemented, result payload must identify which document/version each citation came from
- if only orchestration-level fan-out is feasible, that limitation must be explicit in API semantics
- no hidden fallback to “first document only”

## 3.4 Product Capabilities: Compliance API

### Objective

Expose a machine-friendly compliance surface built on top of KB-scoped retrieval rather than directly on top of chat-shaped skill runs.

### Scope

- reusable compliance definitions
- compliance run execution and result schema
- structured evidence, gaps, conflicts, verdicts, and provenance
- compatibility with both single-manual and federated KB execution

### Important dependency

Compliance API is downstream of the KB model. It should not define a parallel grouping abstraction such as `manual_set` once `knowledge_base` exists.

### Acceptance direction

- compliance resources are workspace-scoped and tenant-bounded
- compliance results carry full source provenance
- API semantics are truthful for both single-manual and multi-manual KB execution
- public contract is machine-friendly, not only prose-chat friendly

## 3.5 Foundational Capabilities

### Objective

Strengthen the service boundary so later open-source release and production usage are not built on brittle defaults.

### Scope

- runtime hardening
- security boundaries
- service configuration hygiene
- operability and deployment quality

### Topics

- safer listen/bind defaults
- stricter CORS defaults
- provider URL and secret handling
- upload limits and payload validation
- auditability of auth and key usage
- better error taxonomy
- migration discipline beyond bootstrap patching
- packaging and deployment clarity for later OSS split

### Deliberate choice for this phase

The current web UI is preserved as-is unless a backend change requires minimal supporting edits.

## Suggested Spec Outputs

Phase 3 should be written as a small spec set, for example:

- `phase3_service_productization/README.md`
- `phase3_service_productization/tenant_and_workspace_model.md`
- `phase3_service_productization/chat_concurrency.md`
- `phase3_service_productization/knowledge_base_and_multi_manual.md`
- `phase3_service_productization/compliance_api.md`
- `phase3_service_productization/foundations.md`

## Exit Intent

After Phase 3:

- the repository should have a clear path toward a standalone `pageindex-service`
- multi-tenant and concurrent-service behavior should no longer be implicit or half-complete
- multi-manual capability should be either truly implemented or explicitly scoped
- the project should be in a better state for an open-source split with a distinct service identity
