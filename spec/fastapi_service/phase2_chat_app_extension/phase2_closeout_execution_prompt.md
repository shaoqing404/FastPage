# Phase 2 Closeout Execution Prompt

## Context

You are taking over **Phase 2 Closeout** for the PageIndex FastAPI service workspace.

Repository root:

- `/Users/shaoqing/workspace/PageIndex`

Current phase status:

- Phase 0 and Phase 1 core backend work are already implemented.
- Phase 2 mainline backend/frontend work is mostly implemented, but **Phase 2 is not formally closed**.
- Existing records say the phase exit was **NO-GO** on **2026-04-03** because the skill SSE path failed during acceptance and fixture cleanup was unreliable.

Read these files first:

- `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/README.md`
- `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/phase2_exit_report.md`
- `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/acceptance_checklist.md`
- `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/skill_chat_stream_contract.md`
- `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/frontend_phase2_session_and_stream_handoff.md`
- `/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/backend_validation_report.md`

Relevant code areas:

- `/Users/shaoqing/workspace/PageIndex/app/api/routers/chat.py`
- `/Users/shaoqing/workspace/PageIndex/app/api/routers/skills.py`
- `/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py`
- `/Users/shaoqing/workspace/PageIndex/app/services/session_service.py`
- `/Users/shaoqing/workspace/PageIndex/app/services/skill_service.py`
- `/Users/shaoqing/workspace/PageIndex/frontend/src/features/chat/api.ts`
- `/Users/shaoqing/workspace/PageIndex/frontend/src/pages/SkillChatPage.tsx`

## Important Current Findings

1. The previous blocker was:
   - `name 'stats_hook' is not defined` in `stream_skill_run_events`
   - reported in the acceptance docs and exit report
2. In the current code snapshot, `stats_hook` now appears to be defined inside `stream_skill_run_events`.
3. That means the original blocker may already be patched, but **Phase 2 is still not closed until it is revalidated end-to-end**.
4. Skill deletion cleanup is still suspicious:
   - current `DELETE /api/v1/skills/{skill_id}` just does `db.delete(skill)` and `db.commit()`
   - there are foreign-key references from `chat_runs.skill_id` and `chat_sessions.skill_id`
   - this is a likely cause of the earlier cleanup failure and must be verified and fixed if needed

## Your Goal

Complete **Phase 2 Closeout** end-to-end. Do not stop at analysis. Patch, validate, and update spec records so that the repository has a clear GO/NO-GO outcome based on fresh evidence.

## Mandatory Exit Criteria

Phase 2 can be formally closed only if all of the following are true:

### A. SSE contract passes

For skill chat streaming, verify the expected happy-path sequence end-to-end:

- `run_started`
- `status=accepted`
- `status=retrieving`
- `context`
- `status=answering`
- one or more `answer_delta`
- `status=completed`
- `run_completed`

And confirm:

- `run_completed` includes `execution_context`
- `run_completed` includes `citations`
- `run_completed` includes `metrics`
- persisted run data matches final SSE payload

### B. Abort semantics pass

Verify that aborting a stream after at least one answer delta:

- stops the stream cleanly
- persists the run in a predictable terminal state
- records the expected abort/error metric behavior
- does not corrupt the session message sequence

If the current contract or implementation differs from the older note, document the exact final behavior with evidence.

### C. Multi-turn skill session semantics pass

Verify that skill-scoped sessions are real, not frontend-only filtering:

- create or reuse a skill session
- send at least two turns
- confirm history is actually entering the execution path
- confirm the resulting run contains meaningful `execution_context.conversation` metadata
- confirm query rewrite / history usage behavior is reflected in the run output

### D. Error path remains correct

Verify failure-path behavior still works:

- stream emits `status=failed` and `error`
- user message is retained in session history
- no silent success is recorded

### E. Cleanup path is operable

Acceptance fixtures created during validation must be removable through supported product paths, or the retained behavior must be intentionally documented.

At minimum verify:

- temp document delete works
- temp skill delete works
- temp provider delete works after dependency cleanup

If deletion is intentionally blocked by dependent runs or sessions, implement or document the expected product rule clearly. Do not leave it as a generic 500.

### F. Spec records are updated

Update the phase records with fresh evidence:

- `phase2_exit_report.md`
- `acceptance_checklist.md`
- any other directly relevant phase docs if behavior changed

The final report must explicitly state:

- test date
- environment used
- provider and model used
- pass/fail by test case
- GO or NO-GO
- any residual risks

## Execution Requirements

1. Inspect the current code before changing anything.
2. Reproduce the current Phase 2 acceptance state.
3. If failures remain, patch them in code.
4. Re-run the acceptance flow until the outcome is clear.
5. Prefer real backend validation over mock reasoning.
6. If frontend behavior depends on backend run IDs or stream behavior, verify enough of the frontend contract to ensure backend closeout is meaningful.
7. Do not treat old reports as current truth. Revalidate everything that was previously blocked.
8. Do not revert unrelated user changes.

## Areas Most Likely To Need Attention

### 1. Stream path

Check `stream_skill_run_events` in:

- `/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py`

Focus on:

- event ordering
- run persistence timing
- usage accounting
- `run_completed` backfill contents
- cancellation handling
- error handling

### 2. Cleanup and delete behavior

Check:

- `/Users/shaoqing/workspace/PageIndex/app/api/routers/skills.py`
- `/Users/shaoqing/workspace/PageIndex/app/models/chat_run.py`
- `/Users/shaoqing/workspace/PageIndex/app/models/chat_session.py`

Look for foreign-key or lifecycle problems when deleting skills/providers that have dependent sessions/runs.

### 3. Frontend stream contract compatibility

Check:

- `/Users/shaoqing/workspace/PageIndex/frontend/src/features/chat/api.ts`
- `/Users/shaoqing/workspace/PageIndex/frontend/src/pages/SkillChatPage.tsx`

Confirm the backend event sequence and payload shape still match what the frontend expects.

## Concrete Deliverables

When done, you must leave behind:

1. Code changes required to close or clearly diagnose Phase 2
2. Updated phase acceptance documents with fresh evidence
3. A short final summary that states one of:
   - `Phase 2 Closeout: GO`
   - `Phase 2 Closeout: NO-GO`

If NO-GO, list the exact remaining blockers and the specific test cases still failing.

## Suggested Working Order

1. Read the phase docs and current stream code.
2. Run or reproduce the acceptance flow.
3. Fix stream and cleanup issues if any remain.
4. Re-run blocked cases:
   - `TC-SSE-001`
   - `TC-SSE-002`
   - `TC-SSE-003`
   - `TC-CHAT-001`
   - cleanup checks
5. Update spec docs with fresh result.
6. Report final GO/NO-GO.

## Non-Goals For This Task

Do not expand scope into Phase 3 productization work such as:

- tenant management UI
- chat worker offloading
- multi-manual aggregation redesign
- compliance API design
- open-source packaging

Only close Phase 2 cleanly.
