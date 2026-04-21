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
- `Phase 4.8 Test-Led Experience Stabilization`

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

The current codebase now materially includes:

- `Phase 4.5` operational control-plane closure
- `Phase 4.6` tenant/workspace/user portrait surfaces
- `Phase 4.7` reset / hardening / validation assets
- `Phase 4.8` provider/workspace uplift and follow-up frontend usability fixes

Current parent-stage blocker summary (`2026-04-21`):

- the phase4 spec/validation surface has been restored and re-aligned to the current chat-session contract
- local `Phase 4.7` harness contract checks pass again
- full frontend `build` still fails on the current tree
- the post-`4.8` real-runtime closeout rerun is still pending

That means:

- `Phase 4` is still `NO-GO`
- `Phase 5` is still `NO-GO`

## Structure

### Active closeout docs

- [phase4_master_stage_plan.md](phase4_master_stage_plan.md)
- [phase4_7_closeout_report.md](phase4_7_closeout_report.md)
- [phase4_8_test_led_experience_stabilization.md](phase4_8_test_led_experience_stabilization.md)
- [phase4_closeout_status.md](phase4_closeout_status.md)

Historical design notes and earlier batch docs remain available in git history and can be restored if the closeout work needs them again.

### Operator-doc handoff

Canonical `Phase 4.7` operator runbooks now live under:

- [docs/phase4_7/README.md](../../../docs/phase4_7/README.md)

The `spec/` tree remains the parent-stage design and gate record.

### Execution support

- [phase4_7_backend_validation.py](phase4_7_backend_validation.py)

## Recommended Sequence

1. Keep `Phase 4.5` at `Conditional GO`.
2. Keep `Phase 4.6` at `GO`.
3. Rerun `Phase 4.7` hardening validation on the current post-`4.8` tree.
4. Clear remaining `Phase 4.8` frontend build blockers and finish closeout revalidation.
5. Only then open `Phase 5`.

## Parent-stage Closeout Rule

`Phase 4` is not considered closed merely because the happy-path product works.

It is closed only when:

- control-plane behavior is explicit and operable
- access rules are membership-driven and explainable
- key runtime compatibility debt is reduced to controlled fallback only
- the environment can be reset and rebuilt reproducibly
- a full end-to-end verification chain passes on project-owned test data
