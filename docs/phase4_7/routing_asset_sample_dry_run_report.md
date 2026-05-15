# Routing Asset Sample Dry-Run Report

Date: 2026-04-24

Task: PageIndex IE closeout subtask C, real-sample routing asset dry-run validation.

## Scope

- Repository: `/Users/shaoqing/workspace/PageIndex`
- DB/storage/provider source: current project `.env`
- DB writes: no committed writes
- Storage writes: none
- Backfill/rollback `--execute`: not run
- Online retrieval/chat/compliance path: not touched
- Synthetic queries and embeddings: not built

## Environment

- Database: MySQL, masked URL `mysql+pymysql://root:***@10.108.1.134:23306/pageindex`
- Storage: MinIO, endpoint `10.108.1.134:9000`, bucket `pageindex`, secure `false`
- Redis: configured
- Provider: OpenAI-compatible base host `dashscope.aliyuncs.com`; provider key present but not recorded
- Default model: `openai/qwen-plus`
- Routing build modes:
  - `ROUTING_ROUTE_DOCS_BUILD_MODE=disabled`
  - `ROUTING_SYNTHETIC_QUERIES_BUILD_MODE=disabled`
  - `ROUTING_EMBEDDINGS_BUILD_MODE=disabled`

## Migration Gate

Command:

```bash
uv run alembic heads && uv run alembic current
```

Result:

- Alembic head: `20260423_0013`
- Current DB revision: `20260423_0013 (head)`
- Routing maintenance schema gate: `ready`
- Missing required tables: none
- Missing required columns: none

## Required File Review

Reviewed:

- `scripts/phase47/routing_asset_maintenance.py`
- `docs/phase4_7/routing_asset_backfill_runbook.md`
- `app/services/parse_service.py`
- `app/services/pageindex_service.py`
- `app/models/routing_asset_contract.py`
- `app/services/storage_service.py`

Relevant behavior confirmed:

- `scan`/`validate` are read-only and require Alembic head plus routing schema columns.
- Backfill defaults to dry-run; mutation requires explicit `--execute`.
- Online parse writes parsed structure, then builds routing index from structure.
- Routing row persistence deletes existing `document_routing_nodes` for the version before inserting rebuilt rows.
- Optional route docs, synthetic queries, and embeddings default to deferred/disabled and are not online retrieval inputs.

## Commands Run

```bash
uv run python scripts/phase47/routing_asset_maintenance.py scan \
  --sample-limit 20 \
  --output results/routing_asset_sample_dry_run_scan_20260424.json
```

```bash
uv run python -m py_compile scripts/phase47/routing_asset_sample_dry_run.py
```

```bash
uv run python scripts/phase47/routing_asset_sample_dry_run.py \
  --sample-limit 5 \
  --output results/routing_asset_sample_dry_run_20260424.json
```

```bash
uv run python scripts/phase47/routing_asset_maintenance.py validate \
  --summary-threshold 1.0 \
  --sample-limit 20 \
  --output results/routing_asset_sample_dry_run_validate_20260424.json
```

Rollback verification for the transactional idempotency dry-run:

```bash
uv run python - <<'PY'
import sqlalchemy as sa
from app.core.config import get_settings
engine = sa.create_engine(get_settings().database_url, future=True)
version_id = '623c2d39-9723-4db4-a988-4ec77f661eaf'
with engine.connect() as conn:
    count = conn.execute(
        sa.text('SELECT COUNT(*) FROM document_routing_nodes WHERE version_id=:version_id'),
        {'version_id': version_id},
    ).scalar()
print({'version_id': version_id, 'row_count_after_rollback': int(count or 0)})
engine.dispose()
PY
```

Result: `row_count_after_rollback=0`.

## Existing DB Scan

The current DB already had enough real `parse_status=index_ready` versions with `parsed_structure_path`, so no new PDF parse was required.

`routing_asset_maintenance.py scan` / `validate` summary:

| Metric | Value |
| --- | ---: |
| total_versions | 15 |
| eligible_versions | 15 |
| ready_count | 0 |
| missing_count | 15 |
| failed_count | 0 |
| low_summary_coverage_count | 0 |
| missing_rate | 1.0 |
| failure_rate | 0.0 |
| ready_rate | 0.0 |
| persisted routing node_count | 0 |
| persisted summary_count | 0 |
| persisted missing_summary_count | 0 |
| persisted coverage_ratio | 0.0 |

All 15 eligible versions are currently missing routing asset rows/path:

- `routing_index_status=uploaded`
- `routing_index_path` absent
- `document_routing_nodes` rows absent

## Downloads PDF Candidates

`/Users/shaoqing/Downloads` was checked for 3-5 real PDF candidates. The largest candidates were:

| File | Size |
| --- | ---: |
| `operations_manual_v1_main.pdf` | 33M |
| `mineru.pdf` | 19M |
| `苹果尴尬的 cod 能力提升训练.pdf` | 6.6M |
| `DeepSeek_V4(2).pdf` | 4.3M |
| `2603.27703v1.pdf` | 3.9M |
| `RTX_PRO_6000测试报告 2026 年 4 月 10 日.pdf` | 787K |

Fresh parse from Downloads was skipped because the DB already had 15 real parsed versions, including manuals and multi-manual samples.

## Sample Dry-Run Build Results

Sample source: existing DB `index_ready` versions with MinIO `structure.json`.

The helper loaded each parsed structure and called `build_routing_index_payload(..., build_options=RoutingBuildOptions.disabled())`. It did not write `routing_index.json` to storage and did not commit DB changes.

| File | Build | node_count | summary_count | missing_summary_count | coverage_ratio | readiness | routing_index_status | Reason |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `operations_manual_v1.pdf` | success | 265 | 0 | 265 | 0.0 | base_nodes ready; optional assets deferred | uploaded | existing routing asset missing |
| `operations_manual_v1_main.pdf` | success | 265 | 0 | 265 | 0.0 | base_nodes ready; optional assets deferred | uploaded | existing routing asset missing |
| `DCS_F-16C_Early_Access_Guide_CN.pdf` | success | 229 | 0 | 229 | 0.0 | base_nodes ready; optional assets deferred | uploaded | existing routing asset missing |
| `DCS FA-18C Early Access Guide EN.pdf` | success | 404 | 0 | 404 | 0.0 | base_nodes ready; optional assets deferred | uploaded | existing routing asset missing |
| `mineru.pdf` | success | 37 | 0 | 37 | 0.0 | base_nodes ready; optional assets deferred | uploaded | existing routing asset missing |

Totals for sample dry-run:

| Metric | Value |
| --- | ---: |
| sample_count | 5 |
| success_count | 5 |
| failure_count | 0 |
| missing_count | 5 |
| skipped_count | 0 |

Interpretation:

- Base routing nodes are buildable from all 5 real parsed structures.
- Summary coverage is 0% for all 5 because the existing parsed structures have no node `summary` values.
- Optional routing assets are intentionally deferred because all routing build modes are disabled.
- The persisted DB state is still missing routing assets because no backfill execute was run.

## Idempotency

Idempotency sample:

- File: `operations_manual_v1.pdf`
- document_id: `72e28541-ffe7-4c6d-b303-b94f8d61640f`
- version_id: `623c2d39-9723-4db4-a988-4ec77f661eaf`
- Mode: DB transaction, no storage write, rollback in `finally`

Result: passed.

| Check | Result |
| --- | --- |
| first_build_node_count | 265 |
| second_build_node_count | 265 |
| first_readiness | base_nodes ready; optional assets deferred |
| second_readiness | base_nodes ready; optional assets deferred |
| first_replace | deleted 0, inserted 265, post_replace_count 265 |
| second_replace | deleted 265, inserted 265, post_replace_count 265 |
| stable_node_count | true |
| stable_readiness | true |
| replaced_not_appended | true |
| rolled_back | true |
| row_count_after_rollback | 0 |

The second rebuild deleted the first rebuild's in-transaction rows before inserting the rebuilt rows. The row count stayed at 265 instead of growing to 530, which verifies replace-not-append behavior for the same version.

## Evidence Files

Local evidence JSON files written:

- `results/routing_asset_sample_dry_run_scan_20260424.json`
- `results/routing_asset_sample_dry_run_validate_20260424.json`
- `results/routing_asset_sample_dry_run_20260424.json`

These are local validation evidence. They are useful for audit but should not be submitted by default unless the reviewer wants raw local evidence in the change.

Auxiliary script added:

- `scripts/phase47/routing_asset_sample_dry_run.py`

Report added:

- `docs/phase4_7/routing_asset_sample_dry_run_report.md`

## Cleanup Notes

No temporary DB rows or storage artifacts were committed.

Only local evidence JSON files were created under `results/`. Safe cleanup, if desired:

```bash
rm results/routing_asset_sample_dry_run_scan_20260424.json \
   results/routing_asset_sample_dry_run_validate_20260424.json \
   results/routing_asset_sample_dry_run_20260424.json
```

Do not run routing asset backfill or rollback with `--execute` without a separate explicit approval.

## Blockers And Risks

- No DB migration blocker: DB is at Alembic head.
- Main readiness gap: persisted routing assets are missing for all 15 eligible versions in the current DB.
- Quality gap: dry-run built nodes have 0% summary coverage because source parsed structures lack summaries.
- This task did not validate online retrieval, chat, compliance, synthetic queries, or embeddings by design.
