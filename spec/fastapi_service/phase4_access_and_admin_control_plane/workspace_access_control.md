# Workspace Access Control

## Scope

This document defines the Phase 4 access-control model built on top of the existing Phase 3 tenant/workspace foundation.

It covers:

- `tenant_memberships`
- `workspace_memberships`
- role model
- capability model
- `permissions_override`
- `visibility`
- principal resolution and authorization order

It does not cover:

- platform-wide admin console implementation
- email delivery infrastructure
- physical delete / purge flows

## Fixed Decisions

The following decisions are frozen for Phase 4 and must not be reopened during implementation:

1. Must introduce `workspace_memberships`.
2. `founder` is unique per workspace and supports transfer.
3. `guest` is an independent role, not simulated through overrides.
4. `KnowledgeBase.visibility` and `ChatSkill.visibility` use:
   - `private`
   - `workspace_read`
   - `workspace_edit`
5. `SkillChat` does not define separate visibility and inherits `Skill.visibility`.
6. Workspace delete in Phase 4 is `archive` only.
7. Invite must support not-yet-registered email targets.
8. `User` adds:
   - `can_create_workspace`
   - `is_platform_admin`
9. Non-default workspace backfill uses minimum-authorization backfill only.
10. Founder transfer demotes the previous founder to `admin`.
11. Invite acceptance is bound to the logged-in user's normalized email.
12. `User.email` is globally unique and case-insensitive.
13. `admin` cannot manage other `admin`.
14. `workspace_edit` visibility never raises capability above membership role/override.
15. Archived workspace becomes frozen; memberships remain for audit, invites become unusable.

## Access Model

### Layering

Phase 4 authorization is evaluated in three layers:

1. tenant access gate
2. workspace access gate
3. resource access gate

### Tenant access gate

Tenant access is controlled by `tenant_memberships`.

Responsibilities:

- determine whether a user can enter a tenant
- determine tenant-level administrative authority
- remain the control plane for tenant-scoped resources

Target role set remains:

- `owner`
- `admin`
- `member`

Target status set:

- `active`
- `disabled`
- `removed`

### Workspace access gate

Workspace access is controlled by `workspace_memberships`.

Responsibilities:

- determine whether a user can enter a workspace
- determine workspace-local role
- determine workspace-local capability defaults
- provide the base for resource management authority inside the workspace

Role set:

- `founder`
- `admin`
- `member`
- `guest`

Status set:

- `active`
- `disabled`
- `removed`

## Workspace Membership Model

### Required fields

`workspace_memberships` must include:

- `id`
- `workspace_id`
- `user_id`
- `role`
- `status`
- `permissions_override_json`
- `created_by`
- `created_at`
- `updated_at`

### Required constraints

- `UNIQUE(workspace_id, user_id)`
- one active founder per workspace

Recommended founder uniqueness enforcement:

- application-level invariant in every create/update/transfer path
- plus partial unique index where supported:
  - `UNIQUE(workspace_id) WHERE role='founder' AND status='active'`

### Founder semantics

Rules:

- every active workspace has exactly one active founder
- founder can transfer founder ownership
- founder transfer is transactional
- after founder transfer:
  - target member becomes `founder`
  - previous founder becomes `admin`

## Capability Model

### Capability keys

Phase 4 should normalize capability checks into a stable, explicit set of boolean capability keys.

Recommended key set:

- `can_view_workspace`
- `can_edit_workspace_metadata`
- `can_manage_members`
- `can_manage_invites`
- `can_transfer_founder`
- `can_archive_workspace`
- `can_manage_api_keys`
- `can_manage_providers`
- `can_manage_knowledge_bases`
- `can_manage_skills`
- `can_run_skills`
- `can_view_runs`

### Default role capability matrix

#### `founder`

- `can_view_workspace = true`
- `can_edit_workspace_metadata = true`
- `can_manage_members = true`
- `can_manage_invites = true`
- `can_transfer_founder = true`
- `can_archive_workspace = true`
- `can_manage_api_keys = true`
- `can_manage_providers = true`
- `can_manage_knowledge_bases = true`
- `can_manage_skills = true`
- `can_run_skills = true`
- `can_view_runs = true`

#### `admin`

- `can_view_workspace = true`
- `can_edit_workspace_metadata = true`
- `can_manage_members = true`
- `can_manage_invites = true`
- `can_transfer_founder = false`
- `can_archive_workspace = false`
- `can_manage_api_keys = true`
- `can_manage_providers = true`
- `can_manage_knowledge_bases = true`
- `can_manage_skills = true`
- `can_run_skills = true`
- `can_view_runs = true`

#### `member`

- `can_view_workspace = true`
- `can_edit_workspace_metadata = false`
- `can_manage_members = false`
- `can_manage_invites = false`
- `can_transfer_founder = false`
- `can_archive_workspace = false`
- `can_manage_api_keys = true`
- `can_manage_providers = false`
- `can_manage_knowledge_bases = true`
- `can_manage_skills = true`
- `can_run_skills = true`
- `can_view_runs = true`

#### `guest`

- `can_view_workspace = true`
- `can_edit_workspace_metadata = false`
- `can_manage_members = false`
- `can_manage_invites = false`
- `can_transfer_founder = false`
- `can_archive_workspace = false`
- `can_manage_api_keys = false`
- `can_manage_providers = false`
- `can_manage_knowledge_bases = false`
- `can_manage_skills = false`
- `can_run_skills = true`
- `can_view_runs = true`

Note:

- `guest` remains read-only at the resource management level
- `guest` may still read and run shared skills if visibility allows and service policy permits

## Permissions Override

### Storage model

`permissions_override_json` is stored on `workspace_memberships`.

Recommended shape:

```json
{
  "can_manage_api_keys": false,
  "can_manage_providers": false,
  "can_manage_knowledge_bases": true,
  "can_manage_skills": true
}
```

### Rules

- missing key means “use role default”
- only allow known capability keys
- overrides can reduce authority
- limited targeted elevation may be allowed for selected non-founder capabilities
- founder-only capabilities must never be elevated by override

Founder-only capabilities:

- `can_transfer_founder`
- `can_archive_workspace`

### Effective capability resolution

Capability resolution order:

1. start from workspace role default capability map
2. apply validated `permissions_override_json`
3. apply hard constraints from workspace status
4. apply resource visibility gate where relevant

## Visibility Model

### Visibility fields

Add `visibility` to:

- `knowledge_bases`
- `chat_skills`

Do not add `visibility` to:

- `chat_sessions`
- `chat_runs`
- `chat_messages`

Skill chat inherits `ChatSkill.visibility`.

### Enum

- `private`
- `workspace_read`
- `workspace_edit`

Default:

- `private`

### Meaning

#### `private`

- resource is available only to users who already have direct edit authority through ownership or admin-level management flow
- for Phase 4, recommended practical rule:
  - founder/admin can read and edit
  - creator may read/edit
  - general workspace readers do not gain access merely by being in the workspace

#### `workspace_read`

- all active workspace members may read
- write authority still depends on role capability

#### `workspace_edit`

- resource is eligible for workspace-wide editing
- but editing authority still depends on role capability and override

Frozen rule:

- `workspace_edit` must never raise authority above membership capability

### Effective permission formula

The effective permission is the intersection of:

- workspace membership role capability
- `permissions_override`
- resource visibility

In shorthand:

`effective_permission = role_capability ∩ permissions_override ∩ resource_visibility`

## Principal Design

### Current baseline

Current principal carries:

- `kind`
- `tenant_id`
- `workspace_id`
- `membership_role`
- `user`
- optional `api_key`

### Phase 4 extension

Principal should be extended to include:

- `tenant_membership_role`
- `tenant_membership_status`
- `workspace_membership_role`
- `workspace_membership_status`
- `workspace_permissions`
- optional `workspace_membership_id`

Implementation note:

- keep backwards compatibility where possible
- `membership_role` may be retained temporarily as an alias for the tenant role or removed after downstream cleanup

## Authorization Chain

### Resolution order

`require_principal()` should resolve in this order:

1. authenticate bearer token or API key
2. load user
3. resolve active tenant membership
4. resolve target workspace
5. resolve active workspace membership
6. reject if:
   - tenant membership missing or inactive
   - workspace missing
   - workspace does not belong to tenant
   - workspace membership missing or inactive
   - workspace is archived for active operations
7. compute workspace capabilities
8. return fully resolved principal

### Archived workspace behavior

Frozen rule:

- archived workspace is frozen

Implications:

- no new resources
- no updates
- no new invites
- pending invites cannot be accepted
- memberships remain stored for audit/history
- active collaboration entry is blocked by access-control checks

Recommended implementation:

- do not require bulk status mutation on memberships at archive time
- block operational access centrally based on `workspace.status == archived`

## Action Guard Rules

### Founder-only actions

- founder transfer
- workspace archive
- promote any member to `admin`
- demote or remove an existing `admin`
- any action affecting the founder record itself

Allowed alternative actor:

- future `is_platform_admin`

### Admin-allowed actions

- invite `member` or `guest`
- remove `member` or `guest`
- change `member <-> guest`
- manage workspace resources and metadata within granted capabilities

Admin is explicitly not allowed to:

- create another admin
- demote another admin
- remove another admin
- transfer founder
- archive workspace

### Guest behavior

Guest is read-only by default.

Guest can:

- read `workspace_read` and `workspace_edit` resources
- read and participate in explicitly shareable read flows allowed by service policy

Guest cannot:

- edit KB/Skill resources
- manage invites, members, providers, API keys, or workspace metadata

## Recommended Service Hooks

To keep the Phase 4 rollout minimally invasive, add a reusable access-control service rather than introducing decorator-heavy RBAC.

Recommended service helpers:

- `resolve_workspace_capabilities(principal)`
- `require_workspace_capability(principal, capability_key)`
- `can_read_knowledge_base(principal, knowledge_base)`
- `can_edit_knowledge_base(principal, knowledge_base)`
- `can_read_skill(principal, skill)`
- `can_edit_skill(principal, skill)`
- `assert_workspace_active(workspace)`

Service-layer checks should remain the primary enforcement layer for visibility and capability.
