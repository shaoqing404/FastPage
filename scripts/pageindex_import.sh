#!/usr/bin/env bash
set -euo pipefail

EXPORT_DIR="${1:?Usage: pageindex_import.sh /path/to/pageindex-export /path/to/PageIndex-Service}"
TARGET_DIR="${2:?Usage: pageindex_import.sh /path/to/pageindex-export /path/to/PageIndex-Service}"
COMPOSE_FILE="${TARGET_DIR}/docker/docker-compose.yml"
ENV_FILE="${TARGET_DIR}/docker/.env"
PROJECT_NAME="${PAGEINDEX_COMPOSE_PROJECT_NAME:-docker}"

if [ ! -f "${COMPOSE_FILE}" ]; then
  echo "Missing compose file at ${COMPOSE_FILE}" >&2
  exit 1
fi

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing ${ENV_FILE}. Copy docker/.env.example to docker/.env and configure it first." >&2
  exit 1
fi

if [ -f "${EXPORT_DIR}/images/pageindex-images.tar" ]; then
  echo "Loading Docker images"
  docker load -i "${EXPORT_DIR}/images/pageindex-images.tar"
fi

echo "Starting infrastructure"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full up -d mysql redis minio elasticsearch

echo "Waiting for infrastructure health"
for _ in $(seq 1 60); do
  unhealthy="$(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full ps --format json \
    | grep -E '"(mysql|redis|minio|elasticsearch)"' \
    | grep -vc '"Health":"healthy"' || true)"
  if [ "${unhealthy}" = "0" ]; then
    break
  fi
  sleep 3
done

if [ -s "${EXPORT_DIR}/data/mysql/pageindex_dump.sql" ]; then
  echo "Importing MySQL dump"
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full exec -T mysql \
    sh -lc 'MYSQL_PWD="${MYSQL_PASSWORD}" mysql -u"${MYSQL_USER}" "${MYSQL_DATABASE}"' \
    < "${EXPORT_DIR}/data/mysql/pageindex_dump.sql"
fi

if [ -d "${EXPORT_DIR}/data/minio" ]; then
  echo "Importing MinIO bucket"
  docker run --rm \
    --network "${PROJECT_NAME}_default" \
    --env-file "${ENV_FILE}" \
    -v "${EXPORT_DIR}/data/minio:/import:ro" \
    --entrypoint /bin/sh \
    minio/mc:latest \
    -lc 'mc alias set pageindex http://minio:9000 "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" >/dev/null && mc mb --ignore-existing "pageindex/${MINIO_BUCKET}" && mc mirror --overwrite /import "pageindex/${MINIO_BUCKET}"' \
    || echo "MinIO import skipped or incomplete; check bucket/service status." >&2
fi

echo "Starting API and frontend"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full up -d api frontend

echo "Checking API health"
curl -fsS "http://127.0.0.1:${API_PORT:-22223}/healthz" >/dev/null

cat <<'DONE'
Import complete.

Elasticsearch settings/mappings/document snapshots are kept under data/elasticsearch.
Current restore helper does not replay them automatically; prefer application rebuild flows for ES-backed indexes.
DONE
