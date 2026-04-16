# Phase 4 Master Stage Plan

## 1. Positioning

This document manages `Phase 4` as a parent stage rather than a single implementation batch.

The reason is simple:

- `Phase 4 baseline` landed the main access/admin path
- `Phase 4.5` must close the operational gaps
- `Phase 4.6` must make tenant/workspace/user access portraits explicit
- `Phase 4.7` must harden and standardize closeout before `Phase 5`

This avoids mixing:

- unfinished control-plane work
- pre-governance release hardening
- future governance and audit platform work

## 2. Core Phase 4 Boundary

`Phase 4` is responsible for:

- access model
- workspace admin model
- membership and capability model
- invitation and context handoff
- platform minimum control plane
- directory and access portrait needed for real operation
- pre-Phase5 hardening and closeout verification

`Phase 5` is responsible for:

- audit center
- governance workflows
- export / import productization
- migration portability
- long-term operational analytics

## 3. Design Domain Split

### Domain A: Identity / Auth / Principal

Includes:

- `User`
- login/session auth
- `TenantMembership`
- `WorkspaceMembership`
- `Principal`
- token/context handoff
- compatibility-field retirement

Key goal:

- membership becomes the runtime source of truth

### Domain B: Tenant / Workspace / Control Plane

Includes:

- workspace list / switch
- workspace create
- workspace membership lifecycle
- invite lifecycle
- founder transfer
- archive lifecycle
- platform user/workspace/tenant backend APIs

Key goal:

- the service is operable without manual DB intervention

### Domain C: Resource Ownership / Isolation

Includes:

- provider scope
- API key scope
- KB / skill scope
- session / run / message scope
- visibility and capability interactions
- default-workspace legacy compatibility

Key goal:

- resource scope is explicit, stable, and testable

### Domain D: Migration / Verification / Release Gate

Includes:

- DB hardening migrations
- environment reset discipline
- remote-dev dataset cleanup rules
- API integration tests
- end-to-end closeout chain
- project-specific testing skill

Key goal:

- each phase can end on a reproducible, reviewable validation chain

## 4. Stage Breakdown

### 4.1 `Phase 4 baseline`

Definition:

- access/admin main path landed

Already expected in code:

- workspace memberships
- workspace invites
- tenant + workspace principal resolution
- capability-based workspace actions
- founder transfer
- archive
- invite accept
- workspace list / context switch

Closeout status:

- baseline landed
- not sufficient for `Phase 5`

### 4.2 `Phase 4.5`

Theme:

- closeout, management, and control

Main goals:

- close DB hard-constraint debt
- close context/discoverability debt
- land workspace create
- land minimum platform backend
- close invite onboarding and password lifecycle gaps needed for real operation
- finish KB / Documents management-surface restructuring that was blocking real product usability
- reduce compat-field dependence

Current stage note (`2026-04-16`):

- formal closeout remains `NO-GO`
- two previously identified main blockers have completed code-level repair and audit:
  - platform user provisioning on real-MySQL path
  - query / skill-chat timeout path on Redis worker mode
- these two items are now considered ready for runtime revalidation, not yet ready for stage signoff
- migration metadata hygiene for `alembic heads` remains part of the 4.5 closeout input discipline

### 4.3 `Phase 4.6`

Theme:

- tenant directory and access portrait

Main goals:

- expose user/tenant/workspace relationship truth
- provide explainable access portrait
- provide team-like collaboration management via workspace boundary
- keep directory / portrait APIs separate from onboarding and page-IA work already absorbed by `Phase 4.5`

Important note:

- this is still not a real team/org tree phase

### 4.4 `Phase 4.7`

Theme:

- pre-Phase5 release hardening

Main goals:

- standardize environment reset
- standardize API/integration verification
- standardize closeout test chain
- produce project-specific testing skill

## 5. Phase 4.x Closeout Test Chain

Every `Phase 4.x` closeout should be judged against a full chain rather than a narrow endpoint check.

Required chain:

1. platform admin logs in
2. platform admin provisions or enables a test user
3. test user logs in
4. test user creates a workspace
5. test user creates a KB
6. test user creates a provider using project `.env` LLM settings
7. test user uploads project-local PDF test data
8. parse/index/build completes
9. test user creates skill / binds KB
10. query and skill-chat flows succeed
11. API-level isolation tests confirm no cross-tenant or cross-workspace leakage
12. admin/control-plane actions still behave correctly after the chain

Registration note:

- public self-signup is **not required** for `Phase 4.x`
- platform-admin provisioning is sufficient
- if invite-bound claim / self-registration lands in `Phase 4.5`, it is treated as product closure and does not replace the provisioning-based closeout chain

Revalidation rule:

- when a blocker is fixed first at code/test level, the stage status does not advance until the same chain is rerun on the real runtime surface
- for current `Phase 4.5`, that runtime surface is the project `.env` resolved `MySQL + MinIO + Redis`

## 6. Environment Reset Rule

Before `Phase 4.5` implementation and before `Phase 4.7` hardening validation:

- clear project-owned data from the remote MySQL `pageindex` schema only for tables managed by this repo
- do not touch unknown or unrelated tables in the same DB server
- clear project-owned MinIO data for this repo's bucket/prefix only
- clear local SQLite/runtime data used by this repo

This reset must leave the environment in:

- migration-ready
- bootstrap-ready
- empty but valid

## 7. Deliverables by Stage

### `Phase 4.5`

- backend closeout implementation
- migration updates
- platform backend routes
- invite onboarding and password-management minimum product closure
- KB / Documents management-surface restructure needed for usable control-plane UX
- API tests for access/control-plane

### `Phase 4.6`

- tenant/workspace/user directory contracts
- access portrait contract
- membership visibility and explainability
- no new invite onboarding or password-lifecycle scope unless `Phase 4.5` explicitly defers a blocking fragment

### `Phase 4.7`

- reset/runbook docs
- end-to-end verification suite
- project-specific testing skill
- release gate checklist
- verification and hardening of capabilities landed in `Phase 4.5` / `Phase 4.6`, not new product surface expansion
- inherits only runtime-revalidated `Phase 4.5` results, not code-audited-only interim fixes

## 8. GO / NO-GO Rule

Do not open `Phase 5` if any of the following is still true:

- core control-plane actions still require manual DB edits
- access truth is still ambiguous between membership and compat fields
- workspace create is not closed-loop
- platform admin cannot inspect users/workspaces/tenants
- end-to-end tenant/workspace isolation is not verified by API tests
- reset and rebuild process is not reproducible
