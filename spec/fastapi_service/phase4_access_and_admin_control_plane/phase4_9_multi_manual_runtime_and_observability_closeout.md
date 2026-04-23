# Phase 4.9 Multi-Manual Runtime And Observability Closeout

- Repository root: current PageIndex checkout
- Parent stage: `Phase 4 Access, Admin, and Pre-Phase5 Closeout`
- Status date: `2026-04-22`
- Current decision: `Conditional GO`

## 1. Phase Intent

`Phase 4.9` exists to close the runtime gap that remained after `Phase 4.8`:

- `skills run` had to move from effectively single-manual behavior to real multi-manual retrieval
- `skills chat`, `skills run`, and `compliance` needed a shared worker/runtime surface
- worker execution needed production-facing concurrency and memory governance
- runtime state needed a unified observation surface rather than scattered logs
- rerank needed to be a first-class runtime capability rather than an implicit provider detail

This is a runtime/productization phase, not a new governance phase.

## 2. Landed In Code

The current tree materially lands the following:

### 2.1 Unified async worker runtime

- `skills run`, `skills chat`, and `compliance` now execute on the same async worker surface
- worker heartbeats, reconnect handling, queue state, and run-stage logging are present
- worker process governance now includes:
  - PID-qualified worker node codes
  - child recycling hooks
  - RSS watchdog support
  - Docker launch wrappers using `MALLOC_ARENA_MAX=2`

Primary code paths:

- `app/worker.py`
- `app/services/task_queue_service.py`
- `docker/docker-entrypoint.sh`
- `docker/start.sh`
- `docker/docker-compose.yml`

### 2.2 Skills multi-manual retrieval

- skills no longer stop at the first bound document when a Knowledge Base is attached
- retrieval now resolves ready manuals from the KB, fans out per-manual retrieval in parallel, then merges globally
- context build and answer generation now execute against the merged citation set

Primary code paths:

- `app/services/chat_service.py`
- `app/services/pageindex_service.py`
- `app/services/knowledge_base_service.py`

### 2.3 Cross-manual rerank

- rerank is now a first-class runtime stage
- provider-native rerank model detection is supported
- system rerank fallback is env-driven
- native DashScope rerank endpoints are now treated separately from `chat/completions`
- rerank failure falls back to original retrieval order instead of crashing the whole run

Primary code paths:

- `app/services/provider_service.py`
- `app/services/pageindex_service.py`
- `.env.example`
- `docker/.env.example`

### 2.4 Unified runtime observation

- run observation events are persisted and streamed for `chat` and `compliance`
- the product can now show queue/runtime stages, worker node identity, timings, and execution context
- frontend now has shared runtime timeline components

Primary code paths:

- `app/services/runtime_observation_service.py`
- `app/api/routers/runtime_observations.py`
- `frontend/src/components/runtime/RunObservationTimeline.tsx`
- `frontend/src/components/runtime/RunStepPanel.tsx`
- `frontend/src/features/runtime-observations/api.ts`

## 3. Verified Product Truth

Confirmed on the current tree:

- worker/runtime documentation exists under:
  - `docs/phase4_9/skills_run_worker_state_machine.md`
  - `docs/phase4_9/worker_concurrency_and_memory_governance.md`
- skills detail page exposes saved rerank configuration and now makes the save semantics explicit
- system rerank can route to native DashScope rerank endpoints instead of incorrectly appending `/chat/completions`
- runtime observation data is available to both skills and compliance surfaces
- current targeted validation passes:
  - `uv run python -m unittest tests.phase4.test_provider_execution_model_normalization tests.phase4.test_pageindex_native_rerank tests.phase4.test_skill_stream_runtime_contract tests.phase4.test_chat_run_worker_logging`
  - `npm run build`

Additional `2026-04-22` regression fix now landed:

- `compliance` no longer fails after producing a valid result just because the `run_completed` observation payload contains raw `datetime` objects
- both compliance serialization and observation payload sanitation now normalize nested datetimes safely

Targeted validation:

- `uv run python -m unittest tests.phase4.test_compliance_serialization tests.phase4.test_runtime_observation_serialization`

## 4. E2E Evidence From Operator Testing

Real Chrome-based operator testing on `2026-04-22` confirmed:

- Workspace creation: working
- Provider creation and workspace availability: working
- multi-document KB build: working
- skills multi-manual query path: working
- compliance multi-manual path: working through retrieval / rerank / build_context / final_answer

The operator test also surfaced two important truths:

1. system/provider rerank configuration must be validated against the actual endpoint style
2. compliance completion could still be marked `failed` if observation payloads were not JSON-safe

The second issue is fixed on the current tree by the serialization patch landed on `2026-04-22`.

## 5. Remaining Gaps

`Phase 4.9` is not perfectly finished from a product-surface perspective.

Remaining non-zero gaps:

- Compliance UI still does not expose a rerank control comparable to the skills detail page
- runtime observation UI still under-exposes:
  - clearer LLM request/response summaries
  - a more explicit answer-delta/progressive-output panel
- full operator rerun after the compliance serialization fix is still desirable before declaring hard `GO`

These are not runtime-foundation blockers, but they are still product-surface gaps.

## 6. Gate Decision

`Phase 4.9`: `Conditional GO`

Reason:

- the runtime architecture, worker governance, multi-manual retrieval, rerank plumbing, and observation plane are materially landed
- the known compliance completion regression has now been fixed on the current tree
- the remaining issues are primarily product-surface polish and one final rerun gap, not missing runtime foundation

## 7. Recommended Next Action

Before promoting this to a hard `GO`, do one narrow follow-up rerun:

1. rerun the saved compliance check on the current tree
2. confirm final status is `completed` after the serialization fix
3. record one fresh artifact showing:
   - `multi_manual_federated`
   - rerank mode behavior
   - observation timeline completion
   - successful `persist_result`

If that rerun passes, `Phase 4.9` can be upgraded from `Conditional GO` to `GO`.
