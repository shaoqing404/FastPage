---
name: pageindex-phase4-7-hardening
description: Run or review the PageIndex Phase 4.7 hardening workflow: safe environment reset, local phase4 contract suite, live runtime validation, artifact cleanup/retention handling, and Phase 4.7 baseline/closeout GO-NO-GO reporting. Use this when the user asks to validate, rerun, or close out Phase 4.7 for PageIndex.
---

# PageIndex Phase 4.7 Hardening

Use this skill only for `/Users/shaoqing/workspace/PageIndex`.

## Workflow

1. Read the current hardening assets:
   - `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_reset_runbook.md`
   - `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_runtime_validation_checklist.md`
   - `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_verification_artifact_retention_rule.md`
   - `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_closeout_report.md`
2. Run the local contract baseline before live validation:
   - `cd /Users/shaoqing/workspace/PageIndex`
   - `uv run python -m unittest discover -s tests/phase4 -p 'test_*.py'`
3. If a clean runtime reset is required, follow the reset runbook exactly. Do not improvise broader MySQL or MinIO deletion.
4. Run the live runtime harness:
   - `uv run python spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_backend_validation.py --output results/phase4_7_backend_validation_latest.json`
5. Review the JSON artifact and map the result to one of:
   - `Phase 4.7 baseline: GO`
   - `Phase 4.7 closeout: GO`
   - `NO-GO`

## Rules

- Do not reopen `Phase 4.5` or `Phase 4.6` product scope.
- Do not touch frontend when running Phase 4.7 hardening.
- Treat the repo code as source of truth over stale notes.
- If runtime validation fails, keep artifacts for triage unless an active API key must be revoked immediately.
- Never store cleartext temporary passwords in repo-tracked files.

## Expected Outputs

- explicit test command results
- path to the latest JSON validation artifact in `results/`
- cleanup status and any retained artifact ids
- a narrow GO / NO-GO statement using the phase-gate language above
