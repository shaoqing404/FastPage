# Phase 4.5 Backend Execution Prompts

These prompts are intended for implementation agents working under the `Phase 4.5` plan.

All prompts assume repository root:

- `/Users/shaoqing/workspace/PageIndex`

## Prompt 1: Batch 4.5-A Constraint Hardening

### Task type

`Phase 4.5 / Batch 4.5-A / backend implementation`

### Specs to read

- [phase4_master_stage_plan.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_master_stage_plan.md)
- [phase4_5_closeout_management_and_control.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_5_closeout_management_and_control.md)
- [workspace_access_control.md](spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_access_control.md)
- [workspace_invitation_flow.md](spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_invitation_flow.md)
- [migration_plan.md](spec/fastapi_service/phase4_access_and_admin_control_plane/migration_plan.md)

### Files to inspect

- `migrations/versions/20260409_0006_phase4_schema_foundation.py`
- `migrations/versions/20260410_0007_phase4_backfill_membership_visibility.py`
- `app/models/user.py`
- `app/models/workspace_membership.py`
- `app/models/workspace_invite.py`
- `app/services/workspace_admin_service.py`
- `app/services/workspace_invite_service.py`
- `tests/phase4/*`

### Allowed write scope

- `migrations/versions/*`
- `app/models/user.py`
- `app/models/workspace_membership.py`
- `app/models/workspace_invite.py`
- `app/services/workspace_admin_service.py`
- `app/services/workspace_invite_service.py`
- `tests/phase4/*`

### Do not touch

- frontend
- compliance flows
- chat queue architecture
- platform admin routers

### Implementation goals

- harden `User.email` normalization + uniqueness
- harden one-active-founder invariant
- harden one-pending-invite-per-normalized-email-per-workspace invariant
- keep SQLite + MySQL compatibility explicit

### Acceptance criteria

- migration path is explicit and safe
- tests cover happy path and conflict path
- implementation does not expand into later Phase 4.5 batches

## Prompt 2: Batch 4.5-B Context And Compat Cleanup

### Task type

`Phase 4.5 / Batch 4.5-B / backend implementation`

### Specs to read

- [phase4_master_stage_plan.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_master_stage_plan.md)
- [phase4_5_closeout_management_and_control.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_5_closeout_management_and_control.md)
- [workspace_access_control.md](spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_access_control.md)

### Files to inspect

- `app/core/auth.py`
- `app/core/principal.py`
- `app/api/routers/auth.py`
- `app/api/routers/workspaces.py`
- `app/services/workspace_membership_service.py`
- `app/services/chat_service.py`
- `app/services/session_service.py`

### Allowed write scope

- `app/core/auth.py`
- `app/api/routers/auth.py`
- `app/api/routers/workspaces.py`
- `app/services/workspace_membership_service.py`
- `app/services/chat_service.py`
- `app/services/session_service.py`
- `tests/phase4/*`

### Do not touch

- migrations unrelated to compat cleanup
- workspace create
- platform admin backend
- frontend

### Implementation goals

- add or finalize context contract needed for stable frontend/runtime behavior
- reduce runtime dependence on `User.tenant_id`
- ensure principal/membership is the primary source of access truth

### Acceptance criteria

- cross-tenant invite accept remains correct
- context switch remains correct
- chat/session/run scoping no longer depends on compat field as primary runtime truth

## Prompt 3: Batch 4.5-C Workspace Create

### Task type

`Phase 4.5 / Batch 4.5-C / backend implementation`

### Specs to read

- [phase4_master_stage_plan.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_master_stage_plan.md)
- [phase4_5_closeout_management_and_control.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_5_closeout_management_and_control.md)

### Files to inspect

- `app/models/user.py`
- `app/api/routers/workspaces.py`
- `app/services/workspace_admin_service.py`
- `app/core/auth.py`
- `app/schemas/workspaces.py`
- `tests/phase4/*`

### Allowed write scope

- `app/api/routers/workspaces.py`
- `app/services/workspace_admin_service.py`
- `app/schemas/workspaces.py`
- `app/core/auth.py`
- `tests/phase4/*`

### Do not touch

- platform admin backend
- frontend
- unrelated resource services

### Implementation goals

- implement workspace create API
- enforce `can_create_workspace` and `is_platform_admin` behavior
- make creator the founder of the new workspace
- return or enable immediate context handoff into the new workspace

### Acceptance criteria

- authorized user can self-create workspace
- unauthorized user gets explicit denial
- created workspace is immediately operable

## Prompt 4: Batch 4.5-D Platform Admin Backend

### Task type

`Phase 4.5 / Batch 4.5-D / backend implementation`

### Specs to read

- [phase4_master_stage_plan.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_master_stage_plan.md)
- [phase4_5_closeout_management_and_control.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_5_closeout_management_and_control.md)
- [phase4_6_tenant_directory_and_access_portrait.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_6_tenant_directory_and_access_portrait.md)

### Files to inspect

- `app/models/user.py`
- `app/models/tenant_membership.py`
- `app/models/workspace.py`
- `app/models/workspace_membership.py`
- `app/models/workspace_invite.py`
- `app/api/routers/*`
- `app/main.py`

### Allowed write scope

- `app/api/routers/platform_*.py`
- `app/services/platform_*.py`
- `app/schemas/platform_*.py`
- `app/main.py`
- `tests/phase4/*`

### Do not touch

- frontend
- audit platform
- export/import
- governance workflow

### Implementation goals

- add minimum platform backend for users, workspaces, and tenant directory
- support only operational control, not governance expansion

### Acceptance criteria

- platform admin can inspect users/workspaces/tenants
- platform admin can update allowed Phase 4.5 controls only
- no drift into Phase 5 governance features
