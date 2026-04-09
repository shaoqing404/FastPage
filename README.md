# PageIndex Service

`pageindex-service` is a service and console layer built on top of PageIndex. It packages the current Phase 3 FastAPI API, background worker, migrations, and React workspace console into an OSS-ready baseline for document ingest, knowledge-base management, skill chat, and compliance-style review flows.

This repository is based on and derived from [PageIndex](https://github.com/VectifyAI/PageIndex). It keeps the upstream [MIT license](/Users/shaoqing/workspace/PageIndex-main-integration/LICENSE) and does not claim to be the upstream PageIndex project itself. The role of this repo is the service surface around PageIndex capabilities.

## Project Positioning

PageIndex Service exposes a workspace-aware service surface for:

- document ingest and parse jobs
- knowledge bases and document membership
- skill authoring and skill chat
- queue-backed chat execution with a worker
- compliance checks and compliance runs
- tenant/workspace-aware data model foundations

Current branch baseline:

- `main` is intended to carry the public Phase 3 baseline
- `codex/phase3-backend` remains the working branch for follow-up fixes
- this OSS packaging targets Phase 3 only and intentionally does not expand Phase 4 product scope

## Current Capabilities

Backend:

- FastAPI API under `app/`
- Alembic migrations under `migrations/`
- Redis-backed worker entrypoint in `app/worker.py`
- local or MinIO-backed artifact storage
- MySQL or SQLite-compatible SQLAlchemy runtime
- auth, providers, documents, jobs, knowledge bases, chat, compliance, and metrics routes

Frontend:

- React + Vite workspace console under `frontend/`
- workspace overview
- documents
- knowledge bases
- skills and skill chat
- compliance checks and compliance runs
- provider/control-plane views

## Architecture

- API: FastAPI app in [app/main.py](/Users/shaoqing/workspace/PageIndex-main-integration/app/main.py)
- Worker: Redis queue consumer in [app/worker.py](/Users/shaoqing/workspace/PageIndex-main-integration/app/worker.py)
- DB: SQLAlchemy models plus Alembic migrations in [migrations/](/Users/shaoqing/workspace/PageIndex-main-integration/migrations)
- Storage: local filesystem or MinIO via [app/services/storage_service.py](/Users/shaoqing/workspace/PageIndex-main-integration/app/services/storage_service.py)
- Frontend: React/Vite console in [frontend/](/Users/shaoqing/workspace/PageIndex-main-integration/frontend)

## Quick Start

### Source startup (recommended)

1. Create a backend env file.

```bash
cp .env.example .env
```

2. Use Python 3.12 and install backend dependencies with `uv`.

```bash
uv sync --python 3.12
```

3. Run migrations.

```bash
uv run alembic upgrade head
```

4. Start the API.

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 22223 --reload
```

5. If using Redis-backed jobs, start the worker in a second shell.

```bash
uv run python -m app.worker
```

6. Start the frontend.

```bash
cd frontend
npm install
VITE_API_BASE_URL=http://127.0.0.1:22223/api/v1 npm run dev
```

If you need a non-`uv` fallback, the existing [requirements.txt](/Users/shaoqing/workspace/PageIndex-main-integration/requirements.txt) still supports a manual `venv + pip install -r requirements.txt` path.

### Docker Compose

The compose stack lives in [docker/docker-compose.yml](/Users/shaoqing/workspace/PageIndex-main-integration/docker/docker-compose.yml) and brings up:

- `api`
- `worker`
- `mysql`
- `redis`
- `minio`

Run:

```bash
cd docker
cp .env.example .env
bash start.sh
```

The default compose example publishes the API to `127.0.0.1:22223` and the MinIO console to `127.0.0.1:9001`.

## Environment Variables

Core:

- `APP_ENV`
- `API_HOST`
- `API_PORT`
- `DATA_DIR`
- `SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

Runtime services:

- `DATABASE_URL`
- `REDIS_URL`
- `TASK_QUEUE_BACKEND`
- `QUEUE_NAME_PARSE`
- `QUEUE_NAME_CHAT`
- `STORAGE_BACKEND`

Object storage:

- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`
- `MINIO_PREFIX_PATH`
- `MINIO_SECURE`

LLM/provider bootstrap:

- `LLM_BASE_URL`
- `LLM_API_KEY`

Chat worker behavior:

- `CHAT_RUN_REQUEST_TIMEOUT_SECONDS`
- `CHAT_RUN_LEASE_TIMEOUT_SECONDS`
- `CHAT_RUN_POLL_INTERVAL_MS`
- `CHAT_RUN_QUEUE_RETRY_DELAY_MS`

Browser/runtime:

- `CORS_ALLOW_ORIGINS`
- `CORS_ALLOW_ORIGIN_REGEX`
- `MAX_UPLOAD_BYTES`
- `PROVIDER_URL_ALLOW_PRIVATE_NETS`

Use [docker/.env.example](/Users/shaoqing/workspace/PageIndex-main-integration/docker/.env.example) for the containerized stack and [.env.example](/Users/shaoqing/workspace/PageIndex-main-integration/.env.example) for local backend development.

## Upstream Relationship

- Based on / derived from PageIndex
- Keeps the upstream MIT license
- Focuses on the service and console layer around PageIndex capabilities
- Does not rename the Python package tree aggressively; project-level naming is `PageIndex Service`

## Phase Status

This public baseline represents the current Phase 3 service productization state:

- tenant/workspace model foundation is present
- knowledge bases and compliance resources are present
- queue-backed chat worker plumbing is present
- README / Docker / env / runtime packaging have been tightened for OSS publication

Expected follow-up after this baseline:

- small fixes and closeout work
- additional runtime hardening
- no new Phase 4-scale feature expansion in this packaging pass

## Important Notes

- The frontend is a separate build from the API service. The root Dockerfiles package the backend API and worker, not a production frontend server.
- The recommended runtime baseline for source development is Python 3.12 plus `uv`.
- Do not expose raw uvicorn directly to the public internet without a reverse proxy, TLS termination, and explicit CORS configuration.
- Some Phase 3 semantics remain foundational rather than fully expanded product flows; see the specs in [spec/fastapi_service/phase3_service_productization/](/Users/shaoqing/workspace/PageIndex-main-integration/spec/fastapi_service/phase3_service_productization).
