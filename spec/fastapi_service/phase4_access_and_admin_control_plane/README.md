# Phase 4: Access, Admin, and Pre-Phase5 Closeout

## Goal

`Phase 4` is the parent stage that turns the PageIndex service from:

- tenant/workspace-aware in model
- partially operable in control plane
- strong in core document / KB / skill / chat capability

into a system that is:

- operationally usable for real tenant/workspace management
- explicit in access control and scope boundaries
- ready to enter `Phase 5` governance work without still carrying major control-plane debt

This parent stage should be managed as:

- `Phase 4 baseline`
- `Phase 4.5 Closeout, Management, and Control`
- `Phase 4.6 Tenant Directory and Access Portrait`
- `Phase 4.7 Pre-Phase5 Release Hardening`

`Phase 5` remains reserved for:

- audit platform
- governance
- export / import
- migration portability
- long-term platform operations

## Stage Boundary

### What must be true before Phase 5 starts

Before `Phase 5`, the service must not only have core product features such as:

- index / parse
- search / query
- knowledge bases
- skills
- skill chat
- multi-manual / compliance-oriented retrieval

It must also have a **real operational control plane** for:

- tenant visibility
- workspace visibility and switching
- user status and capability control
- membership-driven access resolution
- workspace lifecycle and management
- scope-safe resource ownership

In other words:

- `Phase 4.x` finishes product-operability
- `Phase 5` starts governance

### What Phase 4.x does not include

The following stay out of `Phase 4.x`:

- audit center / audit platform
- long-term governance workflows
- org tree / department tree / real team hierarchy
- heavy ACL platform
- quota / billing / chargeback
- policy engine
- export / import productization
- cross-instance migration tooling

## Current Code Reality

The current codebase already has substantial `Phase 4 baseline` coverage:

- `workspace_memberships`
- `workspace_invites`
- `Principal` with tenant + workspace membership context
- capability-based workspace authorization
- founder transfer
- workspace archive
- invite accept / revoke
- workspace list
- context switch
- workspace-scoped resource filtering on several routes

But the following still block a clean `Phase 5` handoff:

- DB-level hard constraints are still incomplete
- `User.tenant_id` still survives in runtime compatibility paths
- workspace create is not closed-loop yet
- platform-level backend management APIs do not exist yet
- tenant/user/workspace access portrait is not yet explicit
- closeout testing and release-hardening are not formalized

## Structure

### Core design docs

- [tenant_and_workspace_model.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/tenant_and_workspace_model.md)
- [workspace_access_control.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_access_control.md)
- [workspace_invitation_flow.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_invitation_flow.md)
- [workspace_admin_api.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_admin_api.md)
- [migration_plan.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/migration_plan.md)
- [workspace_operator_gap_audit.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_operator_gap_audit.md)

### Parent-stage management docs

- [phase4_master_stage_plan.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_master_stage_plan.md)
- [phase4_5_closeout_management_and_control.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_5_closeout_management_and_control.md)
- [phase4_6_tenant_directory_and_access_portrait.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_6_tenant_directory_and_access_portrait.md)
- [phase4_7_pre_phase5_release_hardening.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_pre_phase5_release_hardening.md)

### Execution support

- [phase4_backend_ai_prompt.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_backend_ai_prompt.md)
- [phase4_5_backend_execution_prompts.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_5_backend_execution_prompts.md)

## Recommended Sequence

1. Finish `Phase 4.5` backend closeout.
2. Finish `Phase 4.6` directory and access portrait.
3. Finish `Phase 4.7` release hardening and closeout testing.
4. Only then open `Phase 5`.

## Parent-stage Closeout Rule

`Phase 4` is not considered closed merely because the happy-path product works.

It is closed only when:

- control-plane behavior is explicit and operable
- access rules are membership-driven and explainable
- key runtime compatibility debt is reduced to controlled fallback only
- the environment can be reset and rebuilt reproducibly
- a full end-to-end verification chain passes on project-owned test data
