# PageIndex Service

`PageIndex Service` is a deployable service and console layer built on top of [PageIndex](https://github.com/VectifyAI/PageIndex). It packages the current Phase 3 FastAPI API, workspace console, migrations, and background execution model into a runnable baseline for document ingest, knowledge bases, skill chat, and compliance-style review flows.

This repository is based on and derived from PageIndex, keeps the upstream [MIT license](LICENSE), and does not claim to be the upstream PageIndex project itself. The role of this repo is the service surface around PageIndex capabilities. Thanks to the PageIndex team for the upstream framework and open-source release this work builds on.

This project should be read as an implementation-oriented packaging of PageIndex into a more directly deployable service baseline. Future roadmap work will consider Kubernetes-friendly deployment and equivalent substitutions for Redis, MySQL, and MinIO in domestic or environment-specific stacks.

## Project Positioning

PageIndex Service currently exposes a workspace-aware service surface for:

- document ingest and parse jobs
- knowledge bases and document membership management
- skill authoring and skill chat
- compliance checks and compliance runs
- queue-backed chat execution
- tenant and workspace-aware data modeling

Current scope:

- this repository targets the Phase 3 baseline
- the goal is integration and productization, not Phase 4 feature expansion
- follow-up work should stay in the range of fixes, hardening, and packaging improvements

## API Surface Overview

The current API is organized into 10 route groups under `app/api/routers`:

- `auth`: admin login and token issuance
- `documents`: document upload, parse lifecycle, and retrieval metadata
- `jobs`: parse job status and job-oriented operations
- `knowledge_bases`: knowledge base CRUD and document membership
- `skills`: skill definitions, traces, and skill execution metadata
- `chat`: chat sessions, chat runs, and queue-backed runtime flow
- `compliance_checks`: compliance check definitions
- `compliance_runs`: compliance execution and results
- `providers`: LLM/provider configuration surfaces
- `metrics`: basic service metrics endpoints

Core runtime entrypoints:

- API: `app/main.py`
- worker: `app/worker.py`
- config: `app/core/config.py`
- storage: `app/services/storage_service.py`
- migrations: `migrations/`
- frontend console: `frontend/`

## Current Capabilities

- document ingest and parse
- knowledge base management
- skill chat
- compliance checks and runs
- queue-backed worker execution
- local or MinIO-backed artifact storage
- SQLite or MySQL-backed database runtime
- React workspace console for documents, KB, skills, chat, and compliance flows

## Architecture

- API: FastAPI app serving `/api/v1/*` and `/healthz`
- Worker: separate queue consumer process, only used when `TASK_QUEUE_BACKEND=redis`
- DB: SQLAlchemy + Alembic, compatible with SQLite for local mode and MySQL for full mode
- Storage: local filesystem or MinIO object storage
- Frontend: Vite + React console under `frontend/`

## Deployment Modes

PageIndex Service supports two clearly separated runtime modes:

1. complete component mode
2. minimal startup mode

Detailed container instructions live in [docker/README.md](docker/README.md).

### Database Runtime Selection

Database env parsing now follows one simple priority order:

1. `DATABASE_URL`
2. `DATABASE_MODE`
3. mode-specific parts

Recommended usage:

- local development: keep `DATABASE_MODE=sqlite`
- remote or shared deployment: set `DATABASE_MODE=mysql` and fill `MYSQL_*`
- expert override: set `DATABASE_URL` directly only when you intentionally want to bypass the normal mode-based config

SQLite mode behavior:

- default mode is `sqlite`
- if `DATABASE_URL` is empty and `DATABASE_MODE` is unset, the service uses local SQLite automatically
- default SQLite file is `${DATA_DIR}/app.db`
- optional `SQLITE_PATH` can move the SQLite file, but it is not required

MySQL mode behavior:

- set `DATABASE_MODE=mysql`
- fill `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`
- no hand-written `DATABASE_URL` is required in the normal MySQL path

### 1. Complete Component Mode

Recommended deployment mode:

- MySQL
- Redis
- MinIO
- API
- Worker

This is the recommended production-style deployment shape.

Required settings:

- `APP_ENV=prod` or `APP_ENV=dev`
- `API_HOST`
- `API_PORT`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `SECRET_KEY`
- `DATABASE_MODE=mysql`
- `MYSQL_HOST=<mysql-host>`
- `MYSQL_PORT=3306`
- `MYSQL_DATABASE=pageindex`
- `MYSQL_USER=<user>`
- `MYSQL_PASSWORD=<pass>`
- `TASK_QUEUE_BACKEND=redis`
- `REDIS_URL=redis://:<redis-password>@<redis-host>:6379/1`
- `STORAGE_BACKEND=minio`
- `MINIO_ENDPOINT=<minio-host>:9000`
- `MINIO_ACCESS_KEY=<access-key>`
- `MINIO_SECRET_KEY=<secret-key>`
- `MINIO_BUCKET=pageindex`
- `MINIO_PREFIX_PATH=`
- `MINIO_SECURE=false` or `true`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `CHAT_RUN_REQUEST_TIMEOUT_SECONDS`
- `CHAT_RUN_LEASE_TIMEOUT_SECONDS`
- `CHAT_RUN_QUEUE_RETRY_DELAY_MS`
- `CORS_ALLOW_ORIGINS`

Optional expert override:

- `DATABASE_URL=mysql+pymysql://<user>:<pass>@<mysql-host>:3306/pageindex`

Startup order:

1. Start MySQL, Redis, and MinIO.
2. Configure the environment file.
3. Execute `alembic upgrade head`.
4. Start the API.
5. Start the Worker.
6. Then access the frontend or API.

Docker Compose entrypoint:

```bash
cd docker
cp .env.example .env
docker compose --profile full up -d --build
docker compose --profile full exec api alembic upgrade head
```

Important notes:

- `worker` only runs when `TASK_QUEUE_BACKEND=redis`
- production should prefer complete component mode
- if the API is exposed externally, `API_HOST=0.0.0.0` should only be used behind a reverse proxy and TLS
- reverse-proxy upload limits must be aligned with `MAX_UPLOAD_BYTES`

Demo credentials in the Docker examples intentionally use `pageindex_service123` for:

- MySQL root and application passwords
- Redis password
- MinIO access key and secret key
- `ADMIN_PASSWORD`

These defaults are only for:

- local demo
- test environments
- documentation examples

Production warning:

- replace every demo password
- generate a separate long random `SECRET_KEY`
- do not use plain `pageindex_service123` as a production `SECRET_KEY`

### 2. Minimal Startup Mode

Use this mode when MySQL, Redis, and MinIO are unavailable and you still want to validate the service locally.

Minimal settings:

- `APP_ENV=dev`
- `API_HOST=127.0.0.1`
- `API_PORT=22223`
- `ADMIN_USERNAME=admin`
- `ADMIN_PASSWORD=change-me-local-admin-password`
- `SECRET_KEY=change-me-local-dev-secret-key`
- `DATABASE_MODE=sqlite`
- `DATA_DIR=./data`
- optional `SQLITE_PATH=./somewhere/pageindex.db`
- `STORAGE_BACKEND=local`
- `TASK_QUEUE_BACKEND=local`
- `REDIS_URL=` empty
- `MINIO_*=` empty
- `LLM_BASE_URL`
- `LLM_API_KEY`

Minimal mode behavior:

- uses SQLite
- writes files to local `DATA_DIR`
- parse/chat do not require a Redis worker
- no standalone worker process is needed
- best for local development, self-test, and frontend/API integration
- not suitable for high concurrency or formal production deployment

Recommended source startup with Python 3.12 and `uv`:

```bash
cp .env.example .env
uv sync --python 3.12
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 22223 --reload
```

Minimal Docker startup:

```bash
cd docker
cp .env.example .env
docker compose --profile local up -d --build
docker compose --profile local exec api-local alembic upgrade head
```

Phase 4.7 canonical operator docs live in [docs/phase4_7/README.md](docs/phase4_7/README.md), with companion scripts under `scripts/phase47/` and the Phase 4.7 verification suite in `tests/phase4/test_phase47_api_verification.py`.

## Updating

### Updating Complete Component Mode

1. Pull new code or images.
2. Stop API and Worker.
3. Back up MySQL and object storage data.
4. Execute `alembic upgrade head`.
5. Start API.
6. Start Worker.
7. Check `/healthz`.
8. Validate KB, Skills, Chat, and Compliance pages.

### Updating Minimal Startup Mode

1. Stop API.
2. Back up the `data/` directory, including SQLite and local files.
3. Execute `alembic upgrade head`.
4. Restart API.
5. Validate `/healthz` and key pages.

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

- `DATABASE_MODE`
- `SQLITE_PATH`
- `DATABASE_URL` as an expert override
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_DATABASE`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `TASK_QUEUE_BACKEND`
- `REDIS_URL`
- `STORAGE_BACKEND`
- `QUEUE_NAME_PARSE`
- `QUEUE_NAME_CHAT`

Object storage:

- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`
- `MINIO_PREFIX_PATH`
- `MINIO_SECURE`

LLM/provider:

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `PROVIDER_URL_ALLOW_PRIVATE_NETS`

Chat runtime:

- `CHAT_RUN_POLL_INTERVAL_MS`
- `CHAT_RUN_REQUEST_TIMEOUT_SECONDS`
- `CHAT_RUN_LEASE_TIMEOUT_SECONDS`
- `CHAT_RUN_QUEUE_RETRY_DELAY_MS`

Browser/runtime:

- `CORS_ALLOW_ORIGINS`
- `CORS_ALLOW_ORIGIN_REGEX`
- `MAX_UPLOAD_BYTES`

## Frontend

Run the frontend separately:

```bash
cd frontend
npm install
VITE_API_BASE_URL=http://127.0.0.1:22223/api/v1 npm run dev
```

The frontend is expected to connect to the API at `http://127.0.0.1:22223` during local development.

## Open Source Note

- this repository is a Phase 3 baseline
- small fixes and packaging updates are expected to continue
- future roadmap work may add Kubernetes deployment guidance and equivalent replacements for Redis, MySQL, and MinIO
