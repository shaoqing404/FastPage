# Docker Runtime

This directory defaults to the complete `full` runtime mode for PageIndex Service.

1. `full`: default and recommended deployment mode with MySQL + Redis + MinIO + Elasticsearch + API + Frontend, with worker processes launched inside the API container
2. `standalone`: API + Frontend connected to external MySQL / Redis / MinIO or S3 / Elasticsearch
3. `local`: deprecated SQLite + local storage + local task queue mode, retained only for short-lived development diagnostics and subject to removal

Source startup with Python 3.12 and `uv` remains the recommended development path outside containers.

> **Deprecated:** `PAGEINDEX_COMPOSE_PROFILE=local` is SQLite mode. It is not a supported deployment target for the current mainline runtime and may be removed in a future release. Do not use it for local deployment smoke unless you are explicitly debugging SQLite/local queue behavior.

## Files

- `docker/docker-compose.yml`
- `docker/.env.example`
- `docker/Dockerfile`
- `docker/start.sh`
- `docker/stop.sh`

## Mode 1: Complete Component Mode (`full`, Default)

Default and recommended deployment mode:

- `mysql`
- `redis`
- `minio`
- `elasticsearch`
- `api`

This is the recommended production-style deployment shape. The API container launches the worker process internally.

Required runtime settings:

- `APP_ENV=prod` or `APP_ENV=dev`
- `LLM_API_KEY` (must be set in .env)
- `DATABASE_MODE=mysql`
- `TASK_QUEUE_BACKEND=redis`
- `STORAGE_BACKEND=minio`
- `ROUTING_NODE_ES_ENABLED=true`
- `DATA_DIR=/var/lib/pageindex/data`
- `ENABLE_LITELLM=false` by default. Set `ENABLE_LITELLM=true` only to roll back final-answer chat to the legacy LiteLLM path.

### Complete Mode Startup Order

1. Configure `docker/.env` (start by copying from `.env.example`).
2. Start infrastructure and API using the helper script.
3. The API container automatically executes `alembic upgrade head` on startup.
4. Access the frontend or API once the healthchecks pass.

Helper script:

```bash
cd docker
cp .env.example .env
# Edit .env to set your LLM_API_KEY and other settings
bash start.sh
```

`PAGEINDEX_COMPOSE_PROFILE` defaults to `full`; setting it explicitly is optional:

```bash
PAGEINDEX_COMPOSE_PROFILE=full bash start.sh
```

### Build Architecture And Mirrors

The default `API_DOCKERFILE=docker/Dockerfile` is multi-arch and is the recommended path for both x86_64 (`linux/amd64`) servers and ARM64 (`linux/arm64`) machines:

```bash
cd docker
cp .env.example .env
# Optional for explicit x86 server builds:
API_DOCKERFILE=docker/Dockerfile docker compose --env-file .env --profile full build api frontend
```

For ARM64-specific local builds, set:

```env
API_DOCKERFILE=docker/Dockerfile.arm64
```

Python dependencies are installed with `uv sync --frozen --no-install-project` into `/app/.venv`; container startup uses `uv run --no-sync ...` so runtime and build use the same project virtual environment. The build defaults to a domestic PyPI mirror and npm mirror:

```env
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
NPM_CONFIG_REGISTRY=https://registry.npmmirror.com/
TIKTOKEN_PREWARM=true
```

Override these values in `docker/.env` or in the shell when a target network requires a different mirror. Set `TIKTOKEN_PREWARM=false` only when the build network cannot reach tiktoken's upstream encoding blobs; keep it enabled for runtime images that must work without network fetches. No real API keys should be written into Dockerfiles or compose files.

The mirror settings cover Python and npm packages. A cold build still needs access to the base images, Debian apt repositories, and the `uv` installer; for restricted server networks, build in a connected environment first and transfer the saved image tarballs.

To build image tarballs for distribution from a Linux host with BuildKit/buildx:

```bash
docker buildx build --platform linux/amd64 -f docker/Dockerfile -t pageindex-service-api:amd64 --load ..
docker buildx build --platform linux/arm64 -f docker/Dockerfile.arm64 -t pageindex-service-api:arm64 --load ..
docker buildx build --platform linux/amd64 -f docker/Dockerfile.frontend -t pageindex-service-frontend:amd64 --load ..
docker buildx build --platform linux/arm64 -f docker/Dockerfile.frontend -t pageindex-service-frontend:arm64 --load ..
docker save -o pageindex-images-amd64.tar pageindex-service-api:amd64 pageindex-service-frontend:amd64 mysql:8.4 redis:7-alpine minio/minio:RELEASE.2025-02-28T09-55-16Z elasticsearch:8.19.15
docker save -o pageindex-images-arm64.tar pageindex-service-api:arm64 pageindex-service-frontend:arm64 mysql:8.4 redis:7-alpine minio/minio:RELEASE.2025-02-28T09-55-16Z elasticsearch:8.19.15
```

## Mode 2: Standalone Mode (Connecting to External Infrastructure)

This mode is used when you want to run only the PageIndex-Service (API + Frontend) and connect it to your existing MySQL, Redis, Elasticsearch, and MinIO instances.

### 1. Configuration

Edit `docker/.env` and update the following connection details to point to your external services:

```env
# Database (MySQL)
DATABASE_MODE=mysql
MYSQL_HOST=your-mysql-host
MYSQL_PORT=3306
MYSQL_DATABASE=pageindex
MYSQL_USER=pageindex
MYSQL_PASSWORD=your-password

# Task Queue (Redis)
TASK_QUEUE_BACKEND=redis
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_PASSWORD=your-password

# Search (Elasticsearch)
ROUTING_NODE_ES_ENABLED=true
ROUTING_NODE_ES_HOST=your-es-host
ROUTING_NODE_ES_PORT=9200

# Object Storage (MinIO/S3)
STORAGE_BACKEND=minio
MINIO_ENDPOINT=your-minio-host:9000
MINIO_ACCESS_KEY=your-access-key
MINIO_SECRET_KEY=your-secret-key
```

### 2. Startup

Run the service using the standalone compose file:

```bash
cd docker
# This starts ONLY the api and frontend containers
PAGEINDEX_COMPOSE_PROFILE=standalone bash start.sh
```

### 3. Architecture Note

In this mode, the `api` container still runs the internal background worker processes. The `frontend` container (Nginx) provides the UI and proxies `/api` requests to the `api` container internally.

## Mode 3: Deprecated Minimal Startup Mode (SQLite)

> **Deprecated:** this is `PAGEINDEX_COMPOSE_PROFILE=local`. It uses SQLite, local filesystem storage, and local in-process queues. It is retained only for short-lived development diagnostics and may be removed in a future release. The default for local Docker deployment is `full`, not `local`.


Goal:

- run the service locally even when MySQL, Redis, and MinIO are unavailable

Minimal configuration:

- `APP_ENV=dev`
- `API_HOST=127.0.0.1`
- `API_PORT=22223`
- `ADMIN_USERNAME=admin`
- `ADMIN_PASSWORD=pageindex_service123`
- `SECRET_KEY=pageindex_service123_local_dev_only_change_me`
- `DATABASE_URL=sqlite:///./data/app.db`
  Or inside a container:
  `DATABASE_URL=sqlite:////var/lib/pageindex/data/app.db`
- `STORAGE_BACKEND=local`
- `TASK_QUEUE_BACKEND=local`
- `MINIO_*=` empty
- Redis / ES fields are unused when backend is `local`
- `LLM_BASE_URL`
- `LLM_API_KEY`

Behavior in minimal mode:

- uses SQLite
- writes files under `DATA_DIR`
- uses local filesystem storage via `app/services/storage_service.py`
- parse/chat execution does not require Redis worker mode
- no standalone worker process is needed
- only for development diagnostics of SQLite/local queue behavior
- not suitable for high concurrency or formal production deployment
- not suitable for current mainline deployment smoke

Source startup example:

```bash
cp .env.example .env
uv sync --python 3.12
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 22223
```

Dockerized minimal mode:

```bash
cd docker
cp .env.example .env
docker compose --profile local up -d --build
docker compose --profile local exec api-local alembic upgrade head
```

Helper script:

```bash
cd docker
cp .env.example .env
PAGEINDEX_COMPOSE_PROFILE=local bash start.sh
docker compose --profile local exec api-local alembic upgrade head
```

If you run `docker/docker-entrypoint.sh` directly, pass `local` explicitly to start API-only mode:

```bash
./docker-entrypoint.sh local
```

## Updating

### Updating Complete Component Mode

1. Pull new code or images.
2. Stop the API container.
3. Back up MySQL and object storage data.
4. Execute `alembic upgrade head`.
5. Start API.
6. Check `/healthz`.
7. Validate critical pages: KB, Skills, Chat, Compliance.

### Updating Minimal Startup Mode

1. Stop API.
2. Back up the `data/` directory, including SQLite and local files.
3. Execute `alembic upgrade head`.
4. Restart API.
5. Validate `/healthz` and critical pages.

## Frontend

The frontend is now fully integrated into the Docker stack via a dedicated Nginx container (`pageindex-service-frontend`).

- **Multi-stage build:** The frontend is compiled (`npm run build`) in a Node.js stage, and the static assets are then copied to a lightweight Nginx Alpine image.
- **Reverse Proxy:** Nginx serves the static SPA files and transparently proxies all requests starting with `/api/` to the backend `api` container on port `22223`.
- **Configuration:** You do not need to configure complex CORS or absolute backend URLs. Ensure `VITE_API_BASE_URL=/api/v1` in `frontend/.env` (or let it inherit the default), and access the web UI via the port defined by `FRONTEND_PORT` (default `5173`) in `docker/.env`.

If you prefer to run the frontend independently for development, you can still do so:

```bash
cd frontend
npm install
VITE_API_BASE_URL=http://127.0.0.1:22223/api/v1 npm run dev
```

## Security Notes

- `APP_ENV=prod` rejects weak default `SECRET_KEY` and `ADMIN_PASSWORD`
- do not expose raw uvicorn directly to the public internet
- use a reverse proxy for TLS and request-size enforcement
- align reverse-proxy body-size limits with `MAX_UPLOAD_BYTES`

## ARM64 Dedicated Build & External Connections

If you are running on an ARM64 architecture (like Mac M-series chips or AWS Graviton) and wish to build the image locally, you may use the dedicated `Dockerfile.arm64`. The default `docker/Dockerfile` is still valid for both x86_64 and ARM64.

### 1. Building the ARM64 Image locally

Run the following command from the project root:

```bash
cd docker
docker build -t pageindex-service-api:arm64 -f Dockerfile.arm64 ..
```

*(Note: The frontend does not need a special Dockerfile; `Dockerfile.frontend` uses the official Node image which natively supports ARM64).*

### 2. Connect to Existing Components using Local Docker

If you want to start *only* the `pageindex-service` using your local Docker and connect it to your external/existing infrastructure (MySQL, Redis, MinIO, ES), you should use **Mode 2 (Standalone Mode)**.

**Step 1:** Configure the connection details in `docker/.env`:
```env
DATABASE_MODE=mysql
MYSQL_HOST=192.168.1.100  # Replace with your actual MySQL IP
REDIS_HOST=192.168.1.101  # Replace with your actual Redis IP
# ... configure MinIO and Elasticsearch similarly
```

**Step 2:** Start the API and Frontend pointing to your existing components. If you built the custom `arm64` image above, you can run it directly:

```bash
# Using raw Docker Run (Connecting to external databases):
docker run -d --name pageindex-api \
  --env-file docker/.env \
  -p 22223:22223 \
  -v $(pwd)/data:/var/lib/pageindex \
  pageindex-service-api:arm64 \
  /app/docker/docker-entrypoint.sh

# Or simply use the Compose Standalone file:
PAGEINDEX_COMPOSE_PROFILE=standalone bash docker/start.sh
```
