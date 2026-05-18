#!/usr/bin/env bash
set -euo pipefail

EXPORT_DIR="${1:?Usage: pageindex_import.sh /path/to/pageindex-export /path/to/PageIndex-Service}"
TARGET_DIR="${2:?Usage: pageindex_import.sh /path/to/pageindex-export /path/to/PageIndex-Service}"
COMPOSE_FILE="${TARGET_DIR}/docker/docker-compose.yml"
ENV_FILE="${TARGET_DIR}/docker/.env"
PROJECT_NAME="${PAGEINDEX_COMPOSE_PROJECT_NAME:-docker}"
DATA_POLICY="${PAGEINDEX_IMPORT_DATA_POLICY:-keep-existing}"
OVERWRITE_CONFIRM="${PAGEINDEX_IMPORT_CONFIRM:-}"

case "${DATA_POLICY}" in
  keep-existing|skip-data|overwrite)
    ;;
  *)
    echo "Unsupported PAGEINDEX_IMPORT_DATA_POLICY=${DATA_POLICY}. Use keep-existing, skip-data, or overwrite." >&2
    exit 1
    ;;
esac

if [ "${DATA_POLICY}" = "overwrite" ] && [ "${OVERWRITE_CONFIRM}" != "overwrite" ]; then
  cat >&2 <<'EOF'
PAGEINDEX_IMPORT_DATA_POLICY=overwrite is destructive.
Set PAGEINDEX_IMPORT_CONFIRM=overwrite to confirm that target MySQL and MinIO data may be replaced.
EOF
  exit 1
fi

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

echo "Data import policy: ${DATA_POLICY}"

mysql_table_count() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full exec -T mysql \
    sh -c 'MYSQL_PWD="${MYSQL_PASSWORD}" mysql -N -B -u"${MYSQL_USER}" -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '\''${MYSQL_DATABASE}'\'';"' \
    2>/dev/null | tr -d '\r'
}

if [ -s "${EXPORT_DIR}/data/mysql/pageindex_dump.sql" ]; then
  table_count="$(mysql_table_count || echo 0)"
  table_count="${table_count:-0}"
  if [ "${DATA_POLICY}" = "skip-data" ]; then
    echo "Skipping MySQL import because PAGEINDEX_IMPORT_DATA_POLICY=skip-data"
  elif [ "${DATA_POLICY}" = "keep-existing" ] && [ "${table_count}" != "0" ]; then
    echo "Skipping MySQL import because target database already has ${table_count} table(s). Target data is authoritative."
  else
    if [ "${DATA_POLICY}" = "overwrite" ]; then
      echo "Resetting target MySQL database before import"
      docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full exec -T mysql \
        sh -c 'case "${MYSQL_DATABASE}:${MYSQL_USER}" in (*[!A-Za-z0-9_:]*|:*|*:) echo "Unsafe MYSQL_DATABASE or MYSQL_USER" >&2; exit 1;; esac; MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql -uroot -e "DROP DATABASE IF EXISTS ${MYSQL_DATABASE}; CREATE DATABASE ${MYSQL_DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON ${MYSQL_DATABASE}.* TO '\''${MYSQL_USER}'\''@'\''%'\''; FLUSH PRIVILEGES;"'
    fi
    echo "Importing MySQL dump"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full exec -T mysql \
      sh -c 'MYSQL_PWD="${MYSQL_PASSWORD}" mysql -u"${MYSQL_USER}" "${MYSQL_DATABASE}"' \
      < "${EXPORT_DIR}/data/mysql/pageindex_dump.sql"
  fi
fi

if [ -d "${EXPORT_DIR}/data/minio" ]; then
  if [ "${DATA_POLICY}" = "skip-data" ]; then
    echo "Skipping MinIO import because PAGEINDEX_IMPORT_DATA_POLICY=skip-data"
  else
    echo "Checking target MinIO bucket"
    minio_has_objects="$(
      docker run --rm \
        --network "${PROJECT_NAME}_default" \
        --env-file "${ENV_FILE}" \
        --entrypoint /bin/sh \
        minio/mc:latest \
        -c 'mc alias set pageindex http://minio:9000 "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" >/dev/null && mc mb --ignore-existing "pageindex/${MINIO_BUCKET}" >/dev/null && if mc find "pageindex/${MINIO_BUCKET}" --maxdepth 10 | { read -r _first; }; then echo yes; else echo no; fi' \
      2>/dev/null || echo unknown
    )"
    if [ "${DATA_POLICY}" = "keep-existing" ] && [ "${minio_has_objects}" = "yes" ]; then
      echo "Skipping MinIO import because target bucket already has objects. Target data is authoritative."
    else
      echo "Importing MinIO bucket"
      docker run --rm \
        --network "${PROJECT_NAME}_default" \
        --env-file "${ENV_FILE}" \
        -v "${EXPORT_DIR}/data/minio:/import:ro" \
        --entrypoint /bin/sh \
        minio/mc:latest \
        -c 'mc alias set pageindex http://minio:9000 "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" >/dev/null && mc mb --ignore-existing "pageindex/${MINIO_BUCKET}" >/dev/null && if [ "'"${DATA_POLICY}"'" = "overwrite" ]; then mc rm --recursive --force "pageindex/${MINIO_BUCKET}" || true; fi && mc mirror --overwrite /import "pageindex/${MINIO_BUCKET}"' \
        || echo "MinIO import skipped or incomplete; check bucket/service status." >&2
    fi
  fi
fi

echo "Starting API and frontend"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full up -d api frontend

echo "Checking API health"
curl -fsS "http://127.0.0.1:${API_PORT:-22223}/healthz" >/dev/null

cat <<'DONE'
Import complete.

Elasticsearch settings/mappings/document snapshots are kept under data/elasticsearch.
Current restore helper does not replay them automatically; prefer application rebuild flows for ES-backed indexes.
Redis is intentionally not imported. It is treated as queue/cache runtime state.
DONE
