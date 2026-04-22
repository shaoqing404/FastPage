# Worker Concurrency And Memory Governance

This document explains the current `skills run / skills chat / compliance` execution model, the concurrency knobs that materially affect latency and throughput, and the two-tier memory governance now present in the worker stack.

## Scope

The runtime has two distinct concurrency layers:

1. Run-level concurrency across worker child processes.
2. In-run retrieval concurrency across manuals inside a single skill/compliance run.

These two layers are intentionally different. The worker process model preserves strong isolation between independent runs, while the retrieval fanout reduces latency for multi-manual search inside one run.

## Current Execution Model

### 1. Across runs: one job per worker child process

Each worker child process consumes Redis queues with the loop:

`BLPOP -> handle one message -> complete -> BLPOP again`

That means:

- One worker child process handles at most `1` active run at a time.
- A single node handles at most `WORKER_PROCESS_COUNT` active runs at a time.
- If `WORKER_PROCESS_COUNT=4`, the node can execute at most `4` runs concurrently.

Relevant code:

- [app/worker.py](/Users/shaoqing/workspace/PageIndex/app/worker.py:267)
- [app/core/config.py](/Users/shaoqing/workspace/PageIndex/app/core/config.py:261)

### 2. Inside one run: manual retrieval is parallel

For knowledge-base-backed skill runs and compliance runs, manual retrieval is executed with:

- `asyncio.gather(...)`
- `asyncio.Semaphore(min(RETRIEVAL_MAX_CONCURRENCY, manual_count))`

That means:

- A single run can search multiple manuals in parallel.
- The maximum number of manual retrieval tasks in memory at once is bounded by `RETRIEVAL_MAX_CONCURRENCY`.

Relevant code:

- [app/services/chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py:1407)
- [app/services/compliance_service.py](/Users/shaoqing/workspace/PageIndex/app/services/compliance_service.py:1351)

## Effective Concurrency Formula

For sizing and throughput planning, the useful formulas are:

- Concurrent runs per node:
  `node_run_concurrency = WORKER_PROCESS_COUNT`
- Concurrent manual retrieval tasks per run:
  `run_manual_concurrency = min(RETRIEVAL_MAX_CONCURRENCY, resolved_manual_count)`
- Peak retrieval fanout per node:
  `node_retrieval_fanout = WORKER_PROCESS_COUNT * min(RETRIEVAL_MAX_CONCURRENCY, average_manuals_per_run)`

Examples:

- `WORKER_PROCESS_COUNT=2`, `RETRIEVAL_MAX_CONCURRENCY=8`, 5 manuals/run:
  node run concurrency = `2`
  peak retrieval fanout = `2 * 5 = 10`
- `WORKER_PROCESS_COUNT=4`, `RETRIEVAL_MAX_CONCURRENCY=8`, 12 manuals/run:
  node run concurrency = `4`
  peak retrieval fanout = `4 * 8 = 32`

## Session Serialization

For chat runs, the worker also preserves in-order execution per chat session:

- The same session can only have one active run at a time.
- Later runs for the same session are requeued until the older run releases the session slot.

Relevant code:

- [app/services/chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py:946)
- [app/services/chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py:1115)

This means node-level concurrency is not the whole story. If many requests target the same skill session, they will still serialize by design.

## Two-Tier Memory Governance

## Outer Layer: Docker / Process Environment

The worker container is now launched through a dedicated wrapper:

- [docker/worker-entrypoint.sh](/Users/shaoqing/workspace/PageIndex/docker/worker-entrypoint.sh:1)
- [docker/docker-compose.yml](/Users/shaoqing/workspace/PageIndex/docker/docker-compose.yml:106)

This wrapper sets:

- `MALLOC_ARENA_MAX=2`

Why it matters:

- On glibc-based Linux containers, this significantly reduces allocator arena growth and long-lived fragmentation.
- It is especially useful for multi-process Python workers that repeatedly allocate and discard large JSON trees, prompt strings, and model responses.

Important note:

- This knob is meaningful in Linux containers using glibc.
- It is not the primary protection on macOS local runs.

## Inner Layer: Worker Recycling And Hard Bounds

The worker process now contains three hard guards:

### 1. Max tasks per child

Each child tracks `tasks_processed`.

- When `tasks_processed >= WORKER_MAX_TASKS_PER_CHILD`, the child exits its loop.
- The supervisor immediately replaces it with a fresh child.

Relevant code:

- [app/worker.py](/Users/shaoqing/workspace/PageIndex/app/worker.py:314)

### 2. RSS watchdog

After each completed job, the child checks its own RSS:

- If RSS exceeds `WORKER_MAX_RSS_MB`, the child exits.
- The supervisor replaces it with a fresh child.

Relevant code:

- [app/worker.py](/Users/shaoqing/workspace/PageIndex/app/worker.py:326)

Important note:

- In Linux containers, the worker now reads current RSS from `/proc/self/status` (`VmRSS`) and falls back to `/proc/self/statm`.
- In local or non-Linux environments where `/proc` is unavailable, it falls back to `resource.getrusage(...).ru_maxrss`.
- This means production Docker runs now use true current RSS semantics, while local fallback remains conservative.

### 3. Manual-count hard limit

Each run now enforces a hard cap on manual fanout:

- `RUN_MAX_MANUALS`

If a knowledge base resolves more than this number, the run fails early instead of expanding unboundedly.

Relevant code:

- [app/services/chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py:1387)
- [app/services/compliance_service.py](/Users/shaoqing/workspace/PageIndex/app/services/compliance_service.py:1342)

## Structure Lazy Loading

This is the most important memory improvement in the current Phase 4.9 line.

### Old problem

The previous pattern loaded all parsed manual structures into memory during `load_structures`, before retrieval started. If a skill targeted many large manuals, the worker could hold all structure JSON trees simultaneously even though only a subset was actively being searched at any one moment.

That made `RETRIEVAL_MAX_CONCURRENCY` less meaningful from a memory perspective. The semaphore only throttled retrieval calls, not structure residency.

### Current behavior

The runtime now lazy-loads structure files inside the semaphore-protected retrieval function:

- load structure
- run retrieval
- `del structure`
- return candidates

Relevant code:

- [app/services/chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py:1414)
- [app/services/compliance_service.py](/Users/shaoqing/workspace/PageIndex/app/services/compliance_service.py:1361)

Why this matters:

- At most `RETRIEVAL_MAX_CONCURRENCY` manual structures are resident for retrieval at once.
- Large knowledge-base runs now scale memory with the semaphore window, not with total manual count.
- This directly removes one of the largest memory amplification paths in the old design.

### Practical assessment

Calling eager structure loading a “memory toxin” is directionally correct. It was one of the highest-risk patterns for large multi-manual runs because structure JSON is often the largest in-process object before answer generation begins.

That said, lazy loading does not make memory risk disappear completely. Large allocations can still come from:

- very large candidate pools
- very large context blocks
- very large streamed answers
- provider SDK response buffers

So the correct conclusion is:

- lazy loading fixes a major structural problem
- it does not, by itself, make the worker fully production-grade

## Rerank And Context Implications

The runtime now supports cross-manual rerank for skills and compliance. This improves evidence selection quality, but it also means candidate lists from multiple manuals are merged before final answer generation.

Memory is still accumulated in these later stages:

- `candidate_sections`
- reranked citation list
- `context_blocks`
- final answer buffer

This is acceptable for moderate `top_k`, but operators should still keep `RUN_MAX_MANUALS`, `RETRIEVAL_MAX_CONCURRENCY`, and retrieval defaults under control.

## Production Readiness Assessment

The current design is materially closer to production readiness than the earlier single-loop worker.

What is now in place:

- Redis disconnect recovery
- worker heartbeats and node registry
- multi-process worker supervisor
- child recycling by task count
- child recycling by RSS high-water
- knowledge-base multi-manual retrieval
- semaphore-bounded lazy structure loading
- run-level manual cap
- run-level observation timeline

What is still missing before calling it fully production-grade:

- sustained load testing with realistic large manuals
- explicit current-RSS telemetry instead of only peak RSS recycling
- stronger limits for candidate/context growth
- operator dashboards/alerts for recycle frequency and run failure reasons
- end-to-end chaos tests for Redis/network/process churn
- a green full migration smoke path on SQLite/MySQL CI

Current judgment:

- suitable for controlled deployment and production hardening
- not yet proven enough for unbounded production traffic claims

## Recommended Default Tuning

For a cautious first production rollout:

- `WORKER_PROCESS_COUNT=2`
- `WORKER_MAX_TASKS_PER_CHILD=50`
- `WORKER_MAX_RSS_MB=1024`
- `RETRIEVAL_MAX_CONCURRENCY=4` to `8`
- `RUN_MAX_MANUALS=10` to `20`

For larger nodes with enough RAM and provider capacity:

- increase `WORKER_PROCESS_COUNT` first
- increase `RETRIEVAL_MAX_CONCURRENCY` second

This ordering is intentional:

- more worker processes increases independent run throughput
- higher retrieval fanout mainly reduces latency inside each run but also increases memory and provider burstiness

## Operator Checklist

Before enabling this runtime for real traffic:

1. Set `TASK_QUEUE_BACKEND=redis`.
2. Use the Docker worker entrypoint so `MALLOC_ARENA_MAX=2` is applied in container runs.
3. Set `WORKER_PROCESS_COUNT`, `WORKER_MAX_TASKS_PER_CHILD`, `WORKER_MAX_RSS_MB`, and `RUN_MAX_MANUALS` explicitly.
4. Verify Redis heartbeats are visible under `WORKER_REGISTRY_PREFIX`.
5. Run at least one multi-manual skill and confirm:
   - `execution_context.target.resolved_mode == "multi_manual_federated"`
   - `execution_context.retrieval.documents_considered > 1`
   - observation events include `retrieve_candidates`, `rerank`, `build_context`, `final_answer`
6. Watch recycle frequency. If workers recycle too often, lower fanout or add more worker processes.

## Relevant Environment Variables

- `WORKER_PROCESS_COUNT`
- `WORKER_MAX_TASKS_PER_CHILD`
- `WORKER_MAX_RSS_MB`
- `WORKER_HEARTBEAT_INTERVAL_SECONDS`
- `WORKER_HEARTBEAT_TTL_SECONDS`
- `WORKER_RECONNECT_DELAY_MS`
- `WORKER_REGISTRY_PREFIX`
- `RETRIEVAL_MAX_CONCURRENCY`
- `RUN_MAX_MANUALS`
- `RUN_STEP_MAX_RETRIES`
- `RUN_STEP_RETRY_BASE_MS`
- `QUEUE_NAME_CHAT`
- `QUEUE_NAME_COMPLIANCE`
- `REDIS_URL`

Defaults are shown in:

- [.env.example](/Users/shaoqing/workspace/PageIndex/.env.example)
- [docker/.env.example](/Users/shaoqing/workspace/PageIndex/docker/.env.example)
