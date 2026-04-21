# Phase 4.7 Pre-Phase5 Release Hardening

## 1. Positioning

`Phase 4.7` is the final `Phase 4.x` stage before `Phase 5`.

Its purpose is not to add new product scope.

Its purpose is to prove that the `Phase 4.x` system can be:

- reset cleanly
- rebuilt reproducibly
- validated through API and end-to-end chains
- handed into governance work without unresolved platform-operability questions

This phase assumes product-surface closure work has already been assigned to `Phase 4.5` and relationship-truth exposure has already been assigned to `Phase 4.6`.

It also assumes that any `Phase 4.5` blocker first repaired at unit-test or contract-test level has already been rerun on the real project runtime surface before being treated as a hardening baseline.

Current inherited baseline (`2026-04-17`):

- `Phase 4.5` enters `4.7` as `Conditional GO`
- `Phase 4.6` enters `4.7` as `GO`
- `4.7` therefore inherits a runtime-revalidated control-plane/product baseline rather than a code-audited-only baseline

## 2. Scope

### 2.1 Environment reset and rebuild

Need a standard process for:

- clearing project-owned remote MySQL data
- clearing project-owned MinIO data
- clearing local SQLite/runtime data
- re-running migrations
- re-bootstraping the environment into a clean initial state

Safety rule:

- never delete unknown or unrelated data in shared infrastructure

### 2.2 API integration verification

Need repeatable tests for:

- tenant isolation
- workspace isolation
- context switch
- invite acceptance
- workspace create
- platform admin visibility
- capability enforcement
- founder/archive invariants
- platform user/workspace portrait contracts
- platform portrait route access control

### 2.3 End-to-end product chain

Need a standard closeout chain using PDFs already present in the repo.

Expected chain:

1. platform admin provisions test user
2. test user logs in
3. test user creates workspace
4. test user creates provider
5. test user uploads PDF from repo
6. parse/index/build succeeds
7. KB and skill flow succeeds
8. query / skill chat succeeds
9. access-control API tests still pass

If `Phase 4.5` lands invite claim / password lifecycle closure, `Phase 4.7` should validate that flow as an additional product path, but it should not redefine or redesign it here.

Input discipline:

- `Phase 4.7` does not accept “code audit passed” as a substitute for runtime validation
- fixes inherited from `Phase 4.5` must already have been rerun on the project `.env` resolved `MySQL + MinIO + Redis` surface
- this specifically applies to user provisioning and query / skill-chat paths that were previously known `Phase 4.5` blockers

### 2.4 Project-specific testing skill

Need a Codex skill dedicated to this repo that captures:

- environment reset steps
- migration steps
- test user provisioning pattern
- provider bootstrap pattern
- PDF test data choices
- API verification checklist
- end-to-end validation chain

This skill is a required `Phase 4.7` deliverable, not optional polish.

### 2.5 Verification artifact discipline

Need a standard process for:

- naming temporary validation users
- naming temporary validation API keys
- recording when a validation password reset was performed
- deciding which verification artifacts must be deleted, archived, or retained

Reason:

- `Phase 4.5` / `Phase 4.6` closeout can now be completed on the real runtime surface
- that validation necessarily creates temporary operator/test artifacts
- `Phase 4.7` should make this reproducible and low-risk instead of ad hoc

## 3. Test Data Rule

Tests in this stage should use PDFs inside the project directory first.

This keeps validation:

- reproducible
- source-controlled
- independent from unstable external document inputs

Preferred sources:

- top-level project PDF where useful
- `examples/documents/*.pdf`

## 4. Provider Bootstrap Rule

For default validation:

- use the project `.env` compatible OpenAI settings as the source config
- create a DashScope / BaiLian-compatible provider through the product/API flow
- set default model according to the current runtime default
  - current DashScope-compatible runtime default is `openai/qwen-plus`

This validates:

- provider control-plane behavior
- secret handling
- downstream runtime resolution

## 5. Required Deliverables

- reset runbook
- API integration suite
- end-to-end closeout checklist
- project testing skill
- `Phase 4.x` GO / NO-GO report
- explicit record of which inherited `Phase 4.5` fixes were runtime-revalidated before hardening
- operationalized runtime verification checklist for portrait/control-plane validation
- verification-artifact cleanup/retention rule

## 6. Non-Goals

`Phase 4.7` does not include:

- new governance policy features
- audit center
- export/import productization
- cross-instance migration tooling
- org/team tree
- invite onboarding redesign
- password-management product redesign
- KB / Documents page IA redesign

## 7. Acceptance Standard

`Phase 4.7` is complete when:

- the environment can be reset without collateral damage
- the environment can be rebuilt from a clean state
- API-level isolation and capability rules are fully verified
- the end-to-end product chain passes on repo-local PDF inputs
- the testing process is standardized enough to be reused as a project-specific skill
- the testing process validates the product closures already landed in `Phase 4.5` rather than re-scoping them
- runtime verification artifacts can be created and cleaned up without ambiguity or drift
