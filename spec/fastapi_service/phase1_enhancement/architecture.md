# Phase 1 Architecture

## Goal

Move Phase 0 local single-process storage and background execution into a deployable service shape with:

- external relational persistence
- external object storage
- external queue / cache
- dedicated worker execution

## Recommended Stack

### Metadata

- `MySQL`
- application-specific database name, for example `pageindex`
- application-specific user, for example `pageindex_user`
- do not reuse `rag_flow` schema or application tables

### Artifact Storage

- `MinIO`
- dedicated bucket, for example `pageindex`
- if a dedicated bucket is not immediately available, use a dedicated prefix such as `pageindex-dev/`
- store source PDFs, parsed structure JSON, trace JSON, and future exports here

### Queue / Cache

- `Redis`
- queue backend for parse jobs and long-running chat jobs
- short-lived cache for parsed outline metadata and hot run telemetry

### Worker

- separate worker process
- recommended first step: `RQ` or `arq`
- acceptable alternative: Celery only if later throughput or workflow orchestration requires it

Reasoning:

- Phase 0 currently uses `asyncio.create_task()` inside the web process
- that is acceptable for local testing, but not for restarts, scaling, or long-running parse jobs

## Service Boundaries

### API Service

Responsibilities:

- auth
- tenant and user resolution
- document CRUD
- skill CRUD
- run creation
- status polling
- trace retrieval

Must not:

- perform long PDF parse work inline
- hold long-running retrieval tasks directly in the request process

### Worker Service

Responsibilities:

- parse PDF into structure
- execute skill/direct chat jobs when promoted to async execution
- write `ParseJob` and `ChatRun` state transitions back to MySQL
- write artifacts and traces to MinIO

## Persistence Design

### MySQL

Store:

- `tenants`
- `users`
- `documents`
- `document_versions`
- `parse_jobs`
- `chat_skills`
- `chat_skill_documents`
- `chat_runs`
- `revoked_tokens`
- future `api_keys`

Add in Phase 1:

- indexes on `(tenant_id, created_at)` for jobs and runs
- indexes on `(document_id, created_at)` for versions and runs
- indexes on `(skill_id, created_at)` for skill runs

### MinIO

Recommended object layout:

```text
tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/source.pdf
tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/structure.json
tenants/{tenant_id}/skill_traces/{skill_id}/{run_id}.json
tenants/{tenant_id}/exports/{export_id}/...
```

Rules:

- object keys are immutable once written
- document restore only changes metadata pointers, not object content
- trace files are append-safe only during active execution, then immutable after completion

## Execution Model

### Parse Jobs

State machine:

- `uploaded`
- `queued`
- `parsing`
- `index_ready`
- `failed`

Flow:

1. API creates `ParseJob`
2. API enqueues worker message in Redis
3. Worker loads source PDF from MinIO or local compatibility layer
4. Worker writes progress back to MySQL
5. Worker writes `structure.json` to MinIO
6. Worker updates `DocumentVersion.parse_status` and `Document.status`

### Chat Runs

Phase 1 recommendation:

- keep direct question endpoint synchronous for short documents if desired
- add optional async path for long-running skill executions

Async state machine:

- `accepted`
- `retrieving`
- `answering`
- `completed`
- `failed`

Persist for every run:

- resolved model
- resolved system prompt
- resolved request config
- selected sections
- telemetry metrics
- trace object path

## Config Contract

Recommended Phase 1 env vars:

- `DATABASE_URL`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`
- `MINIO_SECURE`
- `REDIS_URL`
- `QUEUE_NAME_PARSE`
- `QUEUE_NAME_CHAT`

## Migration Rules

### Database

- use Alembic for schema migration
- do not rely on `create_all()` once MySQL is adopted

### Storage

- keep a storage abstraction layer
- support local FS in development and MinIO in staging/production

### Queue

- create a task abstraction so parse scheduling is not tied to `asyncio.create_task()`

## Operational Rules

- never use MySQL `root` as the application account
- never use a shared third-party application schema like `rag_flow`
- never reuse default `minioadmin` in production
- every external component must have app-specific credentials and namespace isolation

## First Implementation Slice

Implement in this order:

1. add storage abstraction with local FS and MinIO backends
2. add queue abstraction with local inline mode and Redis worker mode
3. switch SQLAlchemy config from SQLite to MySQL via `DATABASE_URL`
4. add Alembic migrations
5. move parse jobs to worker process
6. move trace artifacts from local disk to MinIO

## Current Validation Status

The current codebase has already validated the following external component path:

- MySQL connectivity to a dedicated `pageindex` schema
- MinIO connectivity to a dedicated `pageindex` bucket
- Redis enqueue for parse jobs on `pageindex:parse`

Observed behavior during validation:

- uploaded documents were persisted correctly
- `ParseJob` rows were created correctly
- when no worker process was running, jobs remained at `status=uploaded`, `current_step=uploaded`, `progress_percent=0`
- Redis queue length increased exactly as expected

Operational implication:

- once `TASK_QUEUE_BACKEND=redis` is enabled, the worker process is no longer optional
- “upload succeeded but progress stays 0” should be treated first as a worker-availability problem, not a parser problem

## MySQL Compatibility Rule

ORM field definitions must remain MySQL-safe.

Specifically:

- every SQLAlchemy `String` column must declare an explicit length
- relying on SQLite behavior is not acceptable once MySQL is introduced
- `create_all()` can be used only as a temporary bootstrap aid; Alembic must become the source of truth in the next slice
