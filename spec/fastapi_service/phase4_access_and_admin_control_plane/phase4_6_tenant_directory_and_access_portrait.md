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

## 4. Explicit Non-Goals

`Phase 4.6` does not do:

- org tree
- department tree
- team hierarchy
- quota or billing
- audit center
- policy engine
- approval workflow

## 5. API Direction

Suggested minimum backend contracts:

- `GET /api/v1/platform/tenants`
- `GET /api/v1/platform/tenants/{tenant_id}`
- `GET /api/v1/platform/users/{user_id}/access-portrait`
- `GET /api/v1/platform/workspaces/{workspace_id}/access-portrait`

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
