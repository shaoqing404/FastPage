# Phase 0: Initialization

## Goal

Deliver a working single-user FastAPI service that can:

1. support a hardcoded login entry
2. upload and manage PDF files
3. parse and reparse PDFs
4. retain multiple versions of the same logical PDF
5. ask questions through an OpenAI-compatible API
6. create, query, edit, and delete chat skills
7. expose progress and timing metrics
8. support a simple web UI later through stable API contracts

## Phase 0 Scope

### 1. Login

Implementation target:

- single hardcoded account in config
- session-based login for web usage
- one default tenant and one default user stored in metadata

Constraint:

- auth is intentionally weak in this phase
- all core tables and service functions still carry `tenant_id` and `user_id`

### 2. PDF Management

Required functions:

- upload PDF
- list PDFs
- view parsing status
- trigger parse
- trigger reparse
- mark current version
- restore an older version as active

Storage strategy:

- raw files stored under local filesystem
- parsed structure JSON stored beside file artifacts
- version history preserved per logical document

Suggested local directory layout:

```text
data/
  tenants/
    default/
      documents/
        {document_id}/
          meta.json
          versions/
            {version_id}/
              source.pdf
              structure.json
              logs/
```

### 3. Q&A via OpenAI-Compatible API

Input requirements:

- file name or document id
- question
- model name
- optional model flags such as reasoning / temperature / max tokens

Behavior:

- the service resolves the active document version
- it reuses cached parsed structure if present
- it selects relevant sections
- it retrieves page content
- it calls the configured OpenAI-compatible endpoint

### 4. Chat Skills

Definition:

Chat skills are reusable query presets that package:

- prompt template
- target files or file groups
- model name
- model request parameters
- optional reasoning settings
- optional retrieval settings

Required functions:

- create
- list
- get
- update
- delete
- run with a question payload

### 5. Metrics and Progress

Track at minimum:

- upload time
- parse start time
- parse finish time
- parse duration
- parse status
- query start time
- query finish time
- query duration
- current step for long-running parse jobs

Parse progress states:

- `uploaded`
- `queued`
- `parsing`
- `index_ready`
- `failed`

Query progress states:

- `accepted`
- `retrieving`
- `answering`
- `completed`
- `failed`

## Recommended Backend Structure

```text
app/
  main.py
  core/
    config.py
    auth.py
    db.py
    logging.py
  api/
    deps.py
    routers/
      auth.py
      documents.py
      skills.py
      chat.py
      metrics.py
  models/
    user.py
    tenant.py
    document.py
    document_version.py
    parse_job.py
    chat_skill.py
    chat_run.py
  schemas/
  services/
    storage_service.py
    document_service.py
    parse_service.py
    skill_service.py
    chat_service.py
    metrics_service.py
    pageindex_service.py
  workers/
    parse_worker.py
```

## Background Task Mechanism

Phase 0 baseline uses `asyncio + DB state persistence`.

Current implementation keeps that local mode, but also includes a Redis-backed queue mode as a forward-compatible bridge into Phase 1.

Do not introduce heavy queue systems such as Celery in this phase.

### Execution model

- parse requests create a `ParseJob` row first
- in local mode, the API layer schedules background parsing with `asyncio.create_task()`
- in Redis mode, the API layer enqueues a parse message and returns immediately
- the background task updates `ParseJob` state after every major step
- the frontend polls for progress instead of subscribing to push updates

### Runtime modes

Local compatibility mode:

- `TASK_QUEUE_BACKEND=local`
- web process runs parse execution inline through `asyncio.create_task()`
- useful for laptop-only development

Redis worker mode:

- `TASK_QUEUE_BACKEND=redis`
- web process only writes `ParseJob` and pushes queue messages
- a separate worker process must be running, for example `python -m app.worker`
- if worker is not running, jobs will remain at `uploaded` with `progress_percent=0`

### Parse lifecycle

The persisted parse states are:

- `uploaded`
- `queued`
- `parsing`
- `index_ready`
- `failed`

Expected transition:

```text
uploaded -> queued -> parsing -> index_ready
uploaded -> queued -> parsing -> failed
```

### Persistence rule

Every state change must be written into `ParseJob` immediately, including:

- `status`
- `current_step`
- `progress_percent`
- `started_at`
- `finished_at`
- `duration_ms`
- `error_message`

### Frontend refresh strategy

- use `GET /api/v1/jobs/{job_id}` for polling
- recommended polling interval: `2 seconds`
- stop polling when status becomes `index_ready` or `failed`

### Operational note

When the service is configured with external Redis:

- uploaded documents can appear to be accepted successfully
- parse jobs can still remain at `0%`
- the first thing to verify is whether `pageindex:parse` is accumulating queued messages and whether the worker process is alive

### Explicit non-goals in Phase 0

- no WebSocket progress channel
- no external job broker
- no distributed worker pool

Polling is sufficient for the first phase.

## Implementation Notes

- Do not bind business logic directly to local filesystem paths; wrap filesystem access behind `storage_service.py`.
- Do not bind business logic directly to one global user even though Phase 0 only exposes one user.
- Prefer explicit `document_id` and `version_id` everywhere internally.
- Persist parse and query state in the database, not just in-memory, so the web UI can refresh safely.

## Done Criteria

Phase 0 is done when:

- a user can log in
- upload a PDF
- view parse progress
- reparse and restore a previous version
- define a chat skill
- ask a question against a chosen document and model
- see timing and status on parse and query operations
- backend API contracts are stable enough to hand off to frontend work
