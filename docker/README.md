# Docker Runtime

This Docker stack defaults to **full mode**: MySQL + Redis + MinIO + Elasticsearch + API + Frontend.

`local` mode means SQLite + local filesystem + local queue. It is **deprecated**, kept only for short-lived diagnostics, and may be removed in a future release.

## Quick Start

```bash
cd docker
cp .env.example .env
# Edit .env: set real passwords, SECRET_KEY, provider keys, and any external endpoints.
bash start.sh
```

Defaults:

- Frontend: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:22223`
- Health: `http://127.0.0.1:22223/healthz`
- Compose profile: `full`
- Final-answer runtime: `ENABLE_LITELLM=false`

Set `ENABLE_LITELLM=true` only to roll back final-answer chat to the legacy LiteLLM path. With the default direct OpenAI-compatible runtime, model names are sent without historical `openai/` or `litellm/` routing hints at the final HTTP boundary.

## Provider Center

After startup, configure user-facing model capabilities in Provider Center:

- `/providers`: capability center entry page.
- `/providers/api-keys`: workspace API keys.
- `/providers/llm`: LLM provider templates.
- `/providers/embedding`: embedding provider templates and Embedding Profile metadata.
- `/providers/rerank`: rerank provider templates.

Provider templates expose only `API key` and `No auth` as product auth modes.
`No auth` allows empty API keys and probe/runtime requests do not send an
`Authorization` header. Custom header auth is intentionally not exposed in this
phase.

Embedding Profile fields are stored in `model_provider_endpoints.config_json`.
This does not change Elasticsearch index rebuild behavior by itself.

## Runtime Modes

| Mode | Use | Status |
| --- | --- | --- |
| `full` | Local or server deployment with bundled MySQL/Redis/MinIO/Elasticsearch | Default and recommended |
| `standalone` | API + Frontend connected to external MySQL/Redis/MinIO or S3/Elasticsearch | Supported |
| `local` | SQLite/local storage/local queue | Deprecated |

Run an explicit profile when needed:

```bash
PAGEINDEX_COMPOSE_PROFILE=full bash start.sh
PAGEINDEX_COMPOSE_PROFILE=standalone bash start.sh
```

Avoid `PAGEINDEX_COMPOSE_PROFILE=local` unless you are specifically debugging deprecated SQLite behavior.

## Build

The default API Dockerfile is multi-arch and should be used for both x86_64 and ARM64:

```env
API_DOCKERFILE=docker/Dockerfile
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
NPM_CONFIG_REGISTRY=https://registry.npmmirror.com/
TIKTOKEN_PREWARM=true
```

Build API and frontend:

```bash
cd docker
docker compose --env-file .env --profile full build api frontend
```

Use the ARM64-specific API Dockerfile only when explicitly needed:

```env
API_DOCKERFILE=docker/Dockerfile.arm64
```

Python dependencies are installed with `uv sync --frozen --no-install-project` into `/app/.venv`; containers start with `uv run --no-sync`.

Domestic-network notes:

- `UV_DEFAULT_INDEX` controls the Python package index.
- `NPM_CONFIG_REGISTRY` controls npm registry.
- Set `TIKTOKEN_PREWARM=false` if the build network cannot reach tiktoken encoding blobs.
- Cold builds still need base images, Debian apt repositories, and the `uv` installer. For restricted servers, build in a connected environment and transfer image tarballs.

## Build Image Tarballs

From the repository root:

```bash
bash /Users/mac/.codex/skills/pageindex-docker-build/scripts/build_pageindex_images.sh \
  /path/to/PageIndex-Service \
  /path/to/output
```

Or manually:

```bash
docker buildx build --platform linux/amd64 -f docker/Dockerfile -t pageindex-service-api:amd64 --load .
docker buildx build --platform linux/arm64 -f docker/Dockerfile.arm64 -t pageindex-service-api:arm64 --load .
docker buildx build --platform linux/amd64 -f docker/Dockerfile.frontend -t pageindex-service-frontend:amd64 --load .
docker buildx build --platform linux/arm64 -f docker/Dockerfile.frontend -t pageindex-service-frontend:arm64 --load .
docker save -o pageindex-images-amd64.tar pageindex-service-api:amd64 pageindex-service-frontend:amd64 mysql:8.4 redis:7-alpine minio/minio:RELEASE.2025-02-28T09-55-16Z elasticsearch:8.19.15
docker save -o pageindex-images-arm64.tar pageindex-service-api:arm64 pageindex-service-frontend:arm64 mysql:8.4 redis:7-alpine minio/minio:RELEASE.2025-02-28T09-55-16Z elasticsearch:8.19.15
```

## Export And Restore

Create a migration bundle:

```bash
bash scripts/pageindex_export.sh /Users/mac/Desktop/pageindex-export
```

The export includes code, Docker images, MySQL dump, MinIO data, Elasticsearch snapshots, docs, and an import helper. It excludes private env files, `.git`, virtualenvs, `node_modules`, and `specs/`.

Restore after configuring the target `docker/.env`:

```bash
bash scripts/pageindex_import.sh /path/to/pageindex-export /path/to/pageindex-export/code/PageIndex-Service
```

Elasticsearch restore is not replayed automatically; prefer the application rebuild flow for ES-backed indexes.

## Standalone Mode

Use standalone mode when connecting to external infrastructure. Configure these values in `docker/.env`:

```env
DATABASE_MODE=mysql
MYSQL_HOST=your-mysql-host
TASK_QUEUE_BACKEND=redis
REDIS_HOST=your-redis-host
STORAGE_BACKEND=minio
MINIO_ENDPOINT=your-minio-host:9000
ROUTING_NODE_ES_ENABLED=true
ROUTING_NODE_ES_HOST=your-es-host
```

Then run:

```bash
PAGEINDEX_COMPOSE_PROFILE=standalone bash start.sh
```

## Maintenance

Useful commands:

```bash
docker compose --env-file .env --profile full ps
docker compose --env-file .env --profile full logs -f api
docker compose --env-file .env --profile full up -d --build api frontend
docker compose --env-file .env --profile full down
```

Before upgrading production-like data, back up MySQL and object storage.

Never write real API keys into Dockerfiles, compose files, docs, or commits. Keep secrets in `docker/.env` or the deployment secret manager.
