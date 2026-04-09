# Phase 3.3a: Multi-manual Query Feasibility

## Summary

This document records the **code-reality feasibility result** for true multi-manual querying in the current FastAPI service.

Verdict:

- **True multi-manual query is feasible only through service-layer orchestration**
- **Current PageIndex core is document-oriented, not native cross-document retrieval**
- **Current backend/frontend runtime still executes a skill run against exactly one resolved document**

This is therefore a **federated retrieval problem over multiple independent manuals**, not a unified-corpus retrieval problem.

Product conclusion:

- the product should introduce a first-class `knowledge_base` resource above documents
- KB is the reusable query scope
- federated multi-manual retrieval is the runtime execution model inside that KB

## Current Code Reality

### What already exists

- Skills can be linked to multiple `document_ids`
- Skill create/update paths persist multiple document bindings
- Skills UI allows selecting multiple documents for one skill
- `PageIndexClient` can manage multiple documents in a workspace

### What does not exist yet

- No runtime path executes retrieval over more than one document in a single skill run
- No backend response payload carries full citation provenance for multi-manual use
- No truthful multi-manual metrics exist today
- No session/run contract explicitly distinguishes single-manual vs multi-manual execution

## Current Code Gap

### 1. Skill runtime collapses multi-document config to one document

Current skill run routing logic resolves one document only:

- if request payload contains `document_id`, use it
- else use `skill.documents[0]`

Relevant code:

- `app/api/routers/chat.py`

Implication:

- Multi-document skill configuration exists in storage and UI, but not in execution semantics

### 2. Chat execution service is single-document end to end

Current execution service takes one `Document` and one `DocumentVersion` and persists one `run.document_id`.

Relevant code:

- `app/services/chat_service.py`

Implications:

- one run is modeled around one document
- `selected_sections_json` is populated from one selected node list
- `citations_json` is derived from one selected node list
- `ChatRun.document_id` cannot truthfully represent a real multi-manual run unless nullable or reinterpreted

### 3. PageIndex service wrapper is document-scoped

Current answer path accepts:

- one `pdf_path`
- one `structure`

and internally:

- selects nodes from one outline
- builds answer context from one PDF
- hardcodes `manual_count = 1`

Relevant code:

- `app/services/pageindex_service.py`

Implications:

- even the service wrapper around PageIndex is single-document
- multi-manual cannot be achieved by a trivial parameter expansion

### 4. Citation payload is insufficient for multi-manual semantics

Current citations contain only:

- `node_id`
- `title`
- `page_start`
- `page_end`
- `snippet_id`

Missing for multi-manual correctness:

- `document_id`
- `version_id`
- document label/name
- stable source identity across manuals

### 5. Frontend runtime also assumes one effective document

Current skill chat UI computes an `effectiveDocumentId` and submits that one document in the request.

Relevant code:

- `frontend/src/pages/SkillChatPage.tsx`

Implication:

- frontend behavior matches backend single-document execution and would need narrow adjustments if/when real multi-manual execution is added

## Feasibility Verdict

### Verdict

**Feasible, but only by orchestration in service layer.**

### Why PageIndex core is not native multi-manual retrieval

Current PageIndex core/client can hold many documents, but retrieval primitives are document-specific:

- `get_document(doc_id)`
- `get_document_structure(doc_id)`
- `get_page_content(doc_id, pages)`

There is no current core API that:

- ranks nodes across multiple documents in one call
- builds one shared cross-document outline
- returns one federated relevance ordering across manuals
- produces cross-document provenance automatically

So the correct interpretation is:

- **PageIndex core provides single-document retrieval primitives**
- **service layer must compose those primitives for multi-manual behavior**

### Product interpretation

If Phase 3 wants real “query across one or more manuals”, the product contract must explicitly describe that result as:

- one query
- multiple manual fan-out
- merged evidence set
- single final answer with per-citation provenance

It must not imply that PageIndex core itself is a native unified multi-manual retriever.

It also should not keep raw document lists as the long-term product abstraction. The better product layer is:

- `knowledge_base`
  - contains many documents
  - controls enable/disable and pinned-version policy
  - becomes the binding target for skills and compliance APIs

## Feasible Options

## Option A: Fan-out Per Document Then Merge/Rerank

### Execution model

1. Resolve full manual set from skill-linked `document_ids`
2. Resolve one active `version_id` per document
3. Rewrite query once from session history
4. For each document:
   - load parsed structure
   - select local top nodes
   - attach `document_id` and `version_id`
5. Merge all local candidates into one global candidate pool
6. Apply lightweight global rerank/merge
7. Build one bounded final context from top merged evidence
8. Generate one final answer

### Feasibility

- **High**
- Requires no PageIndex core changes
- Can be implemented entirely in `chat_service` and `pageindex_service` orchestration layer

### Citations impact

- Strongest provenance model
- Each citation can preserve source manual identity from first retrieval step onward
- Lowest risk of citation/source ambiguity

### Latency impact

- Higher than single-document query
- Roughly scales with number of manuals
- Can be reduced through parallel per-document retrieval

### Token impact

- Query rewrite remains one call
- Outline selection cost repeats per document
- Final generation remains one answer call
- Token cost is moderate and controllable by per-doc and global caps

### Session history impact

- Cleanest model
- One shared session history
- One shared rewritten query reused across all manuals

### Metrics impact

Metrics can remain truthful with additive fields such as:

- `manual_count`
- `documents_considered`
- `documents_with_hits`
- `retrieval_fanout_ms`
- `merge_rerank_ms`
- `context_build_ms`
- `global_selected_section_count`

### Assessment

- **Recommended**

## Option B: Merged Synthetic Outline / Federated Pseudo-Document

### Execution model

1. Build a synthetic combined outline by stitching all manual outlines together
2. Prefix or namespace node identifiers by document/version
3. Run one selector over the synthetic outline
4. Fetch page content from source manuals for selected synthetic nodes
5. Generate one final answer

### Feasibility

- **Medium**
- Still not native PageIndex support
- Service layer would be inventing a pseudo-document abstraction

### Citations impact

- Can work if source identity is carefully namespaced
- Higher risk of citation/source regression if node ids collide or synthetic structure loses manual boundaries

### Latency impact

- Potentially lower selector latency than per-doc fan-out
- But prompt size may increase sharply for large manual sets

### Token impact

- Highest risk among the options
- Combined outline can become too large quickly
- Retrieval quality can degrade once outline prompt becomes crowded

### Session history impact

- Shared history model is still simple
- But rewrite/selection quality may drop because retrieval target becomes an oversized synthetic outline

### Metrics impact

- Harder to explain truthfully
- One selector pass hides which manuals were genuinely considered or had hits

### Assessment

- **Technically possible**
- **Not recommended for v1**

## Option C: Narrow Product Semantics and Keep Runtime Single-Document

### Execution model

- Multi-document skill binding remains configuration-only
- Actual run must either:
  - require explicit `document_id`, or
  - continue defaulting to the first linked document

### Feasibility

- **Trivial**

### Citations impact

- No change

### Latency impact

- No change

### Token impact

- No change

### Session history impact

- No change

### Metrics impact

- No change

### Assessment

- Operationally safe
- Product-semantic downgrade
- Preserves the current misleading gap between configuration and execution
- **Not recommended unless Phase 3 scope must be explicitly reduced**

## Recommended Execution Model

Adopt **Option A: fan-out per document, merge/rerank globally, answer once from bounded merged evidence**.

### Why this is the recommended path

- It matches current architectural reality
- It avoids risky PageIndex core changes
- It preserves citation provenance best
- It keeps one coherent session and one final answer
- It allows explicit, truthful API semantics for federated manual retrieval

### Why this is preferable to synthetic merged outline

- Lower provenance risk
- Lower prompt bloat risk
- Easier debugging and metrics
- Easier to explain to API consumers
- Fits naturally under a KB abstraction without requiring deep core changes

### Why this is preferable to narrowing semantics

- Meets Phase 3 product direction
- Removes the current “config says multi-manual, runtime is single-manual” mismatch

## Recommended Constraints for V1

- Cap manuals per run to a small bounded value, such as 3 to 5
- Cap per-document retrieval candidates, such as top 3
- Cap globally merged evidence, such as 6 to 8 sections
- Apply `max_context_pages` and `max_context_tokens` after global merge, not only inside one document
- Use one shared rewritten query for the full run
- Preserve all provenance in `selected_sections_json`, `citations_json`, and `execution_context_json`

## Citation Payload Requirement

For any multi-manual-capable result, each citation payload should carry at minimum:

- `document_id`
- `version_id`
- `node_id`
- `page_start`
- `page_end`

Recommended minimum response shape:

```json
{
  "document_id": "doc_xxx",
  "version_id": "ver_xxx",
  "node_id": "0080",
  "page_start": 353,
  "page_end": 360,
  "title": "6.9 特殊机场和特殊航路",
  "snippet_id": "doc_xxx:ver_xxx:0080"
}
```

Recommended extended shape:

## Product Model Follow-Up

The feasibility result should now be interpreted as:

- `knowledge_base` is the first-class product resource
- federated fan-out is the recommended V1 retrieval implementation inside one KB
- deeper PageIndex core evolution is optional later work, not a prerequisite for Phase 3

```json
{
  "document_id": "doc_xxx",
  "version_id": "ver_xxx",
  "node_id": "0080",
  "page_start": 353,
  "page_end": 360,
  "title": "6.9 特殊机场和特殊航路",
  "snippet_id": "doc_xxx:ver_xxx:0080",
  "document_name": "AIP Manual 2025",
  "score": 0.84,
  "rank": 2,
  "source_type": "pdf_section"
}
```

## API / Payload Implications

For a future multi-manual skill run response, the backend should at minimum expose:

### Top-level run semantics

- `document_id` may be `null` for true multi-manual runs
- single-document direct ask can keep current semantics

### `execution_context.retrieval`

Should add:

- `mode`: `single_document` or `multi_document_fanout`
- `document_ids`
- `version_ids`
- `documents_considered`
- `documents_with_hits`
- `per_document_top_k`
- `global_top_k`

### `selected_sections`

Should carry:

- `document_id`
- `version_id`
- `node_id`
- `title`
- `page_start` / `page_end`

### `citations`

Should carry at least the required citation payload described above

## Metrics Implications

Current metrics are not truthful for multi-manual scenarios because `manual_count` is fixed at `1`.

For federated multi-manual retrieval, metrics should distinguish:

- how many manuals were in scope
- how many manuals produced hits
- how long fan-out retrieval took
- how long merge/rerank took
- how much final context was built

Recommended metrics fields:

- `manual_count`
- `documents_considered`
- `documents_with_hits`
- `retrieval_fanout_ms`
- `merge_rerank_ms`
- `context_build_ms`
- `global_selected_section_count`

## Session History Implications

For the recommended model:

- session remains one logical conversation
- history rewrite runs once
- rewritten query is reused across all manuals

This is the cleanest behavioral model and avoids per-document rewrite divergence.

## Non-goals for This Phase 3.3a Feasibility Spike

- No PageIndex core redesign
- No new native manual-set storage resource
- No claim that current core supports unified cross-document retrieval
- No product promise of conflict resolution beyond surfaced evidence and citations

## Final Recommendation

### Recommended

**Proceed with service-layer federated retrieval: fan-out per document, merge/rerank globally, then generate one answer from bounded merged evidence.**

### Explicitly not recommended for v1

- synthetic merged outline as the default execution path
- continuing to expose multi-document skill config while silently running first-document-only execution

### Final feasibility statement

The current codebase supports **future true multi-manual query only through orchestration in the FastAPI service layer**. The present implementation is **not yet multi-manual at runtime**, and any Phase 3 API semantics must say so explicitly until the federated execution path is actually implemented.
