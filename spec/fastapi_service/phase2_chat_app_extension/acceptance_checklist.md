# Phase 2 Acceptance Checklist (Backend/API/SSE)

- Date: 2026-04-06
- Scope owner: Codex (real backend + real provider + SSE/API verification)
- Backend base URL: `http://127.0.0.1:22223/api/v1`
- Environment:
  - `DATABASE_URL=sqlite:////tmp/pageindex_phase2_closeout/app.db`
  - `DATA_DIR=/tmp/pageindex_phase2_closeout/data`
  - `STORAGE_BACKEND=local`
  - `TASK_QUEUE_BACKEND=local`
- Provider under test: DashScope OpenAI-compatible (`https://dashscope.aliyuncs.com/compatible-mode/v1`)
- Model under test: `openai/qwen-plus`
- Raw execution artifact: `/tmp/pageindex_phase2_final_result.json`

## Fresh Reproduction Before Fixes

- Reproduced on current 2026-04-06 code snapshot before patching:
  - SSE happy path still failed because `_sse()` attempted to serialize `datetime` directly in `run_completed`.
  - Abort after first `answer_delta` did not reliably terminate execution.
  - Skill delete path still used raw row deletion without dependent cleanup.
- The old `stats_hook` blocker from 2026-04-03 was **not** the active blocker anymore.

## Final Fixture References

- `document_id`: `2cf828e5-4a28-4ce9-83c9-fc4ea71e3a8b` (`2603.22458v1.pdf`)
- `provider_id`: `96306428-f345-424f-9716-7f9afebd337c`
- `skill_id`: `b06f44d9-c02e-4cf6-91bf-29114317ae0e`
- `session_happy`: `dab37eac-ad37-4485-9dfb-ade7bbb2a6a9`
- `session_multi`: `f1d51959-8494-4f89-bddd-8d50c5e7000b`
- `session_abort`: `0b659154-1b55-4a95-824f-46686c75eb3d`
- `session_fail`: `0fe2db37-9bed-4723-8191-55ae336760cf`

## Case Results

| TC | Target | Result | Evidence |
|---|---|---|---|
| `TC-SSE-001` | SSE event sequence | PASS | happy-path stream observed `run_started -> status(accepted) -> status(retrieving) -> context -> status(answering) -> answer_delta+ -> status(completed) -> run_completed`; run `98de8f50-c2bc-4a57-b904-4ef7f812a185` |
| `TC-SSE-002` | `run_completed` contains `execution_context/citations/metrics` | PASS | final event for run `98de8f50-c2bc-4a57-b904-4ef7f812a185` included all required fields and matched persisted run readback |
| `TC-SSE-003` | Stop/Abort semantics | PASS | stream aborted after first `answer_delta`; run `55fa1f92-19e1-49d2-abff-f32d20bb1505` persisted as `status=failed`, `metrics.error=client aborted stream`, and session kept only the user message |
| `TC-CHAT-001` | multi-turn conversation semantics | PASS | second run `e274dc35-0236-41d1-ae23-47fc118e28f0` reported `history_used=true`, `history_messages_used=2`, and a history-informed rewritten retrieval query |
| `TC-ERR-001` | failure path emits `status=failed` + `error` and keeps user message | PASS | run `228f8222-0da1-4f0c-9488-44711a37b8e1` emitted `status=failed` then `error`; persisted run stayed failed and the session retained the user message |
| `TC-CONFIG-001` | provider probe + skill/provider/model linkage | PASS | `probe-models` succeeded for provider `96306428-f345-424f-9716-7f9afebd337c`; skill/readback used `openai/qwen-plus` correctly |
| `TC-DOC-001` | document delete API | PASS | temp upload deleted via `DELETE /documents/{document_id}` with `204` |
| `TC-CLEANUP-001` | temp skill/provider cleanup | PASS | happy-path skill/provider deleted with `204`; failed-run skill/provider (`d15a4ac6-34fc-4604-a282-33a9c948de7a`, `252d0a81-7fd2-4e23-afc0-0a8e6135e1fe`) also deleted successfully |

## Contract Notes Verified

- `run_completed` now serializes cleanly over SSE even with `datetime` fields in the final payload.
- Abort semantics now terminate the run predictably in the cancellation path instead of silently completing.
- Multi-turn session history is real backend execution input, not frontend-only filtering.
- Cleanup is now lifecycle-aware for skills, and provider delete surfaces explicit dependency errors instead of relying on database failure.

## Final Decision

- Phase 2 acceptance result: **PASS**
- Phase 2 Closeout: **GO**
