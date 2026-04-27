# PageIndex Service

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-00a393.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED.svg)](https://www.docker.com/)

**PageIndex Service** is a production-ready microservice and console layer built on top of the open-source [PageIndex](https://github.com/VectifyAI/PageIndex) framework. It packages the core RAG (Retrieval-Augmented Generation) capabilities into a highly reliable, deployable baseline featuring robust memory governance, multi-manual parallel retrieval, cross-manual reranking, and a unified workspace console.

*Note: This repository is derived from PageIndex under the [MIT license](LICENSE). It serves as an implementation-oriented, deployable service surface around the upstream framework's capabilities.*

## Key Features

- **Document & Knowledge Base Management**: Full lifecycle management for document ingestion, parsing, and dynamic knowledge base mapping.
- **Skill Authoring & Chat**: Define custom AI skills with targeted knowledge bases, powered by multi-manual parallel retrieval and intelligent cross-manual global Rerank support.
- **Compliance Runs**: Execute bulk compliance checks and batch reviews against large document sets with strictly bounded memory usage.
- **Production-Grade Asynchronous Workers**: Queue-backed background execution (Redis) featuring Two-Tier Memory Governance (`MALLOC_ARENA_MAX` glibc tuning, RSS watchdogs, and child process recycling) to eliminate memory fragmentation and OOM crashes.
- **Real-time Observability**: Unified Server-Sent Events (SSE) stream providing real-time visibility into worker node stages, rerank metrics, and LLM I/O across all run types.
- **Workspace Isolation**: Multi-tenant and workspace-aware data modeling with strict access controls.

## Architecture

PageIndex Service is designed for horizontal scalability and high availability:

- **API Layer**: FastAPI application serving `/api/v1/*` endpoints and SSE observation streams.
- **Worker Layer**: Independent queue consumer processes with proactive self-healing and lazy-loading to enforce O(1) memory bounds regardless of document size.
- **Database**: SQLAlchemy + Alembic. MySQL is used for production state persistence.
- **Task Queue**: Redis-backed asynchronous job queues.
- **Storage**: MinIO (S3-compatible) or local filesystem for artifact and document storage.
- **Frontend Console**: A rich Vite + React workspace console for managing documents, KBs, skills, and viewing runtime timelines.

## Recent Engineering Highlights (Phase 4.9B)

The backend has recently been overhauled to introduce high-performance parallel retrieval and unified observability windows. The core architectural achievements include:

- **Multi-Manual Parallel Retrieval & Concurrency**: We migrated from single-document querying to fully parallelized multi-manual retrieval (`asyncio.gather`) across bounded concurrency semaphores. This dramatically speeds up queries across massive Knowledge Bases while enforcing strict memory limits.
- **Cross-Manual Global Rerank**: Inserted an intelligent reranking layer between candidate retrieval and context generation, automatically probing LLM providers for native rerank capabilities or gracefully falling back to a system-wide rerank model. (See `app/services/provider_service.py` and `app/core/config.py`).
- **Unified Worker Surface & Compliance Async**: Standardized `skills run`, `skills chat`, and `compliance` workloads onto a single unified worker execution plane, fully converting compliance tasks to asynchronous background operations.
- **Multi-Observation Windows**: Established a unified observability event stream and database persistence layer. Whether running a skill or a compliance check, the system now broadcasts granular stage transitions, Rerank hit-rates, and full LLM I/O payloads to the frontend's timeline and step-panel UI components. 

*Key components modified during this overhaul: `app/services/chat_service.py`, `app/services/compliance_service.py`, `app/services/pageindex_service.py`, `app/services/runtime_observation_service.py`, `app/services/task_queue_service.py`, `app/api/routers/runtime_observations.py`, `app/worker.py`, and migrations.*

## Deployment Modes

PageIndex Service strongly recommends the **Complete Component Mode (Docker)** for all use cases. **We do not recommend using the Standalone/Local mode (SQLite + Local Task Queue) unless absolutely necessary** (e.g., for quick syntax debugging). The standalone mode lacks the queue reliability, multi-manual parallel concurrency, and strict memory governance of the full deployment.

Detailed container instructions live in [docker/README.md](docker/README.md).

### Minimal Initialization Process

Follow these steps to minimally configure and run the backend using Docker, and manually start the frontend.

#### 1. Configure `.env`
Change into the `docker` directory and copy the example environment file:
```bash
cd docker
cp .env.example .env
```
Open `.env` and configure the minimal required variables. **A Rerank model is highly recommended/mandatory** for production-quality retrieval capabilities.

```env
APP_ENV=prod
API_HOST=0.0.0.0
API_PORT=22223

# Required credentials (change these for production)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=strong-admin-password
SECRET_KEY=long-random-secret-key

# LLM Configuration
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key

# Rerank Configuration (Required for best results)
SYSTEM_RERANK_ENABLED=true
SYSTEM_RERANK_PROVIDER_TYPE=openai_compatible
SYSTEM_RERANK_BASE_URL=https://api.your-rerank-provider.com/v1
SYSTEM_RERANK_API_KEY=sk-your-rerank-key
SYSTEM_RERANK_MODEL=bge-reranker-v2-m3

# Embedding Configuration (deferred, disabled by default)
SYSTEM_EMBEDDING_ENABLED=false
SYSTEM_EMBEDDING_PROVIDER_TYPE=openai_compatible
SYSTEM_EMBEDDING_BASE_URL=https://api.your-embedding-provider.com/v1
SYSTEM_EMBEDDING_API_KEY=sk-your-embedding-key
SYSTEM_EMBEDDING_MODEL=text-embedding-3-large

# Routing asset build hooks (deferred, disabled by default)
# Canonical values: disabled, dry_run, enabled
ROUTING_ROUTE_DOCS_BUILD_MODE=disabled
ROUTING_SYNTHETIC_QUERIES_BUILD_MODE=disabled
ROUTING_EMBEDDINGS_BUILD_MODE=disabled
```

#### 2. Install Host Dependencies (uv)
If you intend to run DB migrations or background scripts directly from your host machine, we recommend using `uv`:
```bash
cd ..
uv sync --python 3.12
```

#### 3. Start Backend via Docker Script
We provide a unified startup script `docker/start.sh` that securely boots the environment and ensures the API container launches the worker under strict memory governance (`MALLOC_ARENA_MAX=2` and RSS watchdogs).

```bash
cd docker
# Start MySQL, Redis, MinIO, API, and the embedded worker
./start.sh
```

The API container runs migrations on startup. To rerun them manually:
```bash
docker compose --env-file .env -f docker-compose.yml --profile full exec api alembic upgrade head
```

#### 4. Manually Start the Frontend
With the backend running at `http://127.0.0.1:22223`, start the React workspace console:

```bash
cd ../frontend
npm install
VITE_API_BASE_URL=http://127.0.0.1:22223/api/v1 npm run dev
```
You can now access the frontend at `http://localhost:5173`.

---

### Database Runtime Selection

Database env parsing follows this priority order:
1. `DATABASE_URL` (expert override)
2. `DATABASE_MODE` (mysql or sqlite)

Recommended usage:
- **Production/Docker**: set `DATABASE_MODE=mysql` and fill `MYSQL_*`
- **Fallback**: `DATABASE_MODE=sqlite` (Not Recommended)

### Updating the Service

1. Pull new code.
2. `cd docker && docker compose --profile full stop api`
3. Back up MySQL and object storage data.
4. Start the database containers and run migrations: `docker compose --profile full exec api alembic upgrade head`
5. Run `./start.sh` to rebuild and restart the stack.
6. Validate `/healthz` and key pages.

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
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` / `REDIS_DB` (推荐拆分写法；`REDIS_URL` 保留作为 legacy 覆盖)
- `STORAGE_BACKEND`
- `QUEUE_NAME_PARSE`
- `QUEUE_NAME_CHAT`
- `QUEUE_NAME_COMPLIANCE`

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
- `SYSTEM_RERANK_ENABLED`
- `SYSTEM_RERANK_BASE_URL`
- `SYSTEM_RERANK_API_KEY`
- `SYSTEM_RERANK_MODEL`
- `SYSTEM_RERANK_PROVIDER_TYPE`
- `SYSTEM_EMBEDDING_ENABLED`
- `SYSTEM_EMBEDDING_BASE_URL`
- `SYSTEM_EMBEDDING_API_KEY`
- `SYSTEM_EMBEDDING_MODEL`
- `SYSTEM_EMBEDDING_PROVIDER_TYPE`
- `ROUTING_ROUTE_DOCS_BUILD_MODE` (canonical: `disabled` / `dry_run` / `enabled`)
- `ROUTING_SYNTHETIC_QUERIES_BUILD_MODE` (canonical: `disabled` / `dry_run` / `enabled`)
- `ROUTING_EMBEDDINGS_BUILD_MODE` (canonical: `disabled` / `dry_run` / `enabled`)

Node embedding ES shadow backend:

- `ROUTING_NODE_ES_ENABLED`
- `ROUTING_NODE_ES_HOST` / `ROUTING_NODE_ES_PORT` / `ROUTING_NODE_ES_USER` / `ROUTING_NODE_ES_PASSWORD` / `ROUTING_NODE_ES_USE_SSL` (推荐拆分写法；`ROUTING_NODE_ES_URL` 保留作为 legacy 覆盖)
- `ROUTING_NODE_ES_INDEX_PREFIX`

Chat runtime:

- `CHAT_RUN_POLL_INTERVAL_MS`
- `CHAT_RUN_REQUEST_TIMEOUT_SECONDS`
- `CHAT_RUN_LEASE_TIMEOUT_SECONDS`
- `CHAT_RUN_QUEUE_RETRY_DELAY_MS`

Compliance runtime:

- `COMPLIANCE_RUN_POLL_INTERVAL_MS`
- `COMPLIANCE_RUN_REQUEST_TIMEOUT_SECONDS`
- `COMPLIANCE_RUN_LEASE_TIMEOUT_SECONDS`
- `COMPLIANCE_RUN_QUEUE_RETRY_DELAY_MS`

Retrieval/manual gate:

- `RETRIEVAL_MAX_CONCURRENCY`
- `RETRIEVAL_MANUAL_GATE_MODE`
- `RETRIEVAL_MANUAL_GATE_CHAT_LIVE_ENABLED`
- `RUN_MAX_MANUALS`
- `RUN_STEP_MAX_RETRIES`
- `RUN_STEP_RETRY_BASE_MS`

Worker:

- `WORKER_PROCESS_COUNT`
- `WORKER_MAX_TASKS_PER_CHILD`
- `WORKER_MAX_RSS_MB`
- `WORKER_HEARTBEAT_INTERVAL_SECONDS`
- `WORKER_HEARTBEAT_TTL_SECONDS`
- `WORKER_RECONNECT_DELAY_MS`
- `WORKER_REGISTRY_PREFIX`
- `REDIS_SOCKET_TIMEOUT_SECONDS`
- `REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS`
- `REDIS_HEALTH_CHECK_INTERVAL_SECONDS`

Observability:

- `OBSERVATION_TEXT_MAX_CHARS`

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
