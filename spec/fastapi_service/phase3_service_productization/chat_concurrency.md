# Phase 3.2: Chat Concurrency and Execution Isolation

## Scope

This document is a current-state audit plus design spec for Phase 3.2. It is based on the current code and the already-approved Phase 3 direction, not on a greenfield rewrite.

Required baseline assumptions for this design:

1. `tenant` is the hard isolation boundary.
2. `workspace` is an in-tenant resource organization boundary.
3. parse already has a Redis worker pattern.
4. chat still executes inside the API process today.
5. Phase 2 SSE happy path and abort semantics must remain compatible.

Primary code inputs:

- [chat.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/chat.py)
- [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py)
- [task_queue_service.py](/Users/shaoqing/workspace/PageIndex/app/services/task_queue_service.py)
- [worker.py](/Users/shaoqing/workspace/PageIndex/app/worker.py)
- [config.py](/Users/shaoqing/workspace/PageIndex/app/core/config.py)
- [session_service.py](/Users/shaoqing/workspace/PageIndex/app/services/session_service.py)
- [chat_run.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_run.py)
- [chat_session.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_session.py)
- [principal.py](/Users/shaoqing/workspace/PageIndex/app/core/principal.py)

Compatibility inputs:

- [README.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/README.md)
- [tenant_and_workspace_model.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/tenant_and_workspace_model.md)
- [foundations.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/foundations.md)
- [skill_chat_stream_contract.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/skill_chat_stream_contract.md)
- [phase2_exit_report.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/phase2_exit_report.md)

## Current-State Audit

### 1. Chat execution still blocks API-process capacity

Current state:

- `POST /api/v1/chat/ask` directly awaits `create_chat_run(...)`.
- `POST /api/v1/chat/skills/{skill_id}/run` directly awaits either `create_chat_run(...)` or streams `stream_skill_run_events(...)`.
- retrieval and answer generation both run inline in the request-serving process.

Observed consequences:

- long retrieval or provider latency ties up API worker capacity
- SSE streaming keeps one request handler open for the full answer lifetime
- non-stream and stream runs compete for the same API-process resources
- one noisy tenant can degrade unrelated tenants because no execution isolation exists

This is exactly the Phase 3.2 gap called out in the Phase 3 README: parse is queue-backed, chat is not.

### 2. Session message ordering is vulnerable to concurrent writes

Current state:

- `append_message(...)` in [session_service.py](/Users/shaoqing/workspace/PageIndex/app/services/session_service.py) computes `next_sequence` as `max(sequence_no) + 1`.
- there is no row lock, no optimistic compare-and-swap, and no unique constraint on `(session_id, sequence_no)`.
- both `create_chat_run(...)` and `stream_skill_run_events(...)` append the user message before execution and append the assistant message after completion.

Observed risks:

- two concurrent runs against the same session can read the same max sequence and write duplicate `sequence_no`
- even if duplicate sequence values do not occur, interleaving can still reorder turns:
  - run A appends user
  - run B appends user
  - run B finishes first and appends assistant
  - run A finishes later and appends assistant
- `_load_session_history(...)` reads ordered history by `sequence_no`, so turn corruption feeds directly into later prompt construction

Conclusion:

- current code does not guarantee deterministic session ordering under concurrency
- same-session concurrent run execution is unsafe unless session sequencing is redesigned

### 3. Cancel and abort semantics are only best-effort inside one request lifecycle

Current state:

- Phase 2 added `request.is_disconnected` checks into `stream_skill_run_events(...)`.
- disconnect triggers `asyncio.CancelledError`, and the run is marked `failed` with `metrics.error = "client aborted stream"`.
- no durable cancel request flag exists in the database or Redis.
- there is no user-facing stop endpoint.
- non-stream `create_chat_run(...)` has no cooperative cancellation path.

Observed risks:

- browser disconnect only works while the API coroutine is still alive
- once execution moves to a worker model, request disconnect alone is no longer sufficient
- current `failed` status conflates three different outcomes:
  - genuine provider/retrieval failure
  - client disconnect
  - future timeout / operator cancellation

Compatibility note:

- Phase 2 contract explicitly accepted best-effort abort and the current `failed` marking for disconnect
- Phase 3 must preserve that behavior as an externally compatible path, even if the internal state model becomes more precise

### 4. No per-tenant fairness exists today

Current state:

- `Principal` carries `tenant_id` but there is no per-tenant concurrency controller.
- chat routes filter reads by tenant, but execution admission is global and unmanaged.
- no tenant-local in-flight counters, queue depths, or rate limits exist.

Observed risks:

- one tenant can flood expensive retrieval/LLM work
- other tenants cannot be protected except by total process capacity exhaustion
- backlog and starvation are invisible

This is inconsistent with the approved Phase 3 tenant model where tenant remains the hard service boundary.

### 5. Worker restart, retry, and orphan handling are defined for parse only, not for chat

Current state:

- parse uses a simple Redis `RPUSH` + worker `BLPOP` pattern.
- the worker handles `kind == "parse_job"` only.
- no ack, lease, heartbeat, dead-letter, or retry metadata exists even for parse.
- chat has no background execution path at all.

Observed chat-specific risks if naively copied:

- if a worker dies after popping a chat run, the message is lost unless run state is durable
- if a worker dies mid-answer, the session may contain a user message with no terminal assistant message
- automatic retry after partial answer generation is not safe because provider calls and session ordering are not idempotent
- orphaned `accepted/retrieving/answering` runs will otherwise remain stuck forever

Conclusion:

- chat needs a worker-safe state machine, claim metadata, heartbeat, and orphan reaper before Redis worker execution is acceptable
- parse queue simplicity is still useful, but chat cannot rely on a blind `BLPOP -> run -> forget` model

### 6. Existing run state is too narrow for queued worker execution

Current state:

- `ChatRun.status` is a free-form string.
- current code uses: `accepted`, `retrieving`, `answering`, `completed`, `failed`.
- `QUEUE_NAME_CHAT` already exists in config but is unused.

Observed gaps:

- no `queued`
- no durable `cancel_requested`
- no worker claim identity
- no heartbeat or lease timestamp
- no timeout classification
- no retry/orphan reason code

Conclusion:

- `ChatRun` is close enough to extend, but not yet sufficient as the source of truth for queued execution

### 7. Tenant/workspace model implications

Current state:

- tenant is already the isolation key in sessions, runs, messages, documents, providers
- workspace does not yet exist in code
- session listings are tenant-wide, not user-private

Concurrency implication:

- Phase 3.2 limits must be tenant-scoped by default because workspace does not yet exist in runtime execution paths
- workspace-aware overrides may be layered later, but they cannot be the primary Phase 3.2 enforcement key

## Architecture Options

### Option A: Redis-backed chat worker plus SSE bridge

#### Summary

Move chat execution into Redis-backed workers, reuse `QUEUE_NAME_CHAT`, and keep the current SSE API surface by turning the API process into a bridge:

1. API validates request and creates a `ChatRun`.
2. API enqueues a chat work item on Redis.
3. API subscribes to worker-emitted run events and relays them as SSE.
4. Worker executes retrieval and generation outside the API process.
5. Worker writes authoritative run/session state to the database.
6. Browser disconnect or user stop becomes a durable cancel request, not only an in-memory signal.

#### Suggested event transport

Use Redis Pub/Sub or Redis Streams per run for transient event fanout:

- queue transport: Redis list on `QUEUE_NAME_CHAT`
- live event transport: `pageindex:chat:events:{run_id}`
- durable source of truth: database `ChatRun` and `ChatMessage`

Why this split:

- queue and live event fanout have different requirements
- database remains the readback/fallback source
- SSE does not need to read the worker process directly

#### Flow

1. API validates tenant, skill, document, session.
2. API decides whether same-session execution is admissible.
3. API creates run in `accepted`.
4. API enqueues payload `{kind: "chat_run", run_id: ..., tenant_id: ..., ...}` on `QUEUE_NAME_CHAT`.
5. API immediately emits `run_started` and `status=accepted`.
6. If worker claim is delayed, API may emit `status=queued`.
7. Worker claims run, emits `status=retrieving`, then `context`, then `status=answering`, then `answer_delta*`, then terminal status and `run_completed`.
8. If client disconnects, API writes a cancel request flag and unsubscribes; worker stops at the next cooperative checkpoint.

#### Strengths

- preserves Phase 2 streaming UX
- removes heavy chat execution from API process
- reuses Redis worker deployment shape already present for parse
- allows one implementation path for stream and non-stream execution
- naturally supports readback fallback from `GET /runs/{run_id}`

#### Weaknesses

- more moving parts than current direct execution
- requires event bridge lifecycle management
- needs durable cancel and orphan cleanup logic
- requires worker-friendly DB session handling instead of reusing request-scoped session objects

### Option B: Queued run plus polling/readback fallback

#### Summary

Move execution to Redis-backed workers, but do not bridge token events through the API. The API returns a queued run immediately and the client polls for state and final answer.

#### Flow

1. API validates request and creates `ChatRun`.
2. API enqueues work on `QUEUE_NAME_CHAT`.
3. API returns `202`-style accepted payload or normal `ChatRunOut` with `status=queued`.
4. Client polls:
   - `GET /runs/{run_id}`
   - optionally `GET /chat/sessions/{session_id}/messages`
5. Final answer appears only when run reaches `completed`.

#### Optional extension

If partial answer persistence is needed later, worker can periodically write `answer_text_so_far` into `ChatRun`, but this is not required for the baseline option.

#### Strengths

- operationally simpler than live SSE bridging
- no live event transport dependency
- easiest way to get API-process isolation quickly
- robust for mobile/background clients and infra with SSE instability

#### Weaknesses

- loses the current Phase 2 streaming experience
- would require frontend contract change or a separate fallback mode
- answer latency becomes less visible
- stop/cancel feedback is slower

#### Compatibility assessment

This is viable as a fallback mode, but it is not the best primary design because Phase 2 already fixed the skill SSE happy path and current product UX expects streaming.

## Recommended Design

### Recommendation

Adopt Option A as the primary design:

- Redis-backed chat worker
- `QUEUE_NAME_CHAT` for work dispatch
- SSE bridge in the API layer
- database as durable run state source of truth
- polling/readback retained as fallback

This best matches the Phase 3 objective and minimizes conceptual divergence from the existing parse queue pattern while preserving Phase 2 stream behavior.

### Design principles

1. Reuse the existing parse queue deployment shape, but add chat-specific safety features.
2. Keep Phase 2 SSE happy path intact for immediate runs.
3. Make cancellation durable and cooperative.
4. Treat tenant as the default concurrency fairness boundary.
5. Do not allow unsafe same-session parallel execution.
6. Do not auto-retry a run once worker execution has actually started.

### Recommended execution model

#### 1. Admission and persistence

On `POST /api/v1/chat/skills/{skill_id}/run` with `stream=true`:

- perform the same pre-stream validation currently done in the API process
- create or resolve `session_id`
- reject if the session already has an active run
- create `ChatRun` in `accepted`
- persist initial execution metadata and request payload snapshot
- enqueue a chat message onto `QUEUE_NAME_CHAT`
- attach SSE bridge

On `stream=false`:

- follow the same queue-backed run creation path
- by default still block until completion only if the API bridge is explicitly kept
- preferred Phase 3 behavior is to return run state immediately and let the client read back

Design note:

- for Phase 3.2, it is acceptable for `stream=false` skill runs to become queue-backed and return an early `ChatRunOut` in `accepted/queued`
- the streaming contract is the compatibility priority, not synchronous completion latency

#### 2. Worker claim and lease

When a worker pops a chat job:

- open a fresh DB session
- atomically move run from `accepted` or `queued` to `retrieving`
- store:
  - `worker_node_code`
  - `claimed_at`
  - `heartbeat_at`
  - `attempt_count`
- refuse claim if run is already terminal or cancellation was requested before start

Worker heartbeat:

- update `heartbeat_at` during long retrieval/generation steps
- heartbeat interval should be shorter than worker timeout threshold

#### 3. Event bridge behavior

The SSE bridge is compatibility-focused, not authoritative:

- `run_started` and `status=accepted` are emitted by the API after run creation
- optional `status=queued` is emitted only if the run waits beyond a short queue threshold
- all later status, context, delta, and terminal events are forwarded from worker events
- if the SSE bridge disconnects, execution may continue only until cancellation is cooperatively observed

#### 4. Poll/readback fallback

Every streamed run must also be inspectable through existing read APIs:

- `GET /api/v1/runs/{run_id}` is the canonical fallback for final state
- `GET /api/v1/chat/.../messages` remains the canonical session readback

This is required because:

- browsers may disconnect
- SSE proxies may buffer or drop
- operators need observability without attaching to a live stream

### Run state machine

#### Canonical states

- `accepted`
- `queued`
- `retrieving`
- `answering`
- `completed`
- `failed`
- `cancelled`

#### State meanings

- `accepted`: API validated request and persisted the run, but queue handoff is not yet confirmed.
- `queued`: run is durably enqueued and waiting for worker claim.
- `retrieving`: worker claimed the run and is performing query rewrite, retrieval, context assembly, or equivalent pre-answer work.
- `answering`: worker is generating the final answer stream.
- `completed`: answer finished successfully and final artifacts/messages are committed.
- `failed`: execution ended due to non-cancellation error, worker loss, invalid upstream response, or unrecoverable internal problem.
- `cancelled`: execution was intentionally stopped due to browser disconnect propagation, user stop, or timeout enforcement.

#### Allowed transitions

- `accepted -> queued`
- `accepted -> retrieving`
- `accepted -> cancelled`
- `queued -> retrieving`
- `queued -> cancelled`
- `retrieving -> answering`
- `retrieving -> failed`
- `retrieving -> cancelled`
- `answering -> completed`
- `answering -> failed`
- `answering -> cancelled`

Disallowed:

- any transition out of `completed`
- any transition out of `failed`
- any transition out of `cancelled`
- `queued -> completed`
- `accepted -> completed`

#### Phase 2 compatibility rule

For happy-path streaming, the externally observed sequence must remain compatible with:

- `run_started`
- `status=accepted`
- `status=retrieving`
- `context`
- `status=answering`
- `answer_delta*`
- `status=completed`
- `run_completed`

Compatibility interpretation:

- `status=queued` is allowed only as an additive event when queue wait actually happens
- existing clients that only understand the old happy path must still work when the worker claims quickly and no queue wait occurs

### Cancel semantics

#### 1. Browser disconnect

Required behavior:

- preserve Phase 2 meaning: best-effort stop of the run
- store a durable cancel request instead of relying only on the request coroutine

Recommended semantics:

- API bridge detects disconnect
- API marks `cancel_requested_at` with reason `client_disconnect`
- worker checks cancel request:
  - before retrieval
  - after retrieval
  - inside token streaming loop
  - before final commit
- final persisted state becomes `cancelled`
- metrics carry:
  - `cancel_reason = "client_disconnect"`
  - `error = "client aborted stream"` for Phase 2 continuity

Compatibility note:

- the disconnected browser is not guaranteed to receive terminal SSE events
- readback APIs must show the run as terminal, not stuck

#### 2. User active stop

Add a stop endpoint in Phase 3.2 API implications:

- `POST /api/v1/runs/{run_id}/cancel`

Required behavior:

- only the same tenant may cancel the run
- if the run is still `accepted` or `queued`, it transitions directly to `cancelled`
- if already `retrieving` or `answering`, worker observes the cancel request cooperatively and transitions to `cancelled`
- repeated cancel requests are idempotent

SSE implication:

- if bridge is still attached, it may emit `status=cancelled`
- `run_completed` is not emitted for cancelled runs
- optional additive terminal `error` event may use code `skill_stream_cancelled`, but this is not required for Phase 3.2

#### 3. Worker timeout

Recommended semantics:

- a run exceeding `CHAT_RUN_TIMEOUT_SECONDS` is cancelled by the system, not retried in place
- terminal state becomes `cancelled`
- metrics carry:
  - `cancel_reason = "timeout"`
  - `error_code = "run_timeout"`

Reasoning:

- timeout is an intentional stop, not a provider correctness failure
- using `cancelled` keeps it distinct from genuine execution errors

### Session ordering rules

#### Rule

Same-session concurrent runs are not allowed in Phase 3.2.

This is the default and recommended rule.

Reasoning:

- current message model uses monotonic per-session `sequence_no`
- prompt history uses ordered session messages
- allowing parallel same-session runs would either corrupt ordering or require a larger turn-model redesign than Phase 3.2 should absorb

#### Enforcement

A session is considered busy if it has a run in:

- `accepted`
- `queued`
- `retrieving`
- `answering`

Admission behavior:

- if `session_id` is present and a busy run exists, return `409 Conflict`
- machine-readable code should be something like `SESSION_RUN_ACTIVE`

Why reject instead of queue behind the session:

- it preserves clear user intent and predictable SSE behavior
- it avoids hidden turn serialization latency
- it keeps Phase 3.2 implementation smaller and safer

Non-goal for this phase:

- no implicit per-session FIFO run queue

If later required, a per-session queue can be added explicitly, but it should not be the Phase 3.2 baseline.

### Per-tenant concurrency control

#### Default concurrency boundary

Default enforcement should be tenant-level, not workspace-level and not user-level.

Reasoning:

- tenant is the hard isolation boundary
- workspace is not yet part of the current execution path
- user-level limits do not protect tenants from self-starvation caused by many users

#### Recommended limits

At minimum define:

- `CHAT_MAX_INFLIGHT_PER_TENANT`
- `CHAT_MAX_QUEUED_PER_TENANT`
- `CHAT_RUN_TIMEOUT_SECONDS`
- `CHAT_WORKER_HEARTBEAT_SECONDS`
- `CHAT_ORPHAN_REAP_SECONDS`

Enforcement model:

- API admission checks queued plus active run counts per tenant
- worker claim checks tenant active slots again before moving a run into `retrieving`
- if the tenant queue is full, reject early with `429` or `409` style limit error

Recommended default semantics:

- cap in-flight by tenant
- allow small tenant-local queue backlog
- keep worker concurrency global, but fair claim logic must prevent one tenant from consuming all active slots

#### Fairness mechanism

Minimum acceptable Phase 3.2 mechanism:

- per-tenant active slot accounting in Redis
- per-tenant queued count accounting in Redis or DB
- worker claim only succeeds if the tenant has free active capacity

Scheduling guidance:

- global single queue is acceptable if worker claim checks tenant capacity before execution
- if fairness remains poor in practice, upgrade later to per-tenant subqueues plus round-robin claim

### Worker restart, retry, and orphan policy

#### Retry policy

Do not auto-retry runs that have already entered `retrieving` or `answering`.

Reason:

- retrieval and especially answer generation are not safely idempotent
- auto-retry can duplicate session-side effects or generate divergent answers

Safe retry window:

- runs stuck in `accepted` or `queued` before worker claim may be re-enqueued by an operator or reconciler

#### Orphan detection

Add a periodic reconciler or worker-side sweep:

- if run is `retrieving` or `answering`
- and `heartbeat_at` is older than `CHAT_ORPHAN_REAP_SECONDS`
- mark the run `failed`
- record `error_code = "worker_lost"`
- release tenant slot accounting

Why `failed` instead of `cancelled` for worker loss:

- worker disappearance is not an intentional stop requested by client or system policy
- it is an execution failure

#### Lost queue item protection

Use the database run row as durable truth:

- API should move run `accepted -> queued` only after Redis enqueue succeeds
- if enqueue fails, keep run terminalized as `failed` or delete the fresh row
- startup reconciliation may requeue old `accepted` runs that were never enqueued successfully only if they have no claim metadata

### Workspace and tenant model relation

#### Default rule for Phase 3.2

Concurrency and fairness are enforced by tenant.

Workspace is not the primary execution-isolation boundary.

#### Why not workspace first

- workspace does not yet exist in the current runtime model
- moving fairness to workspace before workspace resource ownership exists would create policy drift
- tenant-level protection is required regardless of future workspace support

#### Future-friendly extension

Once `workspace_id` exists on sessions/runs, the design should support:

- tenant hard cap
- optional workspace soft cap
- workspace-local queue visibility

But Phase 3.2 should not block on that schema expansion.

## API Implications

### Existing endpoints

Keep existing stream endpoints:

- `POST /api/v1/chat/skills/{skill_id}/run` with `stream=true`
- `POST /api/v1/chat/skills/{skill_id}/run/stream`

Keep existing read endpoints:

- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- session/message read APIs

### New or changed behaviors

#### 1. Streaming request may show `queued`

If worker claim is not immediate, SSE may emit:

- `status=queued`

This is additive and must not replace the established happy path when no queue wait exists.

#### 2. Same-session conflict

When a session already has an active run:

- return `409`
- stable error code: `SESSION_RUN_ACTIVE`

#### 3. Cancel endpoint

Add:

- `POST /api/v1/runs/{run_id}/cancel`

Response semantics:

- terminal or already-cancel-requested runs return success idempotently
- response payload may be current `ChatRunOut`

#### 4. Read APIs must expose new terminal status

`ChatRunOut.status` must allow:

- `queued`
- `cancelled`

This is additive and backward-compatible for tolerant clients.

## Data Model Implications

### `chat_runs`

Extend `ChatRun` with fields equivalent to:

- `status`
- `cancel_requested_at`
- `cancel_reason`
- `worker_node_code`
- `claimed_at`
- `heartbeat_at`
- `attempt_count`
- `queued_at`
- optional `last_error_code`

Exact column names may vary, but Phase 3.2 requires equivalent semantics.

### `chat_messages`

Strengthen ordering guarantees:

- add a uniqueness constraint on `(session_id, sequence_no)`
- stop using plain `max(sequence_no) + 1` without serialization protection

Preferred implementation direction for later implementation phase:

- lock the session row or use a dedicated per-session sequence counter on `chat_sessions`

### `chat_sessions`

Phase 3.2 does not require a full session redesign, but it should add enough support for safe sequencing, for example:

- `next_message_sequence`
- optional `active_run_id` if a strict same-session single-flight model is preferred

## Observability

Minimum metrics and visibility required:

- tenant in-flight run count
- tenant queued run count
- global chat queue backlog
- worker lag
- worker heartbeat freshness
- timeout counter
- cancel counter by reason
- failed counter by reason
- orphaned run counter
- session-conflict rejection counter

Suggested metric names:

- `pageindex_chat_runs_inflight{tenant_id=...}`
- `pageindex_chat_runs_queued{tenant_id=...}`
- `pageindex_chat_queue_backlog`
- `pageindex_chat_worker_lag_seconds`
- `pageindex_chat_run_timeouts_total`
- `pageindex_chat_run_cancellations_total{reason=...}`
- `pageindex_chat_run_failures_total{reason=...}`
- `pageindex_chat_session_conflicts_total`

Queue visibility requirement:

- operators must be able to determine whether delay is caused by queue backlog, worker loss, tenant cap, or provider latency

## Acceptance Criteria

### Current-state audit acceptance

- the Phase 3.2 implementation plan explicitly addresses:
  - API-process blocking
  - session ordering corruption risk
  - cancel/abort consistency
  - tenant fairness
  - worker restart, retry, and orphan handling

### Architecture acceptance

- chat execution can run through Redis-backed workers using `QUEUE_NAME_CHAT`
- streaming clients still observe the Phase 2 happy path when queue wait does not occur
- queued runs can still be inspected through readback APIs

### State machine acceptance

- `accepted`, `queued`, `retrieving`, `answering`, `completed`, `failed`, `cancelled` are defined
- terminal states are immutable
- orphan reconciliation prevents indefinite stuck active runs

### Session ordering acceptance

- same-session concurrent runs are rejected with a stable conflict response
- message sequencing is protected against duplicate or out-of-order `sequence_no`
- session history remains deterministic for later turns

### Cancellation acceptance

- browser disconnect records a durable cancellation request
- user stop is idempotent
- timeout yields terminal non-stuck run state
- terminal cancelled runs are observable through `GET /runs/{run_id}`

### Tenant fairness acceptance

- one tenant cannot consume unlimited active chat workers
- tenant-local in-flight counts and queue backlog are observable
- worker lag and timeout/retry/orphan counters are exposed

## Final Recommendation

Phase 3.2 should implement chat as a Redis-backed worker flow with SSE bridging and readback fallback.

This is the smallest design that simultaneously:

- preserves the Phase 2 stream contract
- reuses the existing parse queue mental model
- uses the already-defined `QUEUE_NAME_CHAT`
- introduces tenant-aware concurrency control
- creates a credible path for worker isolation and service productization

The critical policy decisions for this phase are:

1. tenant is the default concurrency boundary
2. same-session concurrent runs are disallowed
3. cancellation becomes durable and cooperative
4. `cancelled` is introduced as a first-class terminal state
5. started runs are not auto-retried after worker loss
