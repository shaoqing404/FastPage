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

