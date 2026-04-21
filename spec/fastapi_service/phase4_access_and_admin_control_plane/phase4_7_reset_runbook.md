# Phase 4.7 Reset Runbook

- Stage: `Phase 4.7`
- Repository root: current PageIndex checkout
- Purpose: standardize the pre-validation reset for the inherited `Phase 4.5` and `Phase 4.6` control-plane surface.
- Non-goal: this runbook does not add product scope and does not authorize deleting unknown data on shared infrastructure.

## 1. Safety Boundary

Only clear assets owned by this repo.

Allowed reset targets:

- MySQL tables managed by this repo
- MinIO objects under this repo's bucket/prefix
- local runtime data for this repo

Never clear:

- unknown tables in the same MySQL server
- unrelated MinIO buckets or prefixes
- unrelated Redis databases or queues shared by other projects
- frontend build caches outside this repo

## 2. Repo-Owned Data Map

MySQL tables managed by this repo:

- `alembic_version`
- `api_keys`
- `audit_events`
- `chat_messages`
- `chat_runs`
- `chat_sessions`
- `chat_skill_documents`
- `chat_skills`
- `compliance_checks`
- `compliance_runs`
- `document_versions`
- `documents`
- `knowledge_base_documents`
- `knowledge_bases`
- `migration_review_items`
- `model_providers`
- `parse_jobs`
- `revoked_tokens`
- `tenant_memberships`
- `tenants`
- `users`
- `workspace_invites`
- `workspace_memberships`
- `workspaces`

Local runtime paths owned by this repo:

- `data`
- `logs`
- `results`

MinIO scope owned by this repo:

- bucket: `MINIO_BUCKET`
- prefix root: `MINIO_PREFIX_PATH/tenants/`

## 3. Preconditions

- operator has read/write access to the project `.env` targets
- backend worker and API process are stopped, or the environment is otherwise quiesced
- `.env` resolves to the intended `MySQL + MinIO + Redis` surface
- a fresh validation output path is chosen under `results/`

Recommended preflight:

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python - <<'PY'
from app.core.config import get_settings
s = get_settings()
print("DATABASE_URL=", s.database_url)
print("STORAGE_BACKEND=", s.storage_backend)
print("MINIO_BUCKET=", s.minio_bucket)
print("MINIO_PREFIX_PATH=", s.minio_prefix_path)
print("TASK_QUEUE_BACKEND=", s.task_queue_backend)
PY
```

## 4. Reset Order

Use this order to avoid leaving dangling runtime references:

1. stop backend API / worker processes
2. clear MySQL repo-owned tables
3. clear MinIO repo-owned objects
4. clear local runtime directories
5. rerun migrations
6. rerun bootstrap
7. verify empty-but-valid baseline

## 5. MySQL Reset

The reset must run only against the schema named by `DATABASE_URL`.

Example operator flow:

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python - <<'PY'
from sqlalchemy import create_engine, text
from app.core.config import get_settings

TABLES = [
    "chat_messages",
    "chat_runs",
    "chat_sessions",
    "chat_skill_documents",
    "chat_skills",
    "knowledge_base_documents",
    "document_versions",
    "parse_jobs",
    "documents",
    "knowledge_bases",
    "api_keys",
    "workspace_invites",
    "workspace_memberships",
    "tenant_memberships",
    "model_providers",
    "compliance_runs",
    "compliance_checks",
    "audit_events",
    "revoked_tokens",
    "workspaces",
    "users",
    "tenants",
    "migration_review_items",
    "alembic_version",
]

engine = create_engine(get_settings().database_url, future=True)
with engine.begin() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    for table in TABLES:
        conn.execute(text(f"DELETE FROM {table}"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
print("mysql reset complete")
PY
```

If the schema contains tables not listed above:

- stop
- inspect them manually
- do not delete them under this runbook unless they are first confirmed as repo-owned

## 6. MinIO Reset

Only remove objects under the repo-owned bucket/prefix.

Example operator flow:

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python - <<'PY'
from minio import Minio
from app.core.config import get_settings

s = get_settings()
prefix = (s.minio_prefix_path or "").strip("/")
if prefix:
    prefix = prefix + "/"
root = f"{prefix}tenants/"

client = Minio(
    s.minio_endpoint,
    access_key=s.minio_access_key,
    secret_key=s.minio_secret_key,
    secure=s.minio_secure,
)

for obj in client.list_objects(s.minio_bucket, prefix=root, recursive=True):
    client.remove_object(s.minio_bucket, obj.object_name)

print("minio reset complete", s.minio_bucket, root)
PY
```

## 7. Local Runtime Reset

Remove only repo-local runtime outputs:

```bash
cd "$(git rev-parse --show-toplevel)"
rm -rf data/*
rm -rf logs/*
rm -rf results/*
mkdir -p data logs results
```

Do not delete:

- source-controlled PDFs in `examples/documents/`
- spec outputs committed to `spec/`
- `.env`

## 8. Rebuild

Run the rebuild exactly in this order:

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python - <<'PY'
from app.core.bootstrap import init_db
init_db()
print("bootstrap complete")
PY
```

Post-bootstrap checks:

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python -m unittest discover -s tests/phase4 -p 'test_*.py'
```

If Alembic CLI is available in the environment, also verify:

```bash
cd "$(git rev-parse --show-toplevel)"
uv run alembic heads
uv run alembic current
```

Expected result:

- single head: `20260416_0010`
- current revision: `20260416_0010`

## 9. Empty-But-Valid Baseline Checks

Before starting live validation, confirm:

- bootstrap admin can log in
- default tenant exists
- default workspace exists
- default admin is `is_platform_admin=true`
- default admin is `can_create_workspace=true`
- no leftover validation users/workspaces/providers/documents remain from previous runs

## 10. Failure Handling

If reset fails:

- do not proceed to runtime validation
- capture the exact failing command and stderr
- record whether the failure happened in MySQL, MinIO, local cleanup, migration, or bootstrap
- leave the environment frozen for triage instead of partially retrying ad hoc

## 11. Hand-Off to Validation

Once the reset is clean, continue with:

- `spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_runtime_validation_checklist.md`
- `spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_backend_validation.py`
- `spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_verification_artifact_retention_rule.md`
