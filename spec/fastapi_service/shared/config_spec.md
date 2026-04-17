# Configuration Specification

This file defines the runtime environment configuration contract for the service.

## Database Configuration Priority

Database selection must follow this order:

1. `DATABASE_URL`
2. `DATABASE_MODE`
3. mode-specific variables

Rules:

- `DATABASE_URL` is an expert override. If it is set, it wins over every other database variable.
- If `DATABASE_URL` is empty, `DATABASE_MODE` controls the runtime database path.
- Default `DATABASE_MODE` is `sqlite`.
- `SQLITE_PATH` is optional. If omitted in SQLite mode, the service uses `${DATA_DIR}/app.db`.
- In MySQL mode the service assembles the URL from `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, and `MYSQL_PASSWORD`.
- Existing deployments that already use `DATABASE_URL=mysql+pymysql://...` remain valid.

## Minimum Local Configuration

Recommended local baseline:

| Variable | Description | Example |
| --- | --- | --- |
| `ADMIN_USERNAME` | Bootstrap administrator username | `admin` |
| `ADMIN_PASSWORD` | Bootstrap administrator password | `changeme` |
| `SECRET_KEY` | JWT signing secret | `change-this-random-string` |
| `DATA_DIR` | Local storage root directory | `./data` |
| `DATABASE_MODE` | Database runtime selector | `sqlite` |
| `SQLITE_PATH` | Optional SQLite file path override | `./data/dev.db` |
| `LLM_BASE_URL` | OpenAI-compatible LLM base URL | `https://api.openai.com/v1` |
| `LLM_API_KEY` | LLM API key | `sk-...` |

Local mode notes:

- if neither `DATABASE_URL` nor `DATABASE_MODE` is set, the service defaults to local SQLite
- default SQLite location is `${DATA_DIR}/app.db`
- `SQLITE_PATH` should be a filesystem path, not a `sqlite:///` URL
- `SECRET_KEY` must not be committed into git

## MySQL Runtime Configuration

Recommended normal MySQL path:

| Variable | Description | Example |
| --- | --- | --- |
| `DATABASE_MODE` | Database runtime selector | `mysql` |
| `MYSQL_HOST` | MySQL host | `10.108.1.134` |
| `MYSQL_PORT` | MySQL port | `3306` |
| `MYSQL_DATABASE` | Application database name | `pageindex` |
| `MYSQL_USER` | Application database user | `pageindex_user` |
| `MYSQL_PASSWORD` | Application database password | `change-me` |

MySQL rules:

- do not use shared application databases such as `rag_flow`
- do not use MySQL `root` as the application account
- `MYSQL_PASSWORD` is required when `DATABASE_MODE=mysql`
- expert users may still use `DATABASE_URL=mysql+pymysql://pageindex_user:password@10.108.1.134:3306/pageindex`

## Additional Runtime Configuration

| Variable | Description | Example |
| --- | --- | --- |
| `STORAGE_BACKEND` | Artifact backend selector | `local` or `minio` |
| `TASK_QUEUE_BACKEND` | Task queue selector | `local` or `redis` |
| `MINIO_ENDPOINT` | MinIO host and port | `10.108.1.134:9000` |
| `MINIO_ACCESS_KEY` | MinIO access key | `pageindex_user` |
| `MINIO_SECRET_KEY` | MinIO secret key | `change-me` |
| `MINIO_BUCKET` | MinIO bucket name | `pageindex` |
| `MINIO_PREFIX_PATH` | Optional object prefix | `pageindex-dev` |
| `MINIO_SECURE` | Whether MinIO uses HTTPS | `false` |
| `REDIS_URL` | Redis connection string | `redis://:password@10.108.1.134:26379/1` |
| `QUEUE_NAME_PARSE` | Parse queue name | `pageindex:parse` |
| `QUEUE_NAME_CHAT` | Chat queue name | `pageindex:chat` |
| `CORS_ALLOW_ORIGINS` | Allowed frontend origins, comma-separated | `http://10.108.2.18:5174,http://localhost:5174` |
