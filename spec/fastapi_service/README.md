# FastAPI Service Plan

This folder contains the staged plan for turning the current PageIndex workspace into a FastAPI-based service.

## Planning Rules

- Phase 0 optimizes for working functionality, not full production hardening.
- Security is intentionally simplified in Phase 0, but the data model and service boundaries should not block later multi-user and multi-tenant support.
- PDF parsing/indexing should reuse the current PageIndex code path where possible.
- Storage starts locally in Phase 0, then evolves to object storage and relational persistence in Phase 1.
- Frontend is out of scope for implementation right now, but backend contracts and handoff notes must be clear enough for a later Vite frontend build.

## Working-Tree Layout

The current working tree restores the closeout-relevant stage docs first.

Current active entries:

- [`phase4_access_and_admin_control_plane/README.md`](phase4_access_and_admin_control_plane/README.md)
- [`phase4_access_and_admin_control_plane/phase4_closeout_status.md`](phase4_access_and_admin_control_plane/phase4_closeout_status.md)
- [`phase4_access_and_admin_control_plane/phase4_10_routing_speed_and_structure_foundation.md`](phase4_access_and_admin_control_plane/phase4_10_routing_speed_and_structure_foundation.md)
- [`phase4_access_and_admin_control_plane/phase4_10_execution_prompts.md`](phase4_access_and_admin_control_plane/phase4_10_execution_prompts.md)
- [`phase4_access_and_admin_control_plane/phase4_11_b_stage_baseline_and_phase5_entry.md`](phase4_access_and_admin_control_plane/phase4_11_b_stage_baseline_and_phase5_entry.md)
- [`phase5_maintenance_and_audit_governance/README.md`](phase5_maintenance_and_audit_governance/README.md)

Historical phase0-phase3 and shared planning docs remain available in git history and can be restored if the closeout work needs them again.

## Current Runtime Contract

As of `2026-04-30`, the parent-stage recommendation is:

- `Phase 4.5`: `Conditional GO`
- `Phase 4.6`: `GO`
- `Phase 4.7`: `GO` after the current-tree runtime rerun passed and was finalized as `results/phase4_7_backend_validation_passed_20260423T100430Z.json`
- `Phase 4.8`: `GO`
- `Phase 4.9`: `Conditional GO`
- `Phase 4.10`: `Conditional GO`
- `Phase 4.11`: `GO with follow-up`
- `Phase 4`: `Conditional GO`
- `Phase 5`: `NO-GO`

Current B4.2+ / B4.5 runtime decisions:

- Elasticsearch-backed indexed data is the production runtime path for FastSearch and DeepResearch context retrieval.
- Missing ES, stale routing index data, or missing searchable `section_text` / page-text data is a degraded `data_not_ready` / GO-blocking state, not a silent fallback to local embedding artifacts.
- Runtime PDF `get_page_tokens` extraction is not a production GO path; it is debug / emergency fallback only when explicitly enabled.
- `/api/v1/search/fast` is a low-level retrieval/debug API. Skills Chat is the standard product answer interface.
- Skills Chat supports `retrieval_config.retrieval_mode` values `"fast"` and `"deep_research"`.
- OpenAI-compatible providers are supported upstream for LLM/rerank/embedding execution. A public OpenAI-compatible `/v1/chat/completions` API surface is not currently part of this service contract.
- B4.5 streaming stabilization preserves the runtime implementation while reducing hot-path overhead: no per-chunk DB commit/refresh, sampled `answer_delta` observations, reused Redis publish client, and batched frontend streaming answer updates.
- B4.5 API reliability hardening keeps the worker/API architecture but removes long-lived request DB sessions from SSE streams, env-configures the MySQL pool budget, guards startup migrations, and adds Redis connection health/timeout protections.
- The first archived 500Q Skills Chat comparison is `GO with follow-up`: FastSearch is currently faster and higher quality than DeepResearch on the tested operating-manual cohort; remaining work is retrieval parallelization, context compression, and caching rather than B-stage runtime blocking.

The current closeout tracker is:

- [`phase4_access_and_admin_control_plane/phase4_closeout_status.md`](phase4_access_and_admin_control_plane/phase4_closeout_status.md)

## Historical Foundation

Build Phase 0 first with:

- `FastAPI`
- `Pydantic`
- `SQLAlchemy` + `Alembic`
- `SQLite` for local metadata persistence
- local filesystem for uploaded PDFs, parsed outputs, versions, and logs
- background job execution in-process first

This keeps implementation small while preserving a clean migration path to:

- `MySQL`
- `MinIO`
- API key based access control
- tenant-scoped ownership and quotas
