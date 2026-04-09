# Docker Runtime

## Goal

Provide a one-command runtime for the current API + worker architecture.

## Runtime Shape

- `api`: FastAPI HTTP service
- `worker`: Redis-backed background parser worker

## Files

- `docker/.env`: runtime configuration used by startup scripts
- `docker/.env.example`: template for `docker/.env`
- `docker/Dockerfile`: shared image for api and worker
- `docker/docker-compose.yml`: compose definition
- `docker/start.sh`: one-click startup
- `docker/stop.sh`: one-click shutdown

## Prerequisites

### Database Migration

Before starting the API for the first time — or after any upgrade that includes
new migration files — run Alembic migrations:

```bash
# From the project root (not docker/):
alembic upgrade head
```

The API will NOT apply schema changes at startup in production. You must run
migrations explicitly.

### Environment File

Copy `.env.example` to `.env` and fill in **all** placeholder values
(`<CHANGE_ME>`, `<DB_HOST>`, etc.):

```bash
cp .env.example .env
# edit .env with your values
```

> **Never commit `.env` to version control.**

## Startup Order

1. `docker/start.sh`
2. script reads `docker/.env`
3. `docker compose` builds image and starts `api`
4. `docker compose` starts `worker` replicas according to `WORKER_REPLICAS`

## Usage

```bash
cd docker
bash start.sh
```

Stop:

```bash
cd docker
bash stop.sh
```

## Worker Node Code

Each worker container derives a node code from:

- `WORKER_NODE_CODE`, if explicitly passed
- otherwise `WORKER_NODE_CODE_PREFIX` + container hostname

That code is printed in worker logs to identify which node consumed a job.

## Production Deployment Notes

### APP_ENV

Set `APP_ENV=prod` for any internet-exposed deployment. In prod mode:

- Startup will **fail** if `SECRET_KEY` or `ADMIN_PASSWORD` are left at their
  insecure default values.
- CORS origin regex defaults to empty (disabled) — you must explicitly set
  `CORS_ALLOW_ORIGINS` to your frontend's origin.
- Provider `base_url` validation rejects private/reserved IP ranges unless
  `PROVIDER_URL_ALLOW_PRIVATE_NETS=true` is explicitly set.

### Reverse Proxy / TLS

**Do not expose uvicorn directly to the internet.** Place a reverse proxy
(nginx, Caddy, Traefik, etc.) in front of the API service:

- Terminate TLS at the proxy.
- Set `API_HOST=0.0.0.0` in `.env` so the container listens on all interfaces
  within the Docker network.
- The proxy should forward `X-Request-ID` headers if you want end-to-end
  request tracing.

### Upload Body-Size Alignment

The API enforces `MAX_UPLOAD_BYTES` (default 2 GB). Your reverse proxy must
allow at least the same body size:

- **nginx**: `client_max_body_size 2048m;`
- **Caddy**: `request_body { max_size 2GB }`

If the proxy rejects the request before it reaches the API, the client will
receive the proxy's error page instead of the API's structured error envelope.

### Persistent Volumes

Ensure the following paths are backed by persistent storage:

- `DATA_DIR` (`/app/data` by default) — local file storage when
  `STORAGE_BACKEND=local`
- Database and Redis should be externalized (not ephemeral containers)

### MinIO / Object Storage

When using `STORAGE_BACKEND=minio`, the API connects to MinIO at startup.
Ensure the endpoint, credentials, and bucket are configured correctly in `.env`.
