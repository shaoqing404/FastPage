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

Current stage note (`2026-04-17`):

- formal closeout is now `Conditional GO`
- the real project `.env` runtime chain has been rerun on `MySQL + MinIO + Redis`
- the previously known main blockers have completed both code-level repair and real runtime revalidation:
  - platform user provisioning on the real-MySQL path
  - query / skill-chat execution on Redis worker mode
- migration metadata hygiene has been brought back into a clean state
  - `uv run alembic heads` => single head `20260416_0010`
  - `uv run alembic current` => `20260416_0010`
- the end-to-end closeout chain has been confirmed on the real runtime surface:
  - platform admin -> new user -> workspace -> KB -> provider -> repo-local PDF -> query / skill chat
- remaining condition:
  - direct product-surface runtime proof for cross-tenant negative-path checks is still limited because tenant creation is not yet a first-class operator workflow
- handoff to `Phase 4.7`:
  - standardize the runtime verification process
  - clean up temporary verification artifacts

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

Current stage note (`2026-04-17`):

- formal closeout is `GO`
- landed surfaces include:
  - `GET /api/v1/platform/users/{user_id}/access-portrait`
  - `GET /api/v1/platform/workspaces/{workspace_id}/access-portrait`
  - normalized portrait schemas and explainability payloads
  - platform user/workspace detail pages consuming portrait payloads directly
- verification completed through:
  - backend contract suite
  - migration hygiene checks
  - frontend build gate
  - real local runtime verification on `127.0.0.1:22223`
- `Phase 4.7` inherits `Phase 4.6` as a closed product/API surface
  - `4.7` may harden and standardize its validation
  - `4.7` should not reopen `4.6` scope or add new portrait features

### 4.4 `Phase 4.7`

Theme:

- pre-Phase5 release hardening

Main goals:

- standardize environment reset
- standardize API/integration verification
- standardize closeout test chain
- produce project-specific testing skill

Current stage note (`2026-04-17`):

- this phase now inherits:
  - `Phase 4.5` at `Conditional GO`
  - `Phase 4.6` at `GO`
- its main carry-forward work is operational hardening rather than product completion:
  - make the runtime verification flow reproducible
  - define cleanup rules for verification artifacts such as temporary users, reset passwords, and API keys
  - capture the full closeout chain in runbook/skill form

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
- operationalization of the current manual runtime verification flow
- cleanup/retention rules for temporary verification artifacts

## 7.5 Overlap Audit Before Phase 5

The stages before `Phase 5` intentionally touch some of the same entities, but the overlap should be interpreted by responsibility, not by page or table name alone.

### `Phase 4.5` vs `Phase 4.6`

Overlap level: `moderate`

Shared entities:

- users
- tenants
- workspaces
- memberships
- KB / Documents ownership presentation

Split:

- `Phase 4.5` closes product and management surfaces
- `Phase 4.6` exposes relationship truth and explainability

Rule:

- mutations / entry flows / management closure belong to `4.5`
- portrait / directory / why-allowed-or-denied read truth belongs to `4.6`

### `Phase 4.5` vs `Phase 4.7`

Overlap level: `low`

Shared concern:

- `4.7` must validate closures that `4.5` already landed

Rule:

- `4.7` validates `4.5`
- `4.7` does not redesign `4.5`

### `Phase 4.6` vs `Phase 4.7`

Overlap level: `low`

Shared concern:

- `4.7` must standardize verification for the access-portrait and directory contracts landed in `4.6`

Rule:

- `4.6` defines and lands explainability contracts
- `4.7` proves they are reproducibly verifiable

### `Phase 4.x` vs `Phase 5`

Overlap level: `low in scope, moderate in terminology`

The terms `control`, `visibility`, and `auditability` appear before `Phase 5`, but they remain pre-governance preparation until:

- audit center
- governance workflows
- policy / quota / billing surfaces
- long-term operational analytics

Therefore:

- the Claude interim batch audited on `2026-04-16` should be recorded as `Phase 4.5` closure work
- it should not be relabeled as `Phase 4.6`
- it does not justify opening `Phase 5`

## 8. GO / NO-GO Rule

Do not open `Phase 5` if any of the following is still true:

- core control-plane actions still require manual DB edits
- access truth is still ambiguous between membership and compat fields
- workspace create is not closed-loop
- platform admin cannot inspect users/workspaces/tenants
- end-to-end tenant/workspace isolation is not verified by API tests
- reset and rebuild process is not reproducible
