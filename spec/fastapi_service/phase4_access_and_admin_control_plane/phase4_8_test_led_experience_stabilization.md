# Phase 4.8 Test-Led Experience Stabilization

## 1. Positioning

`Phase 4.8` is the final `Phase 4.x` stage before `Phase 5`.

Its purpose is not to reopen the backend foundation already closed through `Phase 4.5` / `Phase 4.6` / `Phase 4.7`.

Its purpose is to prove that the current PageIndex product surface is:

- usable through real operator flows
- aligned between backend truth and frontend behavior
- stable enough for daily testing and practical usage
- able to absorb narrow supporting fixes without drifting into `Phase 5`

This phase starts from the concrete closeout state on `2026-04-17`:

- `Phase 4.7 closeout`: `GO`
- `Phase 5`: still `NO-GO`

That means `Phase 4.8` is a deliberate extension of `Phase 4.x`, not a rollback of the `4.7` closeout decision.

## 2. Why This Phase Exists

`Phase 4.7` proved that the system can be reset, rebuilt, and validated on the real project runtime.

That is necessary, but not sufficient for actual product usage.

Between backend closeout and governance work, there is still one important category of risk:

- the frontend may not fully expose or correctly consume the control-plane/product truth that the backend now provides
- manual operator testing may expose continuity problems that contract tests and runtime harnesses did not catch
- real usage may require narrow fixes across frontend, supporting backend glue, error handling, or flow wording

`Phase 4.8` exists to absorb that risk in a disciplined way.

## 3. Scope

### 3.1 Test-led operator validation

Need repeated validation of the operator flows that matter for actual usage:

1. login and current context resolution
2. workspace list / switch / create
3. workspace admin surface
4. invite preview / claim / accept entry points
5. password reset / change-password continuity
6. platform tenant / user / workspace inspection
7. provider / KB / document / skill / skill-chat continuity
8. failure messages and fallback paths visible to operators

The point is not only to prove that an API returns `200`, but to prove that the product can actually be driven through the intended surface.

### 3.2 Frontend alignment audit

Need a code-backed audit of the current frontend against the landed `Phase 4.x` contracts.

Priority areas:

- workspace switcher and context handoff
- workspace admin console
- platform workspace/user detail pages
- portrait payload consumption
- provider / KB / skill / chat continuity after context changes
- onboarding/password entry points that remain relevant after `Phase 4.5`

This audit should explicitly distinguish:

- pages already aligned with backend truth
- pages usable but awkward
- pages blocked by real defects
- items intentionally deferred to `Phase 5`

### 3.3 Narrow fixes only

Allowed implementation is intentionally narrow.

Allowed:

- frontend fixes required to make the current `Phase 4.x` surface actually usable
- small supporting backend fixes if a real operator/test path is blocked
- error-handling or contract-shape cleanup when it directly affects actual usage
- copy, guardrail, and flow fixes that reduce operator confusion

Not allowed:

- new governance features
- audit-center UI
- org-tree or policy surface
- speculative redesign detached from tested problems
- broad rewrites of already-usable pages

### 3.4 Exception: provider/workspace model may be pulled forward when test-led defects prove the current product model is contradictory

`Phase 4.8` still preserves the `Phase 5` governance boundary by default.

However, if operator testing proves that the current provider/workspace product model is internally contradictory, then `4.8` may pull forward the smallest necessary subset of `Phase 5` design needed to restore product truth.

This exception is now activated as of `2026-04-21`.

Reason:

- `Skills / SkillChat / Providers / Workspace settings` were exposing provider choices that the backend would later reject
- `workspace.default_provider_id` existed in the schema but had no honest product surface
- saved skill provider/model semantics, runtime override semantics, and fallback semantics were diverging

Allowed pull-forward under this exception:

- explicit provider scope contract: `tenant | workspace | system`
- tenant-provider sharing truth for workspace availability
- workspace provider import/fork semantics
- formal `workspace default provider` product/API closure
- provider-aware `skill save` and `skill test` semantics

Still not allowed under this exception:

- audit/governance center
- provider review workflow
- policy engine
- quota/billing model
- user-private provider concept

## 4. Principles

### 4.1 Test before redesign

If a problem has not been observed in testing or actual usage, it should not automatically enter `Phase 4.8`.

### 4.2 Backend truth stays closed by default

`Phase 4.8` starts from the assumption that `Phase 4.5` / `4.6` / `4.7` are materially closed.

If a backend change is needed, it must be justified as one of:

- a real bug
- a missing compatibility edge on an already-approved flow
- a narrow support fix required by operator usage

It should not be justified as a new platform capability.

### 4.3 Frontend should consume, not reinterpret

Where `Phase 4.6` already landed normalized access portrait or capability truth, the frontend should consume that truth directly rather than recomputing it from scattered fields.

### 4.4 Preserve the Phase 5 boundary

The existence of platform pages, portraits, and operator validation does not justify drifting into governance.

If work starts to look like:

- audit review center
- governance workflow engine
- long-term analytics
- export/import administration

it is no longer `Phase 4.8`.

## 5. Deliverables

- `Phase 4.8` test plan covering real operator flows
- frontend gap audit against closed `Phase 4.x` contracts
- a prioritized list of narrow fixes
- updated checklists/runbooks where actual usage exposed missing guidance
- closeout report stating:
  - what was tested
  - what was fixed
  - what remains intentionally deferred to `Phase 5`

Additional `2026-04-21` deliverables now required by the activated provider/workspace exception:

- explicit provider/workspace contract update recorded in spec and code
- workspace AI settings surface with editable `workspace default provider`
- provider hub semantics separating:
  - tenant provider library
  - workspace providers
  - workspace default binding
  - backend system fallback explanation
- skills/skill-chat behavior aligned to workspace-available provider truth

## 6. Suggested Batch Structure

### Batch 4.8-A: Frontend/Flow Audit

Goal:

- map the current frontend to actual `Phase 4.x` capabilities
- identify blockers, friction points, and false claims

### Batch 4.8-B: Narrow Usage Blocker Fixes

Goal:

- fix only the issues that block real testing or daily use

### Batch 4.8-C: Experience Revalidation

Goal:

- rerun the tested flows after fixes
- record accepted rough edges and `Phase 5` deferrals explicitly

## 7. Non-Goals

`Phase 4.8` does not include:

- audit platform
- governance workflows
- export/import productization
- migration portability
- org/dept/team hierarchy
- billing/quota/policy engines
- major visual redesign for its own sake

## 8. Acceptance Standard

`Phase 4.8` is complete when:

- the main operator flows can be executed from the current product surface with no undocumented workaround
- frontend/backend behavior is consistent on the `Phase 4.x` control-plane surface
- remaining defects are either fixed or explicitly classified outside `Phase 4.x`
- the repo contains a concrete record of:
  - tested flows
  - narrow fixes made
  - accepted limitations
  - reasons `Phase 5` remains a separate stage

For the provider/workspace uplift activated on `2026-04-21`, the following are now part of the `Phase 4.8` acceptance bar:

- `workspace default provider` is a real product capability, not just a DB field
- `workspace default provider` can reference only a provider that is actually available in the current workspace
- provider catalogs shown in `Skills / SkillChat / Workspace settings` are based on current-workspace availability truth
- `Skill save` uses a real saved `provider_id`, not a runtime-only provider field hidden inside saved-config UI
- `Model` selection is provider-aware via `default_model / supported_models`
- `Test with draft` can actually test a changed draft provider/model
- `Send (Saved config)` does not silently consume a run-only provider override
- runtime telemetry exposes which fallback layer was actually used:
  - `runtime_override`
  - `skill_saved_provider`
  - `workspace_default_provider`
  - `tenant_default_provider`
  - `system_default_provider`

Known intentional non-goals retained after this uplift:

- streaming runtime root-cause repair
- multi-KB authoring
- provider governance workflow
- user/private provider ownership

## 9. Current Closeout Snapshot (`2026-04-21`)

Current gate:

- `Phase 4.8`: `NO-GO`
- `Phase 4`: `NO-GO`

What is now fixed in code:

- provider/workspace product truth is materially aligned across `Provider Hub`, `Workspace settings`, `Skills`, and `SkillChat`
- KB direct upload now continues into parse instead of stopping at upload + bind
- assistant timestamps no longer misreport the run start time as the answer time
- shared modal containers no longer render visibly offset under `framer-motion`
- KB upload now honestly supports drag/drop
- clipboard interactions now share one fallback-aware copy path
- the `Phase 4.7` validation harness has been re-aligned to the current skill-session contract and its local harness tests pass again

What is still blocking closeout:

- repository-wide frontend `build` still fails on the current tree
- the post-uplift real-runtime validation chain has not yet been rerun and archived

Therefore the current required next step is:

1. clear the frontend build blockers
2. rerun the real local validation chain
3. update the final closeout decision in [`phase4_closeout_status.md`](phase4_closeout_status.md)
