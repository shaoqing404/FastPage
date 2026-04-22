# Docker Runtime

This directory supports two clearly separated runtime modes for PageIndex Service:

1. `full`: recommended deployment mode with MySQL + Redis + MinIO + API, with the worker launched inside the API container
2. `local`: minimal startup mode with SQLite + local storage + local task queue + API only

Source startup with Python 3.12 and `uv` remains the recommended development path outside containers.

## Files

- `docker/docker-compose.yml`
- `docker/.env.example`
- `docker/Dockerfile`
- `docker/start.sh`
- `docker/stop.sh`

## Mode 1: Complete Component Mode

Recommended deployment mode:

- `mysql`
- `redis`
- `minio`
- `api`

This is the recommended production-style deployment shape. The API container launches the worker process internally.

Required runtime settings:

- `APP_ENV=prod` or `APP_ENV=dev`
- `API_HOST`
- `API_PORT`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `SECRET_KEY`
- `DATABASE_URL=mysql+pymysql://<user>:<pass>@<mysql-host>:3306/pageindex`
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

Demo defaults in `docker/.env.example` intentionally use:

- `pageindex_service123` for MySQL passwords
- `pageindex_service123` for Redis password
- `pageindex_service123` for MinIO access key and secret key
- `pageindex_service123` for `ADMIN_PASSWORD`

These values are only for:

- local demo
- test compose
- documentation examples

Production requirements:

- replace every demo password with a strong random value
- generate a dedicated long random `SECRET_KEY`
- do not use `pageindex_service123` as a production `SECRET_KEY`

### Complete Mode Startup Order

1. Start MySQL, Redis, and MinIO.
2. Configure `docker/.env`.
3. Execute `alembic upgrade head`.
4. Start the API container.
5. The API container starts the worker process internally.
6. Then access the frontend or API.

Compose entrypoint:

```bash
cd docker
cp .env.example .env
docker compose --profile full up -d --build
docker compose --profile full exec api alembic upgrade head
```

The API container runs migrations on startup. The `alembic upgrade head` line is only needed if you want to rerun them manually.

Helper script:

```bash
cd docker
cp .env.example .env
PAGEINDEX_COMPOSE_PROFILE=full bash start.sh
docker compose --profile full exec api alembic upgrade head
```

Important notes:

- the worker process is only started when `TASK_QUEUE_BACKEND=redis`
- if the API is exposed beyond localhost, `API_HOST=0.0.0.0` must be paired with a reverse proxy and TLS
- reverse-proxy upload size must be aligned with `MAX_UPLOAD_BYTES`
- `STORAGE_BACKEND=minio` stores artifacts in MinIO keys such as `tenants/<tenant_id>/...`

## Mode 2: Minimal Startup Mode

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
  `DATABASE_URL=sqlite:////app/data/app.db`
- `STORAGE_BACKEND=local`
- `TASK_QUEUE_BACKEND=local`
- `REDIS_URL=`
- `MINIO_*=` empty
- `LLM_BASE_URL`
- `LLM_API_KEY`

Behavior in minimal mode:

- uses SQLite
- writes files under `DATA_DIR`
- uses local filesystem storage via `app/services/storage_service.py`
- parse/chat execution does not require Redis worker mode
- no standalone worker process is needed
- best for development, self-test, and frontend/API integration
- not suitable for high concurrency or formal production deployment

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

The frontend is not bundled into the Docker stack. Run it separately from `frontend/`:

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
