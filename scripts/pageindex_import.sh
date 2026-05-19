#!/usr/bin/env bash
set -euo pipefail

EXPORT_DIR="${1:?用法：pageindex_import.sh /path/to/pageindex-export /path/to/PageIndex-Service}"
TARGET_DIR="${2:?用法：pageindex_import.sh /path/to/pageindex-export /path/to/PageIndex-Service}"
COMPOSE_FILE="${TARGET_DIR}/docker/docker-compose.yml"
ENV_FILE="${TARGET_DIR}/docker/.env"
PROJECT_NAME="${PAGEINDEX_COMPOSE_PROJECT_NAME:-docker}"
DATA_POLICY="${PAGEINDEX_IMPORT_DATA_POLICY:-keep-existing}"
OVERWRITE_CONFIRM="${PAGEINDEX_IMPORT_CONFIRM:-}"

case "${DATA_POLICY}" in
  keep-existing|skip-data|overwrite)
    ;;
  *)
    echo "不支持 PAGEINDEX_IMPORT_DATA_POLICY=${DATA_POLICY}。请使用 keep-existing、skip-data 或 overwrite。" >&2
    exit 1
    ;;
esac

if [ "${DATA_POLICY}" = "overwrite" ] && [ "${OVERWRITE_CONFIRM}" != "overwrite" ]; then
  cat >&2 <<'EOF'
PAGEINDEX_IMPORT_DATA_POLICY=overwrite 是破坏性操作。
如确认允许替换目标 MySQL 和 MinIO 数据，请额外设置 PAGEINDEX_IMPORT_CONFIRM=overwrite。
EOF
  exit 1
fi

if [ ! -f "${COMPOSE_FILE}" ]; then
  echo "缺少 compose 文件：${COMPOSE_FILE}" >&2
  exit 1
fi

if [ ! -f "${ENV_FILE}" ]; then
  echo "缺少 ${ENV_FILE}。请先从 docker/.env.example 复制并配置 docker/.env。" >&2
  exit 1
fi

if [ -f "${EXPORT_DIR}/images/pageindex-images.tar" ]; then
  echo "正在加载 Docker 镜像"
  docker load -i "${EXPORT_DIR}/images/pageindex-images.tar"
fi

echo "正在启动基础组件：MySQL / Redis / MinIO / Elasticsearch"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full up -d mysql redis minio elasticsearch

echo "正在等待基础组件健康"
for _ in $(seq 1 60); do
  unhealthy="$(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full ps --format json \
    | grep -E '"(mysql|redis|minio|elasticsearch)"' \
    | grep -vc '"Health":"healthy"' || true)"
  if [ "${unhealthy}" = "0" ]; then
    break
  fi
  sleep 3
done

echo "数据导入策略：${DATA_POLICY}"

mysql_table_count() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full exec -T mysql \
    sh -c 'MYSQL_PWD="${MYSQL_PASSWORD}" mysql -N -B -u"${MYSQL_USER}" -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '\''${MYSQL_DATABASE}'\'';"' \
    2>/dev/null | tr -d '\r'
}

if [ -s "${EXPORT_DIR}/data/mysql/pageindex_dump.sql" ]; then
  table_count="$(mysql_table_count || echo 0)"
  table_count="${table_count:-0}"
  if [ "${DATA_POLICY}" = "skip-data" ]; then
    echo "跳过 MySQL 导入：PAGEINDEX_IMPORT_DATA_POLICY=skip-data"
  elif [ "${DATA_POLICY}" = "keep-existing" ] && [ "${table_count}" != "0" ]; then
    echo "跳过 MySQL 导入：目标数据库已有 ${table_count} 张表，按默认策略以目标已有数据为准。"
  else
    if [ "${DATA_POLICY}" = "overwrite" ]; then
      echo "正在重置目标 MySQL 数据库后再导入"
      docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full exec -T mysql \
        sh -c 'case "${MYSQL_DATABASE}:${MYSQL_USER}" in (*[!A-Za-z0-9_:]*|:*|*:) echo "MYSQL_DATABASE 或 MYSQL_USER 包含不安全字符" >&2; exit 1;; esac; MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql -uroot -e "DROP DATABASE IF EXISTS ${MYSQL_DATABASE}; CREATE DATABASE ${MYSQL_DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON ${MYSQL_DATABASE}.* TO '\''${MYSQL_USER}'\''@'\''%'\''; FLUSH PRIVILEGES;"'
    fi
    echo "正在导入 MySQL dump"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full exec -T mysql \
      sh -c 'MYSQL_PWD="${MYSQL_PASSWORD}" mysql -u"${MYSQL_USER}" "${MYSQL_DATABASE}"' \
      < "${EXPORT_DIR}/data/mysql/pageindex_dump.sql"
  fi
fi

if [ -d "${EXPORT_DIR}/data/minio" ]; then
  if [ "${DATA_POLICY}" = "skip-data" ]; then
    echo "跳过 MinIO 导入：PAGEINDEX_IMPORT_DATA_POLICY=skip-data"
  else
    echo "正在检查目标 MinIO bucket"
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
      echo "跳过 MinIO 导入：目标 bucket 已有对象，按默认策略以目标已有数据为准。"
    else
      echo "正在导入 MinIO bucket"
      docker run --rm \
        --network "${PROJECT_NAME}_default" \
        --env-file "${ENV_FILE}" \
        -v "${EXPORT_DIR}/data/minio:/import:ro" \
        --entrypoint /bin/sh \
        minio/mc:latest \
        -c 'mc alias set pageindex http://minio:9000 "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" >/dev/null && mc mb --ignore-existing "pageindex/${MINIO_BUCKET}" >/dev/null && if [ "'"${DATA_POLICY}"'" = "overwrite" ]; then mc rm --recursive --force "pageindex/${MINIO_BUCKET}" || true; fi && mc mirror --overwrite /import "pageindex/${MINIO_BUCKET}"' \
        || echo "MinIO 导入被跳过或不完整；请检查 bucket 或服务状态。" >&2
    fi
  fi
fi

echo "正在启动 API 和前端"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full up -d api frontend

echo "正在检查 API 健康状态"
curl -fsS "http://127.0.0.1:${API_PORT:-22223}/healthz" >/dev/null

cat <<'DONE'
导入完成。

Elasticsearch 的 settings/mapping/文档快照保留在 data/elasticsearch 下。
当前恢复脚本不会自动 replay Elasticsearch；ES 索引建议通过应用流程重建。
Redis 不会被导入，它被视为队列/缓存运行态。
DONE
