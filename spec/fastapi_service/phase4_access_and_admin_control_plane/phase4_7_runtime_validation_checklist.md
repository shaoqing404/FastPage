# Phase 4.7 Runtime Validation Checklist

- Stage: `Phase 4.7`
- Repository: `/Users/shaoqing/workspace/PageIndex`
- Goal: operationalize the inherited `Phase 4.5` and `Phase 4.6` surfaces into a repeatable closeout chain.

## 1. Scope Boundary

This checklist validates:

- inherited `Phase 4.5` product/control-plane closure
- inherited `Phase 4.6` directory/portrait read surface
- `Phase 4.7` reset, runtime verification, and artifact discipline

This checklist does not reopen:

- frontend IA or page work
- new portrait fields
- onboarding redesign
- password-management redesign
- governance or audit-center scope

## 2. Inputs

Required files:

- `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_reset_runbook.md`
- `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_backend_validation.py`
- `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_verification_artifact_retention_rule.md`

Preferred repo-local PDF:

- `/Users/shaoqing/workspace/PageIndex/examples/documents/attention-residuals.pdf`

Allowed fallback PDFs:

- `/Users/shaoqing/workspace/PageIndex/examples/documents/2023-annual-report-truncated.pdf`
- `/Users/shaoqing/workspace/PageIndex/examples/documents/PRML.pdf`
- `/Users/shaoqing/workspace/PageIndex/《运行手册》（第1版）.pdf`

## 3. Preflight

Check all items before live validation:

- `uv run python -m unittest discover -s tests/phase4 -p 'test_*.py'` passes
- `.env` points at the intended `MySQL + MinIO + Redis` runtime
- backend API and worker are reachable
- provider `.env` credentials are valid for `openai_compatible` creation
- chosen PDF exists inside the repo

## 4. Reset Gate

Complete the reset runbook first.

Do not continue unless:

- environment is empty but valid
- bootstrap completed
- migration head is clean
- no stale validation artifacts are still active

## 5. Live Validation Chain

Run the scripted chain:

```bash
cd /Users/shaoqing/workspace/PageIndex
uv run python spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_backend_validation.py \
  --output results/phase4_7_backend_validation_latest.json
```

The script must validate all of the following:

1. platform admin login
2. platform-admin provisioning of a temp validation user
3. validation user login
4. workspace create with automatic context handoff
5. workspace list and context switch
6. API key create
7. platform routes reject API-key access with `403`
8. knowledge base create
9. provider create and `probe-models`
10. repo-local PDF upload
11. parse job reaches `index_ready`
12. KB document binding succeeds
13. skill create succeeds with `knowledge_base_id`
14. direct query succeeds
15. skill run succeeds
16. session messages are readable
17. workspace isolation negative path returns `404` from a non-owning workspace context
18. platform user portrait succeeds for the validation user
19. platform workspace portrait succeeds for the validation workspace
20. platform tenant list/detail remain readable by platform admin

## 6. Manual Assertions After Script

Review the JSON artifact and confirm:

- `summary.status == "passed"`
- cleanup status is explicit
- created artifact ids are recorded
- provider model is the expected runtime default or the configured override
- portrait checks include explainability payloads
- negative path evidence is explicit, not implied

## 7. Required Evidence Bundle

Store the following as the closeout evidence set:

- latest script JSON output under `results/`
- exact command line used
- validation start/end time
- selected PDF path
- whether password reset flow was exercised
- whether cleanup completed or artifacts were intentionally retained
- any operator notes needed to explain deviations

## 8. Known Constraint

Cross-tenant negative-path proof is still structurally limited because tenant creation is not yet a first-class operator flow.

Rule for `Phase 4.7`:

- do not fake cross-tenant runtime proof through undocumented DB edits during the normal checklist
- instead, record the limitation explicitly if only same-tenant workspace isolation and platform-access boundaries were exercised

## 9. GO / NO-GO Interpretation

`Phase 4.7 baseline: GO` requires:

- write-surface deliverables are present in the repo
- local contract suite passes
- live validation process is standardized and runnable

`Phase 4.7 closeout: GO` requires:

- live validation script passes on the target runtime
- cleanup/retention handling is unambiguous
- inherited `Phase 4.5` and `Phase 4.6` surfaces are validated without reopening scope

`NO-GO` if any of the following occurs:

- reset cannot be completed safely
- migrations/bootstrap do not rebuild cleanly
- provider/PDF/query/skill path fails
- platform portrait routes regress
- API-key or workspace-isolation checks regress
- cleanup leaves ambiguous active validation artifacts
