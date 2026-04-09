# Docker Runtime

This directory contains the containerized runtime for PageIndex Service Phase 3.

Source startup with Python 3.12 and `uv` is the recommended development path. Docker remains the secondary packaging and single-host evaluation path.

## Stack Shape

- `api`: FastAPI service
- `worker`: Redis-backed chat/parse worker
- `mysql`: primary relational database
- `redis`: queue backend
- `minio`: object storage for document and trace artifacts

The compose file is for local OSS evaluation and single-host development. It is not a recommendation to expose raw uvicorn directly to the public internet.

## Files

- [docker/docker-compose.yml](/Users/shaoqing/workspace/PageIndex-main-integration/docker/docker-compose.yml)
- [docker/.env.example](/Users/shaoqing/workspace/PageIndex-main-integration/docker/.env.example)
- [docker/start.sh](/Users/shaoqing/workspace/PageIndex-main-integration/docker/start.sh)
- [docker/stop.sh](/Users/shaoqing/workspace/PageIndex-main-integration/docker/stop.sh)
- [Dockerfile](/Users/shaoqing/workspace/PageIndex-main-integration/Dockerfile)
- [Dockerfile.worker](/Users/shaoqing/workspace/PageIndex-main-integration/Dockerfile.worker)

## First Run

```bash
cd docker
cp .env.example .env
bash start.sh
```

The startup script builds the API and worker images and brings up the dependency services.

## Default Published Ports

- API: `127.0.0.1:22223`
- MySQL: `127.0.0.1:3306`
- Redis: `127.0.0.1:6379`
- MinIO API: `127.0.0.1:9000`
- MinIO Console: `127.0.0.1:9001`

## Env Matching

The compose file and [docker/.env.example](/Users/shaoqing/workspace/PageIndex-main-integration/docker/.env.example) are aligned around the same runtime names:

- `MYSQL_DATABASE`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_ROOT_PASSWORD`
- `DATABASE_URL`
- `REDIS_URL`
- `MINIO_*`
- `QUEUE_NAME_PARSE`
- `QUEUE_NAME_CHAT`

## Migrations

Run migrations after the stack is up:

```bash
docker compose --env-file .env -f docker-compose.yml exec api alembic upgrade head
```

The API bootstrap calls the migration path on startup, but explicit migration execution is still the safer operational pattern when upgrading a long-lived deployment.

## Frontend

The frontend is not bundled into this compose stack. Run it separately from [frontend/](/Users/shaoqing/workspace/PageIndex-main-integration/frontend):

```bash
cd ../frontend
npm install
VITE_API_BASE_URL=http://127.0.0.1:22223/api/v1 npm run dev
```

## Recommended Source Runtime

For normal development outside containers:

```bash
cp ../.env.example ../.env
cd ..
uv sync --python 3.12
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 22223 --reload
```

Start the worker in a second shell when using Redis-backed jobs:

```bash
cd ..
uv run python -m app.worker
```

## Deployment Notes

- For a reverse-proxy deployment, keep the container listening on `0.0.0.0` internally and publish through nginx, Caddy, Traefik, or equivalent.
- Set explicit `CORS_ALLOW_ORIGINS` for any browser-facing non-local deployment.
- In `APP_ENV=prod`, weak defaults for `SECRET_KEY` and `ADMIN_PASSWORD` will fail startup.
- Align reverse-proxy body-size limits with `MAX_UPLOAD_BYTES`.
