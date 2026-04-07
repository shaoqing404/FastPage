# Tenant And Workspace Model

## Current-State Audit

This audit is based on the current FastAPI code, not on the intended Phase 1 or Phase 3 wording alone.

### 1. The code is tenant-aware in schema and query filters

Current persisted business objects already carry `tenant_id`:

- `Tenant` in [app/models/tenant.py](/Users/shaoqing/workspace/PageIndex/app/models/tenant.py)
- `User` in [app/models/user.py](/Users/shaoqing/workspace/PageIndex/app/models/user.py)
- `ApiKey` in [app/models/api_key.py](/Users/shaoqing/workspace/PageIndex/app/models/api_key.py)
- `ModelProvider` in [app/models/model_provider.py](/Users/shaoqing/workspace/PageIndex/app/models/model_provider.py)
- `Document` in [app/models/document.py](/Users/shaoqing/workspace/PageIndex/app/models/document.py)
- `ChatSkill` in [app/models/chat_skill.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_skill.py)
- `ChatSession` and `ChatMessage` in [app/models/chat_session.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_session.py)
- `ChatRun` in [app/models/chat_run.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_run.py)
- `ParseJob` in [app/models/parse_job.py](/Users/shaoqing/workspace/PageIndex/app/models/parse_job.py)

Service and router code generally enforce tenant-bounded reads and writes:

- documents filter on `current_user.tenant_id` in [app/api/routers/documents.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/documents.py)
- jobs filter on `current_user.tenant_id` in [app/api/routers/jobs.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/jobs.py)
- skills filter on `current_user.tenant_id` in [app/api/routers/skills.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/skills.py)
- runs and sessions filter on principal tenant in [app/api/routers/chat.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/chat.py)
- provider CRUD is tenant-scoped in [app/services/provider_service.py](/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py)
- overview metrics aggregate by tenant in [app/api/routers/metrics.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/metrics.py)

Artifact storage is also tenant-first:

- local filesystem paths are `.../tenants/{tenant_id}/...`
- object storage keys are `tenants/{tenant_id}/...`
- see [app/services/storage_service.py](/Users/shaoqing/workspace/PageIndex/app/services/storage_service.py)

### 2. The product is still effectively single-tenant in identity and bootstrap

The tenant-aware tables do not yet add up to a real multi-tenant product.

#### Bootstrap is single-tenant

[app/core/bootstrap.py](/Users/shaoqing/workspace/PageIndex/app/core/bootstrap.py) currently:

- creates exactly one tenant: `tenant_default`
- creates exactly one user: `user_default`
- binds that user directly to `tenant_default`
- creates or syncs the system-managed provider only inside `tenant_default`

This is a valid local bootstrap path, but it is not a tenant lifecycle model.

#### Login is single-admin, not true user auth

[app/core/auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py) currently:

- loads a `User` by username
- then ignores `user.password_hash` as a product credential source
- accepts login only if submitted credentials exactly match `settings.admin_username` and `settings.admin_password`

Implications:

- extra rows in `users` are not truly first-class login identities
- the application has a `users` table but not real multi-user auth behavior
- JWT tenant context comes from `user.tenant_id`, so tenant selection is hard-bound to the single tenant attached to that user row

#### Principal only supports one tenant and has no workspace notion

[app/core/principal.py](/Users/shaoqing/workspace/PageIndex/app/core/principal.py) currently contains:

- `kind`
- `tenant_id`
- `user`
- optional `api_key`

There is no:

- active workspace
- membership role
- tenant switching
- workspace switching

### 3. Tenant-aware currently means “single tenant per user row”

`User` in [app/models/user.py](/Users/shaoqing/workspace/PageIndex/app/models/user.py) has a required `tenant_id`.

That means:

- one user row can only belong to one tenant
- there is no tenant membership table
- there is no model for a user belonging to multiple tenants
- ownership and access control are inferred from one direct foreign key rather than a membership relation

### 4. There is no workspace concept in code today

There is no `Workspace` model, no `workspace_id` columns, and no workspace-scoped filtering in:

- documents
- parse jobs
- skills
- sessions
- runs
- messages
- providers
- API keys

Phase 3.1 therefore needs to add workspace as a new concept rather than “activate” an already latent one.

### 5. Ownership exists, but not consistently

Current ownership fields:

- `Document.owner_user_id`
- `ChatSkill.owner_user_id`
- `ChatSession.user_id`
- `ChatRun.user_id`
- `ChatMessage.user_id`
- `ApiKey.created_by`

Current gaps:

- `ModelProvider` is tenant-owned but has no explicit creator or owner field
- `ApiKey` is tenant-owned but not workspace-owned
- sessions and messages use `user_id`, but listing is still tenant-wide rather than user-private

### 6. Session visibility is wider than future workspace/team semantics likely want

[app/services/session_service.py](/Users/shaoqing/workspace/PageIndex/app/services/session_service.py) currently lists sessions by:

- `tenant_id`
- optional `skill_id`

It does not filter by:

- `user_id`
- workspace
- sharing/membership policy

As a result, any principal within the same tenant can currently list sessions and messages for that tenant. This is still tenant-safe, but it is not yet workspace-aware and it is broader than likely end-state visibility rules.

### 7. Provider resolution is tenant-local, with env fallback

[app/services/provider_service.py](/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py) currently resolves providers in this order:

1. `skill.provider_id`
2. explicit request provider
3. tenant default provider where `is_default = true`
4. process env fallback from `settings.llm_base_url` and `settings.llm_api_key`

This means:

- provider ownership is tenant-scoped only
- there is no workspace-specific provider layer
- env fallback is still part of runtime behavior, not only bootstrap compatibility

### 8. Existing API shape is good for compatibility and should be preserved

Current routes infer tenant from auth context rather than exposing `tenant_id` in path parameters. This is already the correct compatibility shape for future tenant/workspace evolution.

Relevant examples:

- [app/api/routers/auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py)
- [app/api/routers/documents.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/documents.py)
- [app/api/routers/skills.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/skills.py)
- [app/api/routers/chat.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/chat.py)
- [app/api/routers/providers.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/providers.py)

### Current-state conclusion

The system is already tenant-aware in:

- schema
- most service filters
- storage layout
- provider lookup

But it is still single-tenant as a product because:

- bootstrap assumes one default tenant
- login assumes one global admin credential pair
- user-to-tenant relation is one-to-one
- there is no workspace abstraction
- there is no membership model

The code is therefore best described as:

**tenant-aware implementation discipline inside an effectively single-tenant product shell**

## Target Model

### 1. Tenant and workspace remain separate concepts

Phase 3.1 should not merge tenant and workspace.

Definitions:

- `Tenant`: hard isolation boundary for data, providers, API keys, metrics, and future quotas/billing
- `Workspace`: collaboration and resource organization boundary inside a single tenant

Reasons, based on current code:

- current storage layout is already tenant-rooted
- current schema and service code consistently use `tenant_id` as the isolation key
- replacing tenant with workspace would force broad semantic rewrites across auth, storage, providers, and nearly every model

Decision:

- keep `tenant_id` as the hard isolation key
- add `workspace_id` to tenant-owned business resources
- require one default workspace per tenant

### 2. A user may belong to multiple tenants

Phase 3.1 should support one global user belonging to multiple tenants.

Target modeling:

- `users` becomes the global identity table
- a new `tenant_memberships` table becomes the source of truth for tenant access
- `users.tenant_id` is retained temporarily only for migration compatibility

This is necessary because the current direct `users.tenant_id` binding prevents any real multi-tenant product behavior beyond separate seeded users.

### 3. Tenant creation policy

Phase 3.1 should allow:

- first-run bootstrap creation when no tenant exists
- authenticated user creation of a new tenant, with the creator becoming tenant owner

This keeps the current local/dev bootstrap path viable while removing the assumption that every installation revolves around one preconfigured default tenant forever.

### 4. Membership and role model

Add `tenant_memberships` with:

- `id`
- `tenant_id`
- `user_id`
- `role`
- `status`
- `created_by`
- `created_at`
- `updated_at`

Phase 3.1 role set:

- `owner`
- `admin`
- `member`

Behavior:

- tenant access requires an active membership
- owner and admin can manage members, workspaces, tenant defaults, tenant-level providers, and tenant-level API keys
- member can use resources inside permitted workspaces

Workspace membership is explicitly deferred in Phase 3.1. Tenant membership is sufficient if all members can access the tenant default workspace and any later-created workspace policy remains simple.

### 5. Workspace model

Add `workspaces` with:

- `id`
- `tenant_id`
- `name`
- `slug`
- `status`
- `is_default`
- `created_by`
- `default_provider_id`
- `created_at`
- `updated_at`

Rules:

- every tenant must have exactly one default workspace
- workspace belongs to exactly one tenant
- workspace cannot cross tenant boundaries

### 6. Ownership model

#### Tenant

- owns workspaces
- owns providers
- owns API keys
- owns business resources transitively

#### Workspace

- groups business resources within a tenant
- can have a workspace-level default provider

#### User attribution

Retain existing user attribution on resources:

- `Document.owner_user_id`
- `ChatSkill.owner_user_id`
- `ChatSession.user_id`
- `ChatRun.user_id`
- `ChatMessage.user_id`
- `ApiKey.created_by`

This preserves auditability while introducing tenant/workspace as the primary access boundary.

### 7. Workspace-scoped resource model

Add `workspace_id` to:

- `api_keys`
- `documents`
- `parse_jobs`
- `chat_skills`
- `chat_sessions`
- `chat_messages`
- `chat_runs`

Add `workspace_id` to `model_providers` as nullable:

- `NULL` means tenant-level provider
- non-`NULL` means workspace-scoped provider

This keeps current provider storage in one table and avoids a separate provider inheritance table in Phase 3.1.

### 8. Default provider inheritance

Provider fallback should become:

1. skill-specific provider
2. explicit request provider
3. workspace default provider
4. tenant default provider
5. env fallback

Rules:

- skill provider must belong to the same tenant and same workspace or be tenant-level in that tenant
- explicit request provider follows the same rule
- workspace default provider must belong to the same tenant and workspace
- tenant default provider must belong to the same tenant and have `workspace_id = NULL`
- env fallback remains only as a compatibility backstop for incomplete setup and bootstrap

### 9. API key ownership

API keys remain tenant-owned but become workspace-bound at issuance time.

Target model for `api_keys`:

- `tenant_id`
- `workspace_id`
- `created_by`

Resolved principal from API key must include:

- tenant
- workspace
- owning user attribution

This avoids ambiguous “tenant-wide but workspace-less” service credentials once workspaces exist.

### 10. Principal model

`Principal` should be extended from the current structure to include:

- `tenant_id`
- `workspace_id`
- `membership_role`
- `user`
- optional `api_key`
- existing `kind`

This keeps [app/api/deps.py](/Users/shaoqing/workspace/PageIndex/app/api/deps.py) stable while allowing the rest of the application to rely on one resolved context object.

## API And Migration Plan

### 1. Existing APIs that must remain compatible

These existing routes must keep working without tenant or workspace path parameters:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/apikeys`
- `GET /api/v1/auth/apikeys`
- `DELETE /api/v1/auth/apikeys/{key_id}`
- `POST /api/v1/documents/upload`
- document CRUD and parse endpoints
- skill CRUD endpoints
- chat run and session endpoints
- provider CRUD endpoints
- metrics endpoints

Compatibility rule:

- tenant and workspace must be inferred from auth context
- clients that do not know about workspace should transparently operate in the default workspace for the current tenant

Allowed additive response changes:

- add `workspace_id`
- add membership or context metadata to auth responses

Not allowed in Phase 3.1:

- forcing callers to send `tenant_id` path parameters for existing endpoints
- breaking current auth header conventions

### 2. New APIs to add

#### Tenant lifecycle

- `POST /api/v1/tenants`
- `GET /api/v1/tenants`
- `GET /api/v1/tenants/{tenant_id}`

#### Tenant membership

- `GET /api/v1/tenants/{tenant_id}/members`
- `POST /api/v1/tenants/{tenant_id}/members`
- `PATCH /api/v1/tenants/{tenant_id}/members/{membership_id}`

#### Workspace lifecycle

- `POST /api/v1/workspaces`
- `GET /api/v1/workspaces`
- `GET /api/v1/workspaces/{workspace_id}`
- `PATCH /api/v1/workspaces/{workspace_id}`

#### Context selection

One of the following must exist:

- login response includes memberships and default workspace context
- or a dedicated `POST /api/v1/auth/context/switch`

Recommended for Phase 3.1:

- keep `POST /api/v1/auth/login`
- extend its response with available tenant memberships and the selected default workspace
- add `POST /api/v1/auth/context/switch` for later tenant/workspace switching without re-login

#### Provider extensions

Provider routes may be extended additively with:

- `GET /api/v1/model-providers?workspace_id=...`
- `POST /api/v1/model-providers` accepting nullable `workspace_id`

Default behavior without `workspace_id`:

- operate on tenant-level providers for compatibility

### 3. Auth changes

#### Login validation

[app/core/auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py) should stop using the global admin credential pair as the only accepted login.

Target behavior:

- validate submitted password against the stored user credential
- resolve active tenant membership
- resolve active workspace inside that tenant

This is the single biggest step required to turn the existing `users` table into a real product identity model.

#### JWT payload

JWT should carry:

- `sub`
- `user_id`
- `tenant_id`
- `workspace_id`
- optional `membership_role`
- current `jti`, `iat`, `exp`

#### Principal resolution

`require_principal()` should:

- verify user or API key
- resolve active membership
- resolve active workspace
- reject access if membership is missing or inactive
- reject access if workspace does not belong to that tenant

### 4. Authorization rules

#### Tenant boundary

Tenant remains the hard boundary for:

- documents
- jobs
- skills
- providers
- sessions
- runs
- traces
- metrics
- API keys

#### Workspace boundary

Workspace becomes the second boundary inside a tenant for:

- documents
- jobs
- skills
- sessions
- messages
- runs
- API keys
- workspace-scoped providers

#### Session visibility

Phase 3.1 should tighten session access from current tenant-wide visibility to at least workspace-bounded visibility.

Recommended rule for Phase 3.1:

- list and read sessions within the current workspace only
- retain user attribution
- defer richer sharing semantics to a later phase

This avoids introducing team-wide leakage inside tenants once multiple workspaces exist.

### 5. Bootstrap degradation plan

[app/core/bootstrap.py](/Users/shaoqing/workspace/PageIndex/app/core/bootstrap.py) must be adjusted without breaking existing local/dev installs.

Target bootstrap behavior:

- if no tenant exists:
  - create one tenant
  - create one default workspace
  - create one initial owner membership
  - optionally create one system-managed provider from env
- if legacy `tenant_default` exists:
  - preserve it
  - create its default workspace
  - backfill existing tenant-owned rows into that workspace
  - create tenant membership rows for existing users

Env fallback should remain supported, but only as:

- first-run compatibility
- provider bootstrap backstop

It should no longer be the main long-term ownership model for provider defaults.

### 6. Data migration strategy

Migration should be additive first and tightening later.

#### Step 1. Add tables

Add:

- `workspaces`
- `tenant_memberships`

#### Step 2. Add nullable `workspace_id`

Add nullable `workspace_id` to:

- `api_keys`
- `documents`
- `parse_jobs`
- `chat_skills`
- `chat_sessions`
- `chat_messages`
- `chat_runs`
- `model_providers`

#### Step 3. Create default workspace per existing tenant

For each existing tenant:

- create one workspace
- mark it as default

#### Step 4. Backfill workspace ownership

For each existing tenant-owned row:

- set `workspace_id` to that tenant’s default workspace

This applies to:

- documents
- parse jobs
- skills
- sessions
- messages
- runs
- API keys
- providers, initially as tenant-level or default-workspace-scoped according to chosen rule

Recommended provider rule:

- existing providers stay tenant-level with `workspace_id = NULL`
- workspace default pointer can still reference a tenant-level provider if needed for compatibility

#### Step 5. Backfill memberships

For each existing user:

- create membership for `users.tenant_id`
- assign bootstrap admin user as `owner`
- assign any non-bootstrap legacy users as `member` or `admin` according to migration policy

Recommended default:

- bootstrap-created default user becomes `owner`
- all others become `member`

#### Step 6. Switch runtime reads and writes

After backfill:

- all new writes must include `tenant_id` and `workspace_id`
- all reads must filter on both where applicable

#### Step 7. Tighten non-null constraints later

Once runtime uses `workspace_id` everywhere:

- make `workspace_id` non-null on core business tables

#### Step 8. Keep `users.tenant_id` temporarily

Do not remove `users.tenant_id` in Phase 3.1.

Use it only for:

- migration backfill
- temporary compatibility logic

Do not use it as the long-term access-control source of truth after membership-based auth is in place.

### 7. Code touch points for Phase 3.1

#### Bootstrap

- [app/core/bootstrap.py](/Users/shaoqing/workspace/PageIndex/app/core/bootstrap.py)

Needs:

- workspace creation/backfill
- membership creation/backfill
- compatibility bootstrap for existing default tenant

#### Auth

- [app/core/auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py)
- [app/api/deps.py](/Users/shaoqing/workspace/PageIndex/app/api/deps.py)
- [app/core/principal.py](/Users/shaoqing/workspace/PageIndex/app/core/principal.py)

Needs:

- stored credential validation
- membership-aware principal resolution
- workspace-aware JWT and principal context

#### Models

- [app/models/tenant.py](/Users/shaoqing/workspace/PageIndex/app/models/tenant.py)
- [app/models/user.py](/Users/shaoqing/workspace/PageIndex/app/models/user.py)
- [app/models/api_key.py](/Users/shaoqing/workspace/PageIndex/app/models/api_key.py)
- [app/models/model_provider.py](/Users/shaoqing/workspace/PageIndex/app/models/model_provider.py)
- [app/models/document.py](/Users/shaoqing/workspace/PageIndex/app/models/document.py)
- [app/models/chat_skill.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_skill.py)
- [app/models/chat_session.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_session.py)
- [app/models/chat_run.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_run.py)
- [app/models/parse_job.py](/Users/shaoqing/workspace/PageIndex/app/models/parse_job.py)

Needs:

- workspace and membership schema additions
- compatibility-safe nullable introduction first

#### Services

- [app/services/provider_service.py](/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py)
- [app/services/document_service.py](/Users/shaoqing/workspace/PageIndex/app/services/document_service.py)
- [app/services/skill_service.py](/Users/shaoqing/workspace/PageIndex/app/services/skill_service.py)
- [app/services/session_service.py](/Users/shaoqing/workspace/PageIndex/app/services/session_service.py)
- [app/services/chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py)

Needs:

- workspace-aware filtering
- provider inheritance
- tighter visibility rules

#### Routers

- [app/api/routers/auth.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/auth.py)
- [app/api/routers/providers.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/providers.py)
- existing chat/document/skill/job routes

Needs:

- additive lifecycle endpoints
- compatibility-safe workspace handling

## Acceptance Criteria

### 1. Current-state audit completeness

The Phase 3.1 implementation must align with the audited current reality:

- tenant-aware tables and query filters are preserved
- login is recognized as the main single-tenant bottleneck
- bootstrap is recognized as single-default-tenant behavior
- provider fallback is recognized as tenant-local plus env compatibility fallback
- session visibility is recognized as currently tenant-wide

### 2. Target model acceptance

The system supports:

- at least two tenants existing simultaneously
- one default workspace per tenant
- one user belonging to multiple tenants through memberships
- one active tenant and one active workspace in the resolved principal
- tenant-owned and workspace-attributed writes for documents, jobs, skills, sessions, runs, and API keys
- provider resolution order:
  - skill provider
  - explicit request provider
  - workspace default
  - tenant default
  - env fallback

### 3. Compatibility acceptance

Existing clients remain functional because:

- current document, skill, chat, provider, auth, and metrics endpoints remain available
- existing callers do not need to send tenant or workspace path parameters
- legacy single-tenant data migrates into one default workspace without data loss
- existing API keys remain usable after backfill by receiving the tenant’s default workspace

### 4. Isolation acceptance

After Phase 3.1:

- cross-tenant access remains rejected everywhere
- cross-workspace access is rejected for workspace-bound resources
- tenant access is governed by active membership, not solely by `users.tenant_id`
- provider selection rejects cross-tenant and cross-workspace references

### 5. Bootstrap acceptance

Fresh install:

- creates initial tenant, default workspace, owner membership, and optional env-backed provider bootstrap

Existing install:

- preserves `tenant_default`
- creates a default workspace for it
- backfills existing tenant-owned rows
- creates membership rows for existing users

### 6. Non-goals for Phase 3.1

Phase 3.1 does not need to implement:

- full enterprise RBAC
- workspace-specific membership model
- billing
- quota enforcement
- frontend redesign

It does need to establish the durable backend model those later features can build on.
