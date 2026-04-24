# Phase 4.10 Routing Speed And Structure Foundation

- Repository root: current PageIndex checkout
- Parent stage: `Phase 4 Access, Admin, and Pre-Phase5 Closeout`
- Status date: `2026-04-23`
- Current decision: `Phase 4.10 closeout conditional-go pending parent-stage rerun`

## 1. Phase Intent

`Phase 4.10` exists to address the next layer of runtime debt after `Phase 4.9` landed the shared worker/runtime surface.

Its purpose is deliberately narrow:

- reduce avoidable retrieval/context latency caused by confirmed code-path bugs
- remove structural blockers that prevent future routing optimization work
- introduce a persisted `routing_index` foundation without yet changing the live evidence-layer contract

This is a speed-and-structure phase.

It is not a product-strategy phase.

## 2. Frozen Decisions

The following scope is frozen for this phase.

### 2.1 In scope

- `Code strategy 1`
  - retrieval correctness fixes
  - observability fixes
  - deterministic merge behavior fixes
  - context-budget enforcement fixes
  - narrow multi-manual structure/PDF reuse work
- `Code strategy 2`
  - add routing-index persistence foundation
  - make parse/index emit summary-backed routing assets again
  - land SQLite + MySQL portable DB support for routing assets

### 2.2 Explicitly out of scope

- product-surface redesign
- evidence-layer redesign beyond budget enforcement / safe reuse
- passage-window extraction redesign
- live `manual router` activation
- live `node router` activation
- retrieval-side model split
- synthetic query bank
- embedding-driven online routing

Those items belong to the later discussion for `code strategies 3/4/5/6`.

## 3. Current Code Truth

The approved `Phase 4.10` code strategy work is now materially landed in the tree.

### 3.1 Retrieval-side correctness / observability hardening landed

- outline-selection prompt cardinality now follows the actual runtime selection count instead of a hardcoded `1 to 5`
- rerank-off multi-manual merge no longer depends on raw manual concatenation followed by blind truncation
- retrieval diagnostics are aggregated back into execution context and runtime observations
- `max_context_tokens` is now enforced as a real budget constraint rather than allowing the first oversized section through unchecked

### 3.2 Same-run structure / PDF reuse hardening landed

- repeated same-run reads of `structure.json` are reused inside a run/request scope
- repeated same-run access to the same PDF source reuses page-token work keyed by source path and model
- MinIO-backed local artifact materialization is reused within the run scope and cleaned up with the scope lifecycle
- the implementation remains run-scoped rather than adding a process-global cache

### 3.3 Routing-index foundation landed

- the online parse path no longer forces node summaries off
- parse jobs now emit and persist both `structure.json` and `routing_index.json`
- `document_versions` now tracks routing-index lifecycle separately from `parse_status`
- `document_routing_nodes` provides a portable relational surface for future router work
- reparsing the same `DocumentVersion` now safely rebuilds routing rows instead of colliding with the `(version_id, node_id)` uniqueness rule
- repo reset/rebuild tooling now treats `document_routing_nodes` as part of the repo-owned schema

## 4. Phase Deliverables

`Phase 4.10` must land the following deliverables.

### 4.1 Runtime correctness hardening

- remove prompt/runtime cardinality mismatch for outline selection
- remove silent multi-manual starvation when rerank is disabled
- make `max_context_tokens` a real enforced budget
- emit usable retrieval diagnostics into execution context / runtime observations

### 4.2 Narrow reuse hardening

- stop needless repeated structure/PDF churn inside a single run when multiple citations share the same source assets
- keep storage safety and tenant isolation explicit

### 4.3 Routing asset foundation

- add a persisted `routing_index` artifact alongside `structure.json`
- add DB-tracked routing-index lifecycle on `document_versions`
- add a portable relational `document_routing_nodes` surface for future router work
- restore summary-backed parse output as an online service capability

## 5. Batch Structure

### Batch 4.10-A: Retrieval Correctness And Observability Hardening

Objective:

- fix the confirmed hot-path correctness / telemetry bugs without changing the broader routing design

Scope:

- `app/services/chat_service.py`
- `app/services/pageindex_service.py`
- targeted runtime/retrieval tests only

Acceptance criteria:

- outline selection prompt honors the actual requested max selection count
- rerank-off merge no longer depends on raw manual concatenation followed by blind truncation
- execution context records retrieval diagnostics that are actually populated
- context token budget is enforced even for the first selected section

Status:

- landed

Parallelism:

- blocking batch
- should land before any implementation batch that also edits `pageindex_service.py`

### Batch 4.10-B: Multi-Manual Structure/PDF Reuse Hardening

Objective:

- remove avoidable per-run asset churn when the same `parsed_structure_path` or `storage_path` is reused multiple times

Scope:

- `app/services/pageindex_service.py`
- `app/services/storage_service.py`
- `pageindex/utils.py`
- targeted reuse/perf tests only

Acceptance criteria:

- repeated citations from the same PDF do not force a full reopen/re-tokenize cycle for every citation inside one run
- structure loads can be safely reused within a run
- local-path and MinIO-backed flows remain correct

Status:

- landed

Parallelism:

- depends on `4.10-A`
- shared write scope with retrieval/context helpers means this should not be run in parallel with `4.10-A`

### Batch 4.10-C: Routing Index Schema Foundation

Objective:

- land the storage/model/migration contract for future routing assets in a SQLite + MySQL portable way

Scope:

- migrations
- routing-index DB models / document-version fields
- migration/model tests

Required schema direction:

- `document_versions` should track routing-index lifecycle separately from `parse_status`
- a new `document_routing_nodes` table should store portable text/integer route-doc fields
- avoid dialect-specific JSON/vector dependencies in the first version

Acceptance criteria:

- SQLite migration path is safe
- MySQL compatibility is explicit in schema/migration choices
- old query path remains backward compatible

Status:

- landed

Parallelism:

- blocking batch for all later routing-index build work

### Batch 4.10-D: Routing Index Build Pipeline

Objective:

- make parse/index produce summary-backed routing assets and persist them through the `4.10-C` contract

Scope:

- parse/index services
- storage write helpers for routing artifacts
- targeted parse/routing-index tests

Acceptance criteria:

- new parse jobs emit `summary` again on the online service path
- new parse jobs write a `routing_index` artifact
- DB routing status/path rows are updated consistently
- live chat/compliance query path remains backward compatible and does not require the routing index yet

Status:

- landed
- follow-up review fix landed for same-version reparse, so routing rows are rebuilt safely on repeated parse jobs

Parallelism:

- depends on `4.10-C`
- should not be run in parallel with schema work that is still in flight

## 6. SQLite / MySQL Portability Rule

This phase explicitly carries a dual-database requirement.

Required rule set:

- use portable column types first:
  - `String`
  - `Integer`
  - `Text`
  - `DateTime`
- if a field is naturally list-like or map-like, store it as serialized text in the first version unless both dialects can support the same semantics safely
- do not introduce vector columns in this phase
- do not require MySQL-only JSON semantics in the first version
- migrations must branch when SQLite cannot perform an in-place constraint or alter operation
- tests must keep SQLite migration smoke explicit and must keep MySQL compatibility visible at least at the config/dialect contract level

## 7. Non-Goals

`Phase 4.10` does not yet decide:

- how live manual routing will score manuals
- how node hybrid retrieval will be ranked online
- whether synthetic queries will be generated
- whether retrieval-side LLM calls will be split to a smaller model
- whether the evidence layer will later shrink to windows/paragraphs

Those decisions must be discussed separately before implementation.

## 8. Acceptance Standard

`Phase 4.10` closeout requires all of the following, and the current tree now satisfies the phase-local bar:

1. the known retrieval/context correctness bugs are fixed with tests
2. repeated same-source structure/PDF churn is reduced in the live run path
3. new parse jobs emit summary-backed routing assets again
4. SQLite + MySQL routing-index schema support is landed and reviewable
5. the current chat/compliance query path remains backward compatible while routing-index consumers are still deferred

Phase-local verification now exists through targeted suites covering:

- retrieval contract and runtime observation behavior
- same-run structure/PDF reuse behavior
- migration/bootstrap coverage for the routing-index schema
- parse success, failure, and same-version reparse behavior for routing-index rebuild

What is still not claimed here:

- this file does not claim the broader `Phase 4.7` / `Phase 4.9` / `Phase 4.10` real-runtime validation chain has already been rerun on the current stack
- that larger rerun remains a parent-stage closeout gate rather than a remaining `4.10` implementation gap

## 9. Gate Decision

- `Phase 4.10 baseline`: `LANDED`
- `Phase 4.10 closeout`: `Conditional GO`

Reason:

- the approved `code strategy 1` and `code strategy 2` batches are now landed in code
- targeted backend tests for `4.10-A` / `4.10-B` / `4.10-C` / `4.10-D` have been rerun on the current tree
- the remaining blocker is the broader parent-stage runtime rerun, not unfinished `Phase 4.10` implementation debt
- `code strategies 3/4/5/6` remain intentionally deferred until after this foundation work
