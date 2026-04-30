# Phase 4.10 Execution Prompts

These prompts are intended for implementation agents working under the `Phase 4.10` plan.

All prompts assume repository root:

- `/Users/shaoqing/workspace/PageIndex`

Primary phase spec:

- [phase4_10_routing_speed_and_structure_foundation.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_10_routing_speed_and_structure_foundation.md)

## Python Environment Rule

When you need Python in this repository:

- use the already-created `uv` virtual environment at the repository root
- run Python commands from repository root via `uv run ...`
- do not create a new venv
- do not fall back to system Python unless the user explicitly asks you to

## Prompt 1: Batch 4.10-A Retrieval Correctness And Observability Hardening

### Task type

`Phase 4.10 / Batch 4.10-A / backend implementation`

### Specs to read

- [phase4_10_routing_speed_and_structure_foundation.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_10_routing_speed_and_structure_foundation.md)
- [phase4_9_multi_manual_runtime_and_observability_closeout.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_9_multi_manual_runtime_and_observability_closeout.md)
- [phase4_closeout_status.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_closeout_status.md)

### Files to inspect

- `app/services/chat_service.py`
- `app/services/pageindex_service.py`
- `app/services/compliance_service.py`
- `tests/phase4/test_skill_stream_runtime_contract.py`
- `tests/phase4/test_chat_run_worker_logging.py`
- `tests/phase4/test_pageindex_llm_failfast.py`
- `tests/phase4/test_pageindex_native_rerank.py`

### Allowed write scope

- `app/services/chat_service.py`
- `app/services/pageindex_service.py`
- `app/services/compliance_service.py`
- `tests/phase4/*`

### Do not touch

- migrations
- parse/index schema work
- frontend
- provider/workspace product semantics
- live router redesign

### Implementation goals

- make outline-selection prompt cardinality honor the actual runtime selection count instead of hardcoding `1 to 5`
- fix rerank-off merge behavior so multi-manual selection does not silently starve later manuals due to raw concatenation order
- make `max_context_tokens` a real enforced cap even for the first selected section
- aggregate and persist usable outline/retrieval diagnostics back into execution context and runtime observations
- keep the fix compatible with both `chat` and `compliance` surfaces where shared helper behavior applies

### Non-goals

- do not add embedding retrieval
- do not add a live manual router
- do not change product behavior beyond the correctness fixes above

### Acceptance criteria

- targeted tests cover:
  - outline prompt / selection-count contract
  - rerank-off deterministic merge behavior
  - first-section token-cap enforcement
  - populated retrieval diagnostics
- existing query path remains backward compatible apart from the bug fixes

### Response requirements

- Final summary and findings must be written in Chinese.
- Include exact files changed.
- If any acceptance criterion is not met, say so directly.

## Prompt 2: Batch 4.10-B Multi-Manual Structure/PDF Reuse Hardening

### Task type

`Phase 4.10 / Batch 4.10-B / backend implementation`

### Dependency order

- Run this only after `Batch 4.10-A` is merged, because the write scope overlaps in `pageindex_service.py`.

### Specs to read

- [phase4_10_routing_speed_and_structure_foundation.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_10_routing_speed_and_structure_foundation.md)

### Files to inspect

- `app/services/pageindex_service.py`
- `app/services/storage_service.py`
- `pageindex/utils.py`
- `app/services/chat_service.py`
- `app/services/compliance_service.py`
- `tests/phase4/*`

### Allowed write scope

- `app/services/pageindex_service.py`
- `app/services/storage_service.py`
- `pageindex/utils.py`
- `tests/phase4/*`

### Do not touch

- migrations
- document/routing schema
- frontend
- product strategy docs

### Implementation goals

- investigate and fix repeated same-run reuse problems for:
  - `parsed_structure_path`
  - `storage_path`
  - `get_page_tokens(pdf_path, model=...)`
- prefer safe run-scoped reuse keyed by source path and model
- keep Local storage and MinIO-backed `local_artifact_path()` behavior correct
- avoid cross-run / cross-tenant unsafe global leakage

### Non-goals

- do not introduce a distributed cache
- do not redesign evidence extraction into paragraph windows
- do not add background workers or external cache services

### Acceptance criteria

- targeted tests prove repeated citations from the same PDF do not force full reopen/re-tokenize work each time in a single run
- structure reuse is safe for repeated same-run access
- implementation is narrow and does not expand into routing-index schema work

### Response requirements

- Final summary and findings must be written in Chinese.
- Include exact files changed.
- If a fully safe reuse layer cannot be implemented, explain the blocker and stop instead of guessing.

## Prompt 3: Batch 4.10-C Routing Index Schema Foundation

### Task type

`Phase 4.10 / Batch 4.10-C / backend implementation`

### Specs to read

- [phase4_10_routing_speed_and_structure_foundation.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_10_routing_speed_and_structure_foundation.md)
- [migration_plan.md](spec/fastapi_service/phase4_access_and_admin_control_plane/migration_plan.md)
- [phase4_closeout_status.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_closeout_status.md)

### Files to inspect

- `app/models/document.py`
- `app/core/db.py`
- `migrations/versions/*`
- `tests/phase4/test_migrations_smoke.py`
- `tests/phase4/test_bootstrap_init_db.py`

### Allowed write scope

- `app/models/document.py`
- `app/models/*.py`
- `migrations/versions/*`
- `tests/phase4/*`

### Do not touch

- frontend
- live retrieval/query behavior
- parse/index service logic beyond what is strictly needed for model imports
- provider/workspace control-plane code

### Implementation goals

- add a routing-index lifecycle contract to `document_versions`
- add a portable relational table for routing nodes
- keep the first version SQLite + MySQL portable without JSON/vector type dependencies

### Required schema direction

- extend `document_versions` with routing-index lifecycle fields, for example:
  - `routing_index_status`
  - `routing_index_path`
  - `routing_index_error`
  - `routing_index_version`
- add a new `document_routing_nodes` table with fields in this direction:
  - `id`
  - `document_id`
  - `version_id`
  - `node_id`
  - `parent_node_id`
  - `depth`
  - `title`
  - `breadcrumb`
  - `page_start`
  - `page_end`
  - `route_summary`
  - `contrastive_summary`
  - `aliases_json`
  - `keywords_json`
  - `manual_profile_text`
  - timestamps
- add a uniqueness rule at least on `(version_id, node_id)`
- add indexes that make later per-version routing lookups efficient

### Portability rules

- use portable SQLAlchemy types only
- if SQLite cannot perform an in-place migration step, branch explicitly in Alembic
- do not require live MySQL-only features

### Acceptance criteria

- SQLite migration smoke remains green
- MySQL compatibility remains explicit in migration/model choices
- model import / bootstrap tests remain green
- no query-path behavior is changed in this batch

### Response requirements

- Final summary and findings must be written in Chinese.
- Include exact files changed.
- Call out any SQLite/MySQL portability assumption explicitly.

## Prompt 4: Batch 4.10-D Routing Index Build Pipeline

### Task type

`Phase 4.10 / Batch 4.10-D / backend implementation`

### Dependency order

- Run this only after `Batch 4.10-C` is merged.

### Specs to read

- [phase4_10_routing_speed_and_structure_foundation.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_10_routing_speed_and_structure_foundation.md)
- [phase4_10_execution_prompts.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_10_execution_prompts.md)

### Files to inspect

- `app/services/parse_service.py`
- `app/services/pageindex_service.py`
- `app/services/storage_service.py`
- `pageindex/page_index.py`
- `pageindex/utils.py`
- `app/models/document.py`
- `tests/phase4/*`

### Allowed write scope

- `app/services/parse_service.py`
- `app/services/pageindex_service.py`
- `app/services/storage_service.py`
- `pageindex/utils.py`
- `tests/phase4/*`

### Do not touch

- frontend
- live chat/compliance retrieval logic beyond backward-compatible compatibility hooks
- migrations already landed by `4.10-C`

### Implementation goals

- stop forcing `if_add_node_summary=\"no\"` in the online service parse path
- build and persist a `routing_index` artifact for new parse jobs
- populate the `4.10-C` DB routing lifecycle fields and routing-node rows
- keep the current chat/compliance query path backward compatible and not yet dependent on the routing index

### Routing-index content rules

- mandatory fields should be populated from current structure truth:
  - `manual/document label`
  - `node_id`
  - `parent_node_id`
  - `depth`
  - `title`
  - `breadcrumb`
  - `page span`
  - `route_summary` from node summary when available
- optional future-router fields may be nullable in this first version if they cannot be produced reliably yet:
  - `contrastive_summary`
  - `aliases_json`
  - `keywords_json`

### Compatibility rules

- keep `parse_status` behavior backward compatible for the existing query path
- track routing-index success/failure through the new routing lifecycle fields instead of breaking the old query path blindly
- if routing-index generation fails, record the error clearly

### Acceptance criteria

- new parse jobs emit summaries again on the service path
- new parse jobs write routing-index artifact + DB rows
- old docs remain queryable without requiring routing-index backfill
- targeted tests cover success and failure recording behavior

### Response requirements

- Final summary and findings must be written in Chinese.
- Include exact files changed.
- State clearly whether any existing documents require a manual reparse/backfill to obtain routing assets.
