# Workspace / Operator / User Management Gap Audit

## Current State Audit

This audit is based on the current Phase 3 backend implementation and the active frontend contract, not only on the intended Phase 3 wording.

Primary references:

- [README.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/README.md)
- [tenant_and_workspace_model.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/tenant_and_workspace_model.md)
- [phase3_frontend_closeout_report.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/phase3_frontend_closeout_report.md)
- [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py)
- [bootstrap.py](/Users/shaoqing/workspace/PageIndex/app/core/bootstrap.py)
- [principal.py](/Users/shaoqing/workspace/PageIndex/app/core/principal.py)

### 1. Data model and auth foundation are in place

Phase 3 did land real backend foundation work:

- `Workspace` exists as a first-class table with `tenant_id`, `slug`, `is_default`, and `default_provider_id`: [workspace.py](/Users/shaoqing/workspace/PageIndex/app/models/workspace.py#L9)
- `TenantMembership` exists as a first-class table with `tenant_id`, `user_id`, `role`, and `status`: [tenant_membership.py](/Users/shaoqing/workspace/PageIndex/app/models/tenant_membership.py#L9)
- `Principal` now carries `tenant_id`, `workspace_id`, and `membership_role`: [principal.py](/Users/shaoqing/workspace/PageIndex/app/core/principal.py#L6)
- login/auth resolves membership plus active workspace and includes them in JWT claims: [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L122), [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L165)
- bootstrap guarantees one default workspace plus one owner membership for the bootstrap tenant: [bootstrap.py](/Users/shaoqing/workspace/PageIndex/app/core/bootstrap.py#L44), [bootstrap.py](/Users/shaoqing/workspace/PageIndex/app/core/bootstrap.py#L70), [bootstrap.py](/Users/shaoqing/workspace/PageIndex/app/core/bootstrap.py#L118)

This means the codebase is no longer purely “single-tenant schema with no workspace notion”. The foundation is real.

### 2. Product shell is still single-context

The same code also shows why this has not become a full product capability:

- login returns exactly one resolved workspace context plus a flat membership list, but no switch API: [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L29)
- `resolve_auth_context(...)` always picks one active membership and then one workspace, defaulting to the tenant default workspace when no explicit workspace is supplied: [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L79), [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L94), [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L122)
- frontend stores the returned `workspace` and `memberships` in local storage, but active workspace resolution is just `user.workspace_id`; there is no UI or API contract for switching: [LoginPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/LoginPage.tsx#L20), [client.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/lib/api/client.ts#L141)

So the current runtime has an active workspace context, but not a productized workspace-selection flow.

### 3. `tenant_membership` exists, but management does not

The backend now has membership state in the database and in auth context:

- membership lookup is the access-control source used by auth: [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L79), [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L122)
- login returns memberships to the client: [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L36)

But there are no backend routes for:

- membership list
- add/invite/remove member
- role change
- tenant admin actions

The router package only exposes auth, documents, jobs, skills, chat, providers, metrics, knowledge bases, and compliance routes. There is no workspace lifecycle router, no membership router, and no user admin router under [app/api/routers](/Users/shaoqing/workspace/PageIndex/app/api/routers).

### 4. `operator` is not a backend model today

There is no backend `operator` entity or operator-specific API. A repository-wide search of `app/` shows no backend `operator` model, service, or router usage.

What exists instead is:

- `User`: identity row, still carrying compatibility `tenant_id`: [user.py](/Users/shaoqing/workspace/PageIndex/app/models/user.py#L9)
- `TenantMembership`: tenant access + role: [tenant_membership.py](/Users/shaoqing/workspace/PageIndex/app/models/tenant_membership.py#L9)
- `membership_role` in principal and token: [principal.py](/Users/shaoqing/workspace/PageIndex/app/core/principal.py#L6), [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L165)

In other words, `operator` currently exists only as product wording in the frontend/spec, not as a backend control-plane concept.

### 5. Resource scope audit

| Resource | Model state | API/service behavior | Assessment |
| --- | --- | --- | --- |
| `document` | `workspace_id` exists and is nullable: [document.py](/Users/shaoqing/workspace/PageIndex/app/models/document.py#L9) | read/write uses principal workspace filter, with default-workspace fallback to legacy `NULL` rows: [document_service.py](/Users/shaoqing/workspace/PageIndex/app/services/document_service.py#L23), [documents.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/documents.py#L68) | workspace-aware, but transitional |
| `provider` | `workspace_id` exists and is nullable: [model_provider.py](/Users/shaoqing/workspace/PageIndex/app/models/model_provider.py#L9) | runtime binding checks workspace accessibility, but CRUD/list routes remain tenant-scoped and schema does not expose workspace ownership: [provider_service.py](/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py#L67), [provider_service.py](/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py#L324), [providers router](/Users/shaoqing/workspace/PageIndex/app/api/routers/providers.py#L18), [providers schema](/Users/shaoqing/workspace/PageIndex/app/schemas/providers.py#L8) | tenant-aware with workspace hook, not a true workspace-managed resource |
| `knowledge base` | `workspace_id` is required: [knowledge_base.py](/Users/shaoqing/workspace/PageIndex/app/models/knowledge_base.py#L9) | all CRUD routes are `/workspaces/{workspace_id}/...` and require current principal workspace to match: [knowledge_bases.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/knowledge_bases.py#L29), [knowledge_base_service.py](/Users/shaoqing/workspace/PageIndex/app/services/knowledge_base_service.py#L15) | strongly workspace-aware inside the current active workspace |
| `skill` | `workspace_id` exists and is nullable: [chat_skill.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_skill.py#L9) | create/list/get/update validate same-workspace docs/provider/KB and list by `principal.workspace_id`: [skill_service.py](/Users/shaoqing/workspace/PageIndex/app/services/skill_service.py#L58), [skill_service.py](/Users/shaoqing/workspace/PageIndex/app/services/skill_service.py#L129), [skills.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/skills.py#L22) | workspace-aware |
| `session` | `workspace_id` exists and is nullable: [chat_session.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_session.py#L9) | create uses current workspace; list/get filter by workspace with default-workspace fallback to `NULL`: [session_service.py](/Users/shaoqing/workspace/PageIndex/app/services/session_service.py#L22), [session_service.py](/Users/shaoqing/workspace/PageIndex/app/services/session_service.py#L42), [chat.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/chat.py#L256) | workspace-aware, but transitional |
| `run` | `workspace_id` exists and is nullable: [chat_run.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_run.py#L9) | run creation derives workspace from session/document/skill; reads filter by workspace with default-workspace fallback: [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py#L292), [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py#L354), [chat.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/chat.py#L203) | workspace-aware, but transitional |
| `api key` | `workspace_id` exists and is nullable: [api_key.py](/Users/shaoqing/workspace/PageIndex/app/models/api_key.py#L9) | issuance/list/revoke are all tied to the current principal workspace; auth resolves API key workspace context: [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L84), [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L117), [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L223) | workspace-aware |
| `parse job` | `workspace_id` exists and is nullable: [parse_job.py](/Users/shaoqing/workspace/PageIndex/app/models/parse_job.py#L9) | creation records workspace, but list/get routes ignore active workspace and only filter by `current_user.tenant_id`: [documents.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/documents.py#L110), [jobs.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/jobs.py#L13) | still tenant-aware in exposed API |

### 6. Routes still using tenant-only or bootstrap-only behavior

The following paths remain tenant-aware or bootstrap-aware rather than fully workspace-aware:

- bootstrap creates and maintains only one default tenant/user/workspace shell: [bootstrap.py](/Users/shaoqing/workspace/PageIndex/app/core/bootstrap.py#L118)
- `jobs` uses `get_current_user()` and scopes by `current_user.tenant_id`, not principal workspace: [deps.py](/Users/shaoqing/workspace/PageIndex/app/api/deps.py#L11), [jobs.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/jobs.py#L13)
- `metrics/overview` also uses `get_current_user()` and aggregates tenant-wide counts: [metrics.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/metrics.py#L13)
- provider CRUD/list stays tenant-scoped even though the model carries `workspace_id`: [providers.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/providers.py#L18), [provider_service.py](/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py#L56)

## Isolation Assessment

### Tenant isolation: `partial`

#### Why it is not `weak`

Most business objects still enforce tenant bounds in model/service/router code:

- documents: [document_service.py](/Users/shaoqing/workspace/PageIndex/app/services/document_service.py#L39)
- skills: [skill_service.py](/Users/shaoqing/workspace/PageIndex/app/services/skill_service.py#L58)
- runs: [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py#L544)
- providers: [provider_service.py](/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py#L56)
- storage layout remains tenant-rooted: tenant data is stored under `tenants/{tenant_id}` paths in storage service: [storage_service.py](/Users/shaoqing/workspace/PageIndex/app/services/storage_service.py#L47)

There is no obvious broad cross-tenant leakage in the main document/skill/chat/provider flows.

#### Why it is not `strong`

Tenant isolation is still not closed as a product capability:

- `User.tenant_id` remains mandatory compatibility state: [user.py](/Users/shaoqing/workspace/PageIndex/app/models/user.py#L12)
- auth still falls back to `user.tenant_id` when resolving context: [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L129)
- `get_current_user()` throws away principal tenant/workspace context and returns only the raw `User`, which means downstream routes can silently scope by `user.tenant_id` instead of active membership context: [deps.py](/Users/shaoqing/workspace/PageIndex/app/api/deps.py#L11)
- `jobs` and `metrics` already do this: [jobs.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/jobs.py#L13), [metrics.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/metrics.py#L13)
- there is still no tenant lifecycle or tenant switching API even though memberships exist: [tenant_and_workspace_model.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/tenant_and_workspace_model.md)

#### Tenant-isolation closeout items

The current key gaps are:

- routes that still bind to `User.tenant_id` rather than active `Principal`
- no explicit tenant context switch flow
- no tenant/member administration surface to make memberships operable

### Workspace isolation: `partial`

#### Why it is not `weak`

Workspace isolation is already real for several important resources:

- knowledge bases and compliance resources are explicitly nested under `/workspaces/{workspace_id}` and reject mismatched workspace context: [knowledge_bases.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/knowledge_bases.py#L29), [compliance_checks.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/compliance_checks.py#L20), [compliance_runs.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/compliance_runs.py#L18), [knowledge_base_service.py](/Users/shaoqing/workspace/PageIndex/app/services/knowledge_base_service.py#L15)
- documents, sessions, and runs do apply workspace filtering in services: [document_service.py](/Users/shaoqing/workspace/PageIndex/app/services/document_service.py#L33), [session_service.py](/Users/shaoqing/workspace/PageIndex/app/services/session_service.py#L22), [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py#L292)
- API keys are issued and listed per active workspace: [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L84), [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L117)

So workspace is not merely decorative.

#### Why it is not `strong`

Workspace isolation still has several open loops:

- default workspace can see legacy `NULL workspace_id` rows for documents/sessions/messages/runs, so behavior is intentionally compatibility-driven rather than strictly partitioned: [document_service.py](/Users/shaoqing/workspace/PageIndex/app/services/document_service.py#L33), [session_service.py](/Users/shaoqing/workspace/PageIndex/app/services/session_service.py#L22), [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py#L292)
- there is no workspace list API, no switch API, and no workspace CRUD API, so users cannot actually operate multiple workspaces even though the runtime can carry one: [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L29), [client.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/lib/api/client.ts#L163)
- provider ownership is ambiguous: runtime checks workspace accessibility, but CRUD/list remains tenant-wide and schema does not expose `workspace_id`: [provider_service.py](/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py#L67), [providers router](/Users/shaoqing/workspace/PageIndex/app/api/routers/providers.py#L31), [providers schema](/Users/shaoqing/workspace/PageIndex/app/schemas/providers.py#L28)
- `jobs` and `metrics` are not workspace-aware surfaces at all: [jobs.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/jobs.py#L13), [metrics.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/metrics.py#L13)
- chat session/run API schemas do not expose `workspace_id`, which makes cross-workspace admin or diagnostics difficult even if the DB field exists: [chat schema](/Users/shaoqing/workspace/PageIndex/app/schemas/chat.py#L31)

#### Workspace-isolation closeout items

The current key gaps are:

- no formal workspace switch path
- no workspace lifecycle management
- legacy `NULL workspace_id` compatibility behavior still present
- provider/job/metrics paths are not closed around workspace scope

## Missing Management Capabilities

### 1. Capability checklist

| Capability | Present now? | Evidence | Impact |
| --- | --- | --- | --- |
| workspace list | No | no workspace router; frontend only reads one stored `workspace`: [client.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/lib/api/client.ts#L152) | can only operate current workspace context |
| workspace switch | No | login returns one resolved workspace, but no `/auth/context/switch` or equivalent route: [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L29) | memberships are informational only |
| workspace create/update/delete | No | no workspace CRUD router in [app/api/routers](/Users/shaoqing/workspace/PageIndex/app/api/routers) | workspace is not an operable product object |
| workspace member list | No | no workspace member router/model | cannot present workspace access administration |
| add/invite/remove member | No | `TenantMembership` exists, but no member mutation routes: [tenant_membership.py](/Users/shaoqing/workspace/PageIndex/app/models/tenant_membership.py#L9) | no team onboarding/offboarding flow |
| role change | No | role is stored in membership, but there is no API to mutate it: [tenant_membership.py](/Users/shaoqing/workspace/PageIndex/app/models/tenant_membership.py#L18) | admin roles cannot be managed |
| user/operator list | No | no user admin router; no backend `operator` concept in `app/` | “operator” cannot land as a real backend product capability |
| enable/disable user | No surface | `User.is_active` exists, but there is no admin API: [user.py](/Users/shaoqing/workspace/PageIndex/app/models/user.py#L16) | deactivation is only a data-model possibility, not a product feature |

### 2. Product effect on the frontend

These gaps directly explain the current frontend limitations:

- the frontend can display only the currently stored workspace context, not manage or switch it: [LoginPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/LoginPage.tsx#L20), [client.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/lib/api/client.ts#L163)
- `memberships` are stored client-side but not consumable through any follow-up backend workflow: [LoginPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/LoginPage.tsx#L22)
- the “Workspace console” IA from Phase 3 frontend closeout is therefore a single active-workspace shell, not a real multi-workspace admin product yet: [phase3_frontend_closeout_report.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/phase3_frontend_closeout_report.md)
- because `operator` has no backend model or API, the frontend’s operator-facing wording still maps only to a logged-in user acting in one workspace

### 3. Data model vs auth helper vs product capability

This distinction matters for Phase 3 closeout:

#### Data model already laid down

- `Workspace`
- `TenantMembership`
- `workspace_id` on core resources
- `User.is_active`

References:

- [workspace.py](/Users/shaoqing/workspace/PageIndex/app/models/workspace.py#L9)
- [tenant_membership.py](/Users/shaoqing/workspace/PageIndex/app/models/tenant_membership.py#L9)
- [user.py](/Users/shaoqing/workspace/PageIndex/app/models/user.py#L9)

#### Auth helper already exists

- principal carries tenant/workspace/role
- JWT carries tenant/workspace/role
- login resolves default workspace and returns membership metadata
- API key issuance is workspace-aware

References:

- [principal.py](/Users/shaoqing/workspace/PageIndex/app/core/principal.py#L6)
- [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L122)
- [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L29)

#### Product capability still missing

- workspace discovery/switch
- workspace lifecycle
- membership management
- user administration
- operator control-plane semantics

That is why the backend feels “half productized”: the model and principal exist, but the administration plane does not.

### 4. Phase classification of the gaps

My classification is:

- workspace list/switch: Phase 3 follow-up that should now become Phase 3 closeout scope
- workspace CRUD: originally deferred in spec, but still close enough to Phase 3.1 intent that at least minimal support belongs near Phase 3 closeout
- tenant member list/add/remove/role change: spec-defined but deferred; better split into minimum closeout read/list surface plus later mutating admin flow
- user/operator admin: this is not really implemented-and-missing; it is closer to a true next-phase control-plane capability

So these are not primarily “spec was unfinished”. The spec named most of them. The gap is that the implementation stopped after schema/auth foundation and never turned that foundation into an admin surface.

## Phase 3 Closeout Recommendation

### Recommendation

**Phase 3 should add a closeout slice for workspace/operator management.**

Reason:

- Phase 3 already introduced `Workspace`, `TenantMembership`, and workspace-aware auth context.
- Several core resources already behave as workspace-scoped resources.
- Without workspace list/switch/admin surfaces, the product remains locked to one implicit active workspace, which makes the new model structurally incomplete rather than merely “future enhancement”.

This does not mean Phase 3 must implement a full enterprise admin console. It means Phase 3 should finish the minimum control-plane slice required to make the current model honest and operable.

### 1. Minimum scope that should be included in Phase 3 closeout

Recommended name:

- `Phase 3.6 Workspace Administration`

Minimum closeout scope:

1. `GET /api/v1/workspaces`
   - list workspaces visible inside the active tenant context
   - return the active workspace id and default flag

2. `POST /api/v1/auth/context/switch`
   - accept target `workspace_id`
   - validate workspace belongs to the current tenant and caller has active tenant membership
   - issue a new token and return the same auth payload shape as login

3. convert remaining context-sensitive routes from `get_current_user()` to `get_current_principal()`
   - at minimum `jobs` and `metrics`
   - even if `metrics` remains tenant-wide, it should become explicit tenant-control-plane behavior rather than accidental loss of workspace context

4. expose provider scope clearly in API output
   - include `workspace_id` or a derived `scope`
   - otherwise workspace-aware provider behavior remains invisible and hard to reason about

### 2. What can stay out of Phase 3 closeout

These can reasonably move to the next phase:

- member invitation flow
- member removal flow
- role mutation flow
- workspace delete / archive
- full user list / deactivate UI
- separate workspace-level ACL model
- separate `operator` backend entity

Recommended next-phase name:

- `Phase 4 Access and Admin Control Plane`

### 3. Must-have foundation vs later enhancement

#### Must-have before closing Phase 3

- workspace list
- workspace switch
- principal-based scoping cleanup for remaining tenant-only routes
- clear provider ownership contract

#### Can be postponed

- invite/remove/change-role
- workspace CRUD beyond list/switch
- user directory / deactivation
- richer admin UI and audit flows

## Proposed Next Phase Design

### 1. Workspace should have a formal switch API

Yes. A formal switch API is necessary.

Recommended shape:

- `POST /api/v1/auth/context/switch`
- payload:
  - `workspace_id`
  - optionally later `tenant_id`
- response:
  - same shape as `POST /api/v1/auth/login`
  - new token
  - `user`
  - selected `workspace`
  - available `memberships`

Reason:

- the current token already carries `workspace_id`: [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py#L165)
- the frontend already stores workspace context: [LoginPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/LoginPage.tsx#L22)
- without a switch API, workspace is effectively fixed at login-time default resolution

### 2. Keep `tenant_membership` for now; do not introduce `workspace_membership` yet

Recommended near-term model:

- keep `User` as identity
- keep `TenantMembership` as the access-control source
- keep one default workspace per tenant
- allow all tenant members to access all workspaces in that tenant in the short term

Do **not** introduce `workspace_membership` in the next minimal step.

Reason:

- the spec already deferred workspace-specific membership
- the current main blocker is context operability, not fine-grained ACL complexity
- introducing a second membership layer now would slow down closeout and overfit ahead of proven product need

Add workspace-level ACL later only if the product truly needs:

- private workspaces
- workspace-specific admins
- restricted document/skill visibility inside one tenant

### 3. Product modeling for user / workspace member / admin / operator

Recommended pragmatic model:

- `User`
  - global login identity
  - status field remains `is_active`

- `TenantMembership`
  - real access row
  - roles: `owner`, `admin`, `member`

- `Workspace`
  - organization boundary for KB/document/skill/session/run/API key
  - not a separate identity surface

- `operator`
  - do not create as a separate backend entity
  - treat it as a product/UI label for a user acting with tenant or workspace admin privileges

If a later phase needs workspace-specific delegated admins, add that as:

- `workspace_admin` capability on a workspace ACL table
- not as a distinct `Operator` table

### 4. Ownership model clarity

#### Clear enough today

- Knowledge Base: workspace-owned and explicit: [knowledge_base.py](/Users/shaoqing/workspace/PageIndex/app/models/knowledge_base.py#L9)
- Skill: workspace-owned in service behavior: [skill_service.py](/Users/shaoqing/workspace/PageIndex/app/services/skill_service.py#L129)
- API key: workspace-owned in auth behavior: [auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py#L84)

#### Still unclear today

- Provider
  - model supports `workspace_id`
  - runtime respects workspace accessibility
  - management API is still tenant-wide
  - output schema hides workspace ownership

Recommended fix:

- expose `scope = tenant | workspace`
- if `scope=tenant`, persist `workspace_id = null`
- if `scope=workspace`, bind to active workspace

This is clearer than keeping an invisible nullable `workspace_id` contract.

#### Transitional but acceptable

- Document / Session / Run
  - workspace ownership exists
  - default workspace still sees legacy `NULL` rows
  - acceptable short term, but closeout should treat non-null workspace ownership as the end state

### 5. Minimal implementation order

Recommended order:

1. Add workspace list endpoint.
2. Add auth context switch endpoint and reuse the login response shape.
3. Change `jobs` and `metrics` to principal-aware behavior.
4. Expose provider scope in API schema and normalize provider semantics.
5. Add read-only tenant member list for owner/admin if bandwidth permits.
6. Move invite/remove/role-change/user-disable into Phase 4.

## Final Conclusion

### Direct answers

- `tenant isolation`: `partial`
- `workspace isolation`: `partial`

### Why

- tenant boundaries are broadly enforced in the main business resources, but some routes still fall back to `User.tenant_id` and the tenant lifecycle/switch/admin plane is unfinished
- workspace boundaries are real for several resources, but they only operate inside one implicit active workspace, still rely on default-workspace compatibility fallbacks, and do not yet have list/switch/admin surfaces

### Final verdict

**Phase 3 should add a closeout slice for workspace/operator management.**

Reason:

- the backend has already crossed the line from “no workspace model” to “workspace-aware foundation”
- stopping here leaves the system with hidden workspace context, stored memberships, and partially scoped resources, but no way to operate them as a product
- the minimum closeout needed is modest and focused: workspace list, workspace switch, and cleanup of remaining tenant-only routes
