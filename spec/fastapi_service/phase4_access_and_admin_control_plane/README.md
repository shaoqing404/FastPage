# Phase 4: Access, Admin, and Pre-Phase5 Closeout

## Goal

`Phase 4` is the parent stage that turns the PageIndex service from:

- tenant/workspace-aware in model
- partially operable in control plane
- strong in core document / KB / skill / chat capability

into a system that is:

- operationally usable for real tenant/workspace management
- explicit in access control and scope boundaries
- ready to enter `Phase 5` governance work without still carrying major control-plane debt

This parent stage should be managed as:

- `Phase 4 baseline`
- `Phase 4.5 Closeout, Management, and Control`
- `Phase 4.6 Tenant Directory and Access Portrait`
- `Phase 4.7 Pre-Phase5 Release Hardening`
- `Phase 4.8 Test-Led Experience Stabilization`
- `Phase 4.9 Multi-Manual Runtime And Observability Closeout`
- `Phase 4.10 Routing Speed And Structure Foundation`
- `Phase 4.11 B-Stage Baseline And Phase 5 Entry`

`Phase 5` remains reserved for:

- audit platform
- governance
- export / import
- migration portability
- long-term platform operations

## Stage Boundary

### What must be true before Phase 5 starts

Before `Phase 5`, the service must not only have core product features such as:

- index / parse
- search / query
- knowledge bases
- skills
- skill chat
- multi-manual / compliance-oriented retrieval

It must also have a **real operational control plane** for:

- tenant visibility
- workspace visibility and switching
- user status and capability control
- membership-driven access resolution
- workspace lifecycle and management
- scope-safe resource ownership

In other words:

- `Phase 4.x` finishes product-operability
- `Phase 5` starts governance

### What Phase 4.x does not include

The following stay out of `Phase 4.x`:

- audit center / audit platform
- long-term governance workflows
- org tree / department tree / real team hierarchy
- heavy ACL platform
- quota / billing / chargeback
- policy engine
- export / import productization
- cross-instance migration tooling

## Current Code Reality

The current codebase now materially includes:

- `Phase 4.5` operational control-plane closure
- `Phase 4.6` tenant/workspace/user portrait surfaces
- `Phase 4.7` reset / hardening / validation assets and refreshed current-tree runtime evidence
- `Phase 4.8` provider/workspace uplift and follow-up frontend usability fixes
- `Phase 4.9` multi-manual runtime and observability closure
- `Phase 4.10` routing speed and structure foundation
- `Phase 4.11` B-stage runtime/product baseline and Phase 5 entry handoff

Current parent-stage blocker summary (`2026-04-30`):

- the phase4 spec/validation surface has been restored and re-aligned to the current chat-session contract
- local `Phase 4.7` harness contract checks pass again, and the current-tree runtime validation artifact is finalized
- the current frontend tree now passes `build`
- `Phase 4.9` runtime foundation is materially landed, but still awaiting final rerun-based hard closeout
- `Phase 4.10` routing speed / structure foundation is now materially landed at the code-and-targeted-test level
- `Phase 4.11` records the first archived 500Q Skills Chat baseline as `GO with follow-up`
- the remaining parent-stage work is now soak/regression evidence and Phase 5 entry optimization, not an open B-stage implementation blocker

That means:

- `Phase 4` is `Conditional GO`
- `Phase 5` is still `NO-GO`

## Structure

### Active closeout docs

- [phase4_master_stage_plan.md](phase4_master_stage_plan.md)
- [phase4_7_closeout_report.md](phase4_7_closeout_report.md)
- [phase4_8_test_led_experience_stabilization.md](phase4_8_test_led_experience_stabilization.md)
- [phase4_9_multi_manual_runtime_and_observability_closeout.md](phase4_9_multi_manual_runtime_and_observability_closeout.md)
- [phase4_10_routing_speed_and_structure_foundation.md](phase4_10_routing_speed_and_structure_foundation.md)
- [phase4_11_b_stage_baseline_and_phase5_entry.md](phase4_11_b_stage_baseline_and_phase5_entry.md)
- [fast_search_product_surface.md](fast_search_product_surface.md)
- [phase4_10_execution_prompts.md](phase4_10_execution_prompts.md)
- [phase4_closeout_status.md](phase4_closeout_status.md)

Historical design notes and earlier batch docs remain available in git history and can be restored if the closeout work needs them again.

### B4.2 Runtime Search Decision

Starting with `B4.2`, Elasticsearch is the required runtime search index for Fast Search and DeepResearch context retrieval.

Runtime indexed data must include node metadata, title / breadcrumb lexical fields, `section_text` / page-text searchable fields, embedding vectors, `routing_index_version`, document/version identifiers, and tenant/workspace metadata where available.

Artifact disposition:

- existing local embedding artifact bundle and exact-scan code is legacy transitional infrastructure
- migration scripts may read old artifacts to seed ES
- diagnostics and historical B2/B2.8 validation may continue to reference artifact exact scan
- new runtime product features must not depend on artifact exact scan
- artifact exact scan is not a production runtime fallback after `B4.2`

Runtime gates:

- missing ES index is `data_not_ready` / runtime `NO-GO`
- missing `section_text` is `data_not_ready` / runtime `NO-GO`
- stale routing-version data is degraded and must not be treated as fresh context
- runtime PDF extraction is disabled by default and only allowed as explicit debug / emergency fallback
- DeepResearch runtime PDF extraction does not count as performance GO

### Operator-doc handoff

Canonical `Phase 4.7` operator runbooks now live under:

- [docs/phase4_7/README.md](../../../docs/phase4_7/README.md)

The `spec/` tree remains the parent-stage design and gate record.

### Execution support

- [phase4_7_backend_validation.py](phase4_7_backend_validation.py)

## Recommended Sequence

1. Keep `Phase 4.5` at `Conditional GO`.
2. Keep `Phase 4.6` at `GO`.
3. Treat `Phase 4.7` as already `GO` on the current tree.
4. Keep `Phase 4.9` at `Conditional GO` until its final rerun artifact is refreshed.
5. Treat `Phase 4.10` as `Conditional GO` pending the broader parent-stage rerun.
6. Treat `Phase 4.11` as `GO with follow-up`.
7. Treat `Fast Search Product Surface` as the primary business landing path for direct manual Q&A.
8. Run the full 5000Q soak/regression during the May Day window.
9. Open `Phase 5.0` for retrieval parallelization, context compression, chain caching, and quality/cost tuning.

## Parent-stage Closeout Rule

`Phase 4` is not considered closed merely because the happy-path product works.

It is closed only when:

- control-plane behavior is explicit and operable
- access rules are membership-driven and explainable
- key runtime compatibility debt is reduced to controlled fallback only
- the environment can be reset and rebuilt reproducibly
- a full end-to-end verification chain passes on project-owned test data
