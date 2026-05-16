#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
PROFILE="${PAGEINDEX_COMPOSE_PROFILE:-full}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${SCRIPT_DIR}/.env.example" "${ENV_FILE}"
  echo "docker/.env was missing and has been created from docker/.env.example"
fi

set -a
source "${ENV_FILE}"
set +a

case "${PROFILE}" in
  full)
    echo "==> PAGEINDEX_COMPOSE_PROFILE=${PROFILE} (default, recommended): MySQL + Redis + MinIO + Elasticsearch + API + Frontend"
    echo "==> Starting Infrastructure (MySQL, Redis, MinIO, Elasticsearch)..."
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full up -d --build mysql redis minio elasticsearch

    echo "==> Starting API Service and Frontend (worker starts inside the API container, including database migrations)..."
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full up -d --build api frontend
    ;;
  standalone)
    echo "==> Starting API Service in Standalone Mode (Connecting to external services)..."
    docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/docker-compose.standalone.yml" up -d --build
    ;;
  local)
    cat >&2 <<'EOF'
WARNING: PAGEINDEX_COMPOSE_PROFILE=local is the deprecated SQLite/local queue/local storage mode.
It is retained only for short-lived development diagnostics and may be removed in a future release.
Use the default PAGEINDEX_COMPOSE_PROFILE=full for local deployments unless you are explicitly debugging SQLite mode.
EOF
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile local up -d --build api-local frontend-local
    ;;
  *)
    echo "Unsupported PAGEINDEX_COMPOSE_PROFILE=${PROFILE}. Use full, standalone, or local." >&2
    exit 1
    ;;
esac

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps
