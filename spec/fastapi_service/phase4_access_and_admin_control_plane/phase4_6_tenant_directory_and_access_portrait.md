# Phase 4.6 Tenant Directory and Access Portrait

## 1. Positioning

`Phase 4.6` sits between:

- `Phase 4.5` operational closeout
- `Phase 4.7` release hardening

Its role is to make the already-landed access/control-plane model:

- visible
- explainable
- manageable at tenant/workspace/user relationship level

It does **not** introduce:

- a real `Team` entity
- organization tree
- department hierarchy
- governance workflows

It also does **not** absorb work that `Phase 4.5` has already chosen to close:

- invite claim / self-registration entry
- password reset / change-password lifecycle
- KB / Documents page information-architecture restructuring
- basic platform user password operations

Current closeout note (`2026-04-17`):

- `Phase 4.6` is `GO`
- the phase has landed as explicit portrait/directory read surface, not as a new management-write phase
- runtime/API/frontend verification has been completed against the current local control-plane surface
- any further work on this area now belongs to `Phase 4.7` hardening unless a regression is found

## 2. Why This Phase Exists

`Phase 4.5` can make the backend operable, but that still leaves one important gap:

- platform operators and developers must be able to explain the active access state of the system

Without this, the service remains difficult to operate because it is hard to answer:

- which tenant a user belongs to
- which workspaces they can enter
- what their tenant role is
- what their workspace role is
- what effective capabilities they have
- why a given action is allowed or denied

That visibility is not governance; it is part of a real control plane.

## 3. Scope

### 3.1 Tenant directory

Need:

- tenant list
- tenant detail
- tenant-level workspace summary
- tenant-level user summary

### 3.2 User access portrait

Need:

- user detail
- visible tenant memberships
- visible workspace memberships
- current platform flags
  - `is_active`
  - `can_create_workspace`
  - `is_platform_admin`
- effective access portrait for current or target context

### 3.3 Workspace access portrait

Need:

- founder/admin/member/guest membership summary
- invite summary
- archive state visibility
- capability summary

### 3.4 Resource ownership contract clarification

Need:

- provider scope clarity
- API key scope clarity
- session/run visibility explanation
- KB / skill visibility explanation

This clarification is about explainability and inspectability.

It is not a second frontend rewrite of the KB / Documents management pages.

## 4. Explicit Non-Goals

`Phase 4.6` does not do:

- org tree
- department tree
- team hierarchy
- quota or billing
- audit center
- policy engine
- approval workflow
- invite onboarding product flow
- reset-password / change-password product flow
- generic account activation UX
- KB selector / KB detail / Documents IA redesign

## 5. API Direction

Suggested minimum backend contracts:

- `GET /api/v1/platform/tenants`
- `GET /api/v1/platform/tenants/{tenant_id}`
- `GET /api/v1/platform/users/{user_id}/access-portrait`
- `GET /api/v1/platform/workspaces/{workspace_id}/access-portrait`

Implemented closeout surface (`2026-04-17`):

- `GET /api/v1/platform/tenants`
- `GET /api/v1/platform/tenants/{tenant_id}`
- `GET /api/v1/platform/users/{user_id}/access-portrait`
- `GET /api/v1/platform/workspaces/{workspace_id}/access-portrait`

Implementation rule confirmed in closeout:

- existing `Phase 4.5` list/detail APIs remain in place
- `Phase 4.6` adds normalized portrait reads rather than reopening onboarding or management-write scope

Important boundary:

- if existing list/detail APIs from `Phase 4.5` already expose enough relationship truth, `Phase 4.6` may extend them instead of introducing duplicate portrait APIs
- `Phase 4.6` should prefer normalized effective-portrait read APIs, not new onboarding or management mutations

Shape guidance:

- the API should expose raw membership rows where useful
- the API should also expose a normalized effective portrait
- do not require the frontend to recompute capability truth from scattered fields

## 6. Data and Runtime Rules

### 6.1 Source of truth

Access portrait must be derived from:

- `TenantMembership`
- `WorkspaceMembership`
- platform flags on `User`
- capability resolution logic

Not from:

- stale login-time cache only
- `User.tenant_id` compat fallback

### 6.2 Team-like semantics

For `Phase 4.6`, "team-like management" means:

- workspace as collaboration boundary
- membership and capability as team-like access surface

It does not mean:

- introducing a `Team` model
- pretending workspaces are departments or org nodes

## 7. Acceptance Standard

`Phase 4.6` is complete when:

- a platform operator can inspect tenant/workspace/user relationship truth
- a developer can explain allowed/denied actions from API output alone
- user access portraits no longer depend on manual DB inspection
- this visibility still stays inside `Phase 4` control-plane scope and does not drift into `Phase 5` governance
- there is no remaining confusion that invite onboarding, password lifecycle, or KB / Documents page restructuring belongs here if it already landed in `Phase 4.5`

Closeout record (`2026-04-17`):

- the backend contract suite passed
- migration hygiene passed
- frontend build passed
- real runtime verification confirmed portrait payloads on the live API surface
- non-platform-admin and API-key access to portrait routes returned `403`
- no additional `Phase 4.6` product/API work is required before entering `Phase 4.7`
