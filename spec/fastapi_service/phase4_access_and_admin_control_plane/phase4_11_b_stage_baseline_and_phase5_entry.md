# Phase 4.11 B-Stage Baseline And Phase 5 Entry

- Repository root: current PageIndex checkout
- Parent stage: `Phase 4 Access, Admin, and Pre-Phase5 Closeout`
- Status date: `2026-04-30`
- Current decision: `GO with follow-up`

## 1. Purpose

`Phase 4.11` is the Phase 4 closeout baseline for the B-stage routing/runtime work and the handoff point into `Phase 5.0`.

It records three completed workstreams:

- enhanced routing: ES-backed FastSearch / DeepResearch runtime search, routing-index foundation, and production no-artifact-fallback rule
- A refactor: prior runtime/retrieval restructuring work that made indexed section text available to the query paths and isolated runtime PDF extraction from production readiness
- B refactor: Skills Chat streaming/runtime stabilization, API DB-pool reliability, and FastSearch / DeepResearch product baseline validation

This phase is deliberately a closeout and handoff record. It does not reopen the routing schema, evidence-layer semantics, or product mode definitions.

## 2. Phase Mapping

`Phase 4.11` sits across existing Phase 4 work instead of replacing it:

- `Phase 4.10` owns the routing speed and structure foundation.
- `B4.2` owns the ES-only runtime search decision and FastSearch product boundary.
- `Phase 4.5` owns Skills Chat runtime hardening, SSE reliability, DB pool behavior, and API/worker separation.
- `Phase 4.11` records the combined B-stage baseline and moves remaining optimization into `Phase 5.0`.

The key boundary is:

- Phase 4 proves the runtime/product baseline is operable and stable enough to close.
- Phase 5 improves cost, latency, quality, governance, and long-running operational polish.

## 3. Baseline Evidence

The first archived 500Q Skills Chat FastSearch / DeepResearch comparison is the baseline evidence for this closeout:

- Artifact directory: `/Users/shaoqing/workspace/PageIndex/test/20240430_Pageindex_SkillsChat_FastSearch_and_DeepResearch_5000Q/test0428_5000/`
- Reports:
  - `b4_4_skill_analysis_report.md`
  - `b4_5_skill_attribution_report.md`
  - `b4_4_skill_leader_report.xlsx`

Observed results:

- FastSearch: `500/500 OK`, end-to-end p50 / p95 `13.96s / 22.78s`, quality average `7.84`
- DeepResearch: `500/500 OK`, end-to-end p50 / p95 `20.74s / 49.02s`, quality average `6.84`
- paired questions: `499`
- FastSearch faster on `444+` paired questions
- DeepResearch faster on `55` paired questions
- FastSearch quality better on `166` paired questions
- DeepResearch quality better on `22` paired questions

Interpretation:

- FastSearch is the current primary business landing path for direct operating-manual Q&A.
- DeepResearch remains available as a broader reasoning path, but this batch does not prove a stable quality premium over FastSearch for the tested cohort.
- The previous API/SSE/DB-pool runtime blockers are no longer dominant in this baseline.

## 4. Closed B-Stage Decisions

The following decisions are now closed for the Phase 4 baseline:

- Skills Chat is the standard product answer surface.
- `/api/v1/search/fast` remains the low-level retrieval/debug surface.
- `retrieval_config.retrieval_mode` accepts `"fast"` and `"deep_research"`.
- ES-backed indexed node / section text / vector data is the production runtime path.
- Local embedding artifact exact scan is legacy transitional infrastructure only.
- Runtime PDF extraction is debug / emergency fallback only and does not satisfy production GO.
- Worker/API separation remains the enterprise deployment architecture.
- Long SSE streams must not hold request-scoped DB sessions.
- DB pool sizing is an explicit deployment budget, not a hidden SQLAlchemy default.

## 5. Follow-Up Work Moved To Phase 5.0

The following items are intentionally not B-stage blockers:

- full 5000Q soak/regression analysis during the May Day holiday window
- FastSearch context compression, selective parent suppression, and query-aware excerpt/window design
- retrieval parallelization and section-load caching
- DeepResearch quality tuning for over-conservative "insufficient information" answers
- richer telemetry for final context size, per-selected-node token estimates, and suppression decisions
- cost/capacity tuning for provider TTFT and prompt-cache behavior

These are Phase 5.0 entry tasks because the baseline is already operable, but not yet cost/latency optimal.

## 6. GO / NO-GO

`Phase 4.11 B-stage baseline`: `GO with follow-up`.

`Phase 4 parent stage`: `Conditional GO`.

`Phase 5.0`: may start from this baseline, with the 5000Q run treated as soak/regression evidence rather than a blocker for the baseline commit.
