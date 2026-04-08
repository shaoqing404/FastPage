# Configuration Specification

This file defines the minimum environment-based configuration for Phase 0.

## Phase 0 Minimum Configuration

| Variable | Description | Example |
| --- | --- | --- |
| `ADMIN_USERNAME` | Hardcoded administrator username | `admin` |
| `ADMIN_PASSWORD` | Hardcoded administrator password | `changeme` |
| `SECRET_KEY` | JWT signing secret | `change-this-random-string` |
| `DATA_DIR` | Local storage root directory | `./data` |
| `LLM_BASE_URL` | OpenAI-compatible LLM base URL | `https://api.openai.com/v1` |
| `LLM_API_KEY` | LLM API key | `sk-...` |
| `DATABASE_URL` | Database connection string | `sqlite:///./data/app.db` |

## Notes

- `DATA_DIR` should contain document artifacts, parse outputs, and service-local metadata exports.
- `DATABASE_URL` should default to SQLite in Phase 0.
- `LLM_BASE_URL` and `LLM_API_KEY` should support any OpenAI-compatible provider.
- `SECRET_KEY` must not be committed into git.

## Phase 1 Additional Configuration

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

Phase 1 rules:

- `DATABASE_URL` should switch to MySQL, for example `mysql+pymysql://pageindex_user:password@10.108.1.134:23306/pageindex`
- do not use shared application databases such as `rag_flow`
- do not use MySQL `root` as the application account
