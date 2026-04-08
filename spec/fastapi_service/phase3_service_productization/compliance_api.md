# Phase 3.4: Compliance API Contract

## Current-State Gap

This contract is based on current code reality, not on desired product wording alone.

### 1. Current chat runtime is still single-document

Current skill execution explicitly resolves exactly one document:

- if request payload carries `document_id`, use that document
- else fallback to `skill.documents[0]`

Relevant code:

- [chat.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/chat.py)

This means the current runtime semantics are:

- multi-document skill configuration exists
- execution still collapses to one effective document

That is incompatible with truthful compliance semantics and must not be reused as-is.

### 2. Current run model is chat-shaped, not compliance-shaped

Current run contract is centered on prose QA:

- `question`
- `answer`
- `selected_sections`
- `citations`
- `metrics`

Relevant code:

- [chat.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/chat.py)
- [chat.py](/Users/shaoqing/workspace/PageIndex/app/schemas/chat.py)
- [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py)
- [index.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/types/index.ts)

Missing machine-friendly compliance fields:

- `summary`
- `evidence[]`
- `gaps[]`
- `conflicts[]`
- `verdict`
- compliance-specific `execution_context`

### 3. Current citation payload is insufficient for multi-manual correctness

Current citations only include:

- `node_id`
- `title`
- `page_start`
- `page_end`
- `snippet_id`

Relevant code:

- [pageindex_service.py](/Users/shaoqing/workspace/PageIndex/app/services/pageindex_service.py)

This is not enough for federated multi-manual results. Compliance citations must carry at least:

- `document_id`
- `version_id`
- `node_id`
- `page_start`
- `page_end`

### 4. Current retrieval wrapper is document-oriented

Current PageIndex service wrapper accepts one PDF and one structure, then returns one answer path with `manual_count = 1`.

Relevant code:

- [pageindex_service.py](/Users/shaoqing/workspace/PageIndex/app/services/pageindex_service.py)
- [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py)

This confirms the Phase 3.3a feasibility result:

- multi-manual is not native PageIndex unified retrieval
- the viable model is service-layer federation:
  - per-document fan-out
  - global merge/rerank
  - one final answer

### 5. Current resource boundary does not yet expose workspace-scoped compliance resources

The product direction is that tenant and workspace become formal resource boundaries, but current code still has:

- tenant-aware resources
- no real `workspace_id` on chat/skill/run objects
- no KB-backed compliance resource model

Relevant code and spec:

- [tenant_and_workspace_model.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/tenant_and_workspace_model.md)
- [chat_run.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_run.py)
- [chat_skill.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_skill.py)

## API Goals

### Primary goal

Define a machine-friendly compliance API contract for single-manual and multi-manual federated analysis without pretending the current chat runtime already supports true cross-manual execution.

### Contract goals

1. Make compliance a first-class API surface, not just a prose chat wrapper.
2. Preserve strict tenant isolation and make workspace the explicit resource scope.
3. Build compliance on top of the KB model from [knowledge_base_and_multi_manual.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/knowledge_base_and_multi_manual.md).
4. Support both:
   - single-manual mode
   - multi-manual federated mode
5. Require full citation provenance in every evidence-bearing result.
6. Expose structured result fields suitable for frontend rendering, automation, and downstream machine processing.
7. Allow both reusable saved definitions and ad hoc execution.
8. Keep internal implementation free to reuse existing retrieval/chat service primitives where practical, but do not leak current chat contract limitations into the public API.

### Non-goals for this phase

1. Do not claim PageIndex core provides native unified multi-manual retrieval.
2. Do not preserve the current misleading semantic of “skill linked to many docs but runtime picks one doc”.
3. Do not make compliance depend on chat session UX semantics.
4. Do not require full backend implementation in this phase.

## Resource Model

## Resource decisions

### 1. `knowledge_bases` are the grouping resource

Compliance should target `knowledge_base_id`, not `manual_set_id`.

Reason:

- KB is now the shared product abstraction above documents
- both skills and compliance should target the same query scope concept
- introducing `manual_set` as a second first-class grouping resource would duplicate product semantics

### 2. `compliance_checks`

`compliance_checks` should be added as saved check definitions.

Reason:

- a compliance check is not only “ask a question”
- it usually includes instructions, expected output shape, verdict policy, and target manual scope
- saved definitions are useful for repeatable workflows and future automation

### 3. `compliance_runs`

`compliance_runs` should be added as execution instances.

Reason:

- execution lifecycle and result payload are materially different from the definition
- async execution, retry, audit, and polling all want a run resource
- current `chat_runs` cannot truthfully represent multi-manual federated execution without semantic breakage

## Resource definitions

### `compliance_check`

Saved definition of what to evaluate.

Core fields:

```json
{
  "id": "cc_123",
  "workspace_id": "ws_123",
  "name": "special-airport-rule-check",
  "description": "Check whether the requested procedure is compliant",
  "target": {
    "mode": "knowledge_base",
    "knowledge_base_id": "kb_123"
  },
  "query_template": "Assess whether the described operation is compliant.",
  "instructions": "Return verdict, conflicts, gaps, and evidence only from cited manuals.",
  "verdict_policy": {
    "allowed_values": ["pass", "fail", "inconclusive", "not_applicable"],
    "default_on_gap": "inconclusive"
  },
  "output_config": {
    "include_summary": true,
    "include_answer": true,
    "include_evidence": true,
    "include_gaps": true,
    "include_conflicts": true
  },
  "retrieval_config": {
    "per_document_top_k": 5,
    "global_top_k": 8,
    "selection_mode": "outline_llm",
    "max_context_pages": 20,
    "max_context_tokens": 12000
  },
  "generation_config": {
    "temperature": 0
  },
  "created_at": "2026-04-07T12:00:00Z",
  "updated_at": "2026-04-07T12:00:00Z"
}
```

### `compliance_run`

Execution instance with machine-friendly result.

Core fields:

```json
{
  "id": "cr_123",
  "workspace_id": "ws_123",
  "compliance_check_id": "cc_123",
  "knowledge_base_id": "kb_123",
  "status": "completed",
  "mode": "multi_manual_federated",
  "question": "Can a special-airport operation use procedure X under condition Y?",
  "summary": "The manuals do not fully support procedure X under condition Y.",
  "answer": "Verdict is fail because ...",
  "verdict": "fail",
  "confidence": 0.74,
  "citations": [],
  "evidence": [],
  "gaps": [],
  "conflicts": [],
  "execution_context": {},
  "metrics": {},
  "error": null,
  "created_at": "2026-04-07T12:00:00Z",
  "started_at": "2026-04-07T12:00:01Z",
  "finished_at": "2026-04-07T12:00:12Z"
}
```

## Endpoint And Schema Proposal

## Design choice: independent compliance endpoints

### Recommendation

Expose independent compliance endpoints.

Recommended external API surface:

- `knowledge_bases`
- `compliance_checks`
- `compliance_runs`

### Why not reuse `/chat/skills/{skill_id}/run` as the public contract

1. Current chat contract is prose-first, not compliance-first.
2. Current skill runtime collapses many documents to one document.
3. Current `chat_runs.document_id` and current citation schema do not truthfully model federated execution.
4. Compliance needs reusable machine-friendly artifacts, not only chat transcripts.

### Internal reuse boundary

Implementation may still internally reuse parts of:

- node selection
- query rewrite
- provider resolution
- final generation

Possible reusable code paths:

- [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py)
- [pageindex_service.py](/Users/shaoqing/workspace/PageIndex/app/services/pageindex_service.py)

But public API contract should be independent from current chat route and schema.

## URI structure

Because tenant remains implicit from auth and workspace becomes a formal boundary, the recommended path shape is:

- `/api/v1/workspaces/{workspace_id}/knowledge-bases`
- `/api/v1/workspaces/{workspace_id}/compliance-checks`
- `/api/v1/workspaces/{workspace_id}/compliance-runs`

This preserves tenant inference from auth while making workspace explicit in resource addressing.

## Execution modes

### Single-manual mode

Use when exactly one manual is resolved.

Contract value:

```json
{
  "mode": "single_manual"
}
```

Semantics:

- exactly one resolved `document_id`
- exactly one resolved `version_id`
- no per-document fan-out

### Multi-manual federated mode

Use when multiple manuals are resolved.

Contract value:

```json
{
  "mode": "multi_manual_federated"
}
```

Semantics:

- resolve one `knowledge_base_id`
- load enabled KB documents
- fan out retrieval per document
- merge/rerank globally
- answer once from bounded merged evidence

## Relationship To Skills

Recommended product relationship:

- `skill` is an interactive chat behavior bound to one `knowledge_base_id`
- `compliance_check` is a structured policy-analysis behavior bound to one `knowledge_base_id`

They may share retrieval primitives internally, but they should not share the same public run contract.

## Minimum Provenance Requirements

Every compliance result carrying evidence or citations must include:

- `knowledge_base_id`
- `document_id`
- `version_id`
- `node_id`
- `page_start`
- `page_end`

This requirement applies to both:

- `citations[]`
- `evidence[]`

- resolve one version per document
- run per-document retrieval fan-out
- merge/rerank globally
- generate one final result

This is the required truthful product wording for Phase 3.

## Manual set endpoints

### `POST /api/v1/workspaces/{workspace_id}/manual-sets`

Create a reusable manual set.

Request:

```json
{
  "name": "airport-ops-core",
  "description": "Core manuals for airport operations compliance",
  "manuals": [
    {
      "document_id": "doc_a",
      "pinned_version_id": "ver_a2",
      "label": "AIP China"
    },
    {
      "document_id": "doc_b",
      "pinned_version_id": null,
      "label": "Company SOP"
    }
  ],
  "resolution_policy": "pinned_or_active"
}
```

Response: `201 Created`

```json
{
  "id": "ms_123",
  "workspace_id": "ws_123",
  "name": "airport-ops-core",
  "description": "Core manuals for airport operations compliance",
  "manuals": [
    {
      "document_id": "doc_a",
      "pinned_version_id": "ver_a2",
      "label": "AIP China"
    },
    {
      "document_id": "doc_b",
      "pinned_version_id": null,
      "label": "Company SOP"
    }
  ],
  "resolution_policy": "pinned_or_active",
  "created_at": "2026-04-07T12:00:00Z",
  "updated_at": "2026-04-07T12:00:00Z"
}
```

### `GET /api/v1/workspaces/{workspace_id}/manual-sets`

List manual sets in the workspace.

### `GET /api/v1/workspaces/{workspace_id}/manual-sets/{manual_set_id}`

Get manual set detail.

### `PATCH /api/v1/workspaces/{workspace_id}/manual-sets/{manual_set_id}`

Update manual set membership or metadata.

### `DELETE /api/v1/workspaces/{workspace_id}/manual-sets/{manual_set_id}`

Delete manual set.

## Compliance check endpoints

### `POST /api/v1/workspaces/{workspace_id}/compliance-checks`

Create a saved compliance check definition.

Request:

```json
{
  "name": "special-airport-rule-check",
  "description": "Assess whether the operation is compliant",
  "target": {
    "mode": "manual_set",
    "manual_set_id": "ms_123"
  },
  "query_template": "Assess whether the described operation is compliant.",
  "instructions": "Return verdict, evidence, gaps, and conflicts using cited manuals only.",
  "verdict_policy": {
    "allowed_values": ["pass", "fail", "inconclusive", "not_applicable"],
    "default_on_gap": "inconclusive"
  },
  "retrieval_config": {
    "per_document_top_k": 5,
    "global_top_k": 8,
    "selection_mode": "outline_llm",
    "max_context_pages": 20,
    "max_context_tokens": 12000
  },
  "generation_config": {
    "temperature": 0
  },
  "output_config": {
    "include_summary": true,
    "include_answer": true,
    "include_evidence": true,
    "include_gaps": true,
    "include_conflicts": true
  }
}
```

### `GET /api/v1/workspaces/{workspace_id}/compliance-checks`

List compliance check definitions.

### `GET /api/v1/workspaces/{workspace_id}/compliance-checks/{check_id}`

Get compliance check detail.

### `PATCH /api/v1/workspaces/{workspace_id}/compliance-checks/{check_id}`

Update compliance check definition.

### `DELETE /api/v1/workspaces/{workspace_id}/compliance-checks/{check_id}`

Delete compliance check definition.

## Compliance run endpoints

### Recommended execution contract

Recommend `async-first` execution with polling as the baseline contract, plus optional SSE streaming.

Reason:

- Phase 3.2 already points toward background execution isolation
- federated multi-manual runs have higher latency variance
- async is the safer public contract for retries, queueing, and future worker execution

`sync` may be allowed as a best-effort mode for small single-manual checks, but should not be the default contract.

### `POST /api/v1/workspaces/{workspace_id}/compliance-runs`

Create and start an ad hoc compliance run.

Request:

```json
{
  "execution_mode": "async",
  "stream": false,
  "input": {
    "question": "Can a special-airport operation use procedure X under condition Y?",
    "facts": {
      "airport_type": "special",
      "procedure": "X",
      "condition": "Y"
    }
  },
  "target": {
    "mode": "manual_set",
    "manual_set_id": "ms_123"
  },
  "instructions": "Return a verdict with supporting evidence only from the manuals.",
  "retrieval_config": {
    "per_document_top_k": 5,
    "global_top_k": 8,
    "selection_mode": "outline_llm",
    "max_context_pages": 20,
    "max_context_tokens": 12000
  },
  "generation_config": {
    "temperature": 0
  }
}
```

Alternative target for direct single-manual mode:

```json
{
  "target": {
    "mode": "document",
    "document_id": "doc_a",
    "version_id": "ver_a2"
  }
}
```

Response when queued: `202 Accepted`

```json
{
  "id": "cr_123",
  "workspace_id": "ws_123",
  "compliance_check_id": null,
  "status": "queued",
  "mode": "multi_manual_federated",
  "summary": null,
  "answer": null,
  "verdict": null,
  "confidence": null,
  "citations": [],
  "evidence": [],
  "gaps": [],
  "conflicts": [],
  "execution_context": {
    "workspace_id": "ws_123",
    "target": {
      "requested_mode": "manual_set",
      "resolved_mode": "multi_manual_federated",
      "manual_set_id": "ms_123"
    }
  },
  "metrics": {},
  "error": null,
  "created_at": "2026-04-07T12:00:00Z",
  "started_at": null,
  "finished_at": null
}
```

Response when completed synchronously: `200 OK`

Return the full `compliance_run` payload.

### `POST /api/v1/workspaces/{workspace_id}/compliance-checks/{check_id}/runs`

Start a run from a saved compliance check definition.

Request:

```json
{
  "execution_mode": "async",
  "stream": false,
  "input": {
    "question": "Can a special-airport operation use procedure X under condition Y?",
    "facts": {
      "airport_type": "special",
      "procedure": "X",
      "condition": "Y"
    }
  }
}
```

### `GET /api/v1/workspaces/{workspace_id}/compliance-runs`

List runs.

Recommended filters:

- `status`
- `compliance_check_id`
- `manual_set_id`
- `mode`
- `created_after`
- `created_before`

### `GET /api/v1/workspaces/{workspace_id}/compliance-runs/{run_id}`

Get full run detail and result.

### `GET /api/v1/workspaces/{workspace_id}/compliance-runs/{run_id}/events`

Optional SSE endpoint for progressive status/result events.

Recommended event types:

- `status`
- `retrieval_started`
- `document_completed`
- `merge_completed`
- `answer_completed`
- `completed`
- `failed`

This SSE contract is optional in Phase 3.3b, but if exposed it should stream `compliance_run`-oriented events rather than chat tokens only.

## Core schema proposal

## `ComplianceRunStatus`

Recommended enum:

```json
[
  "accepted",
  "queued",
  "retrieving",
  "merging",
  "answering",
  "completed",
  "failed",
  "cancelled"
]
```

## `ComplianceVerdict`

Recommended enum:

```json
[
  "pass",
  "fail",
  "inconclusive",
  "not_applicable"
]
```

## `Citation`

This must carry full provenance.

```json
{
  "citation_id": "cit_1",
  "document_id": "doc_a",
  "version_id": "ver_a2",
  "node_id": "0080",
  "page_start": 353,
  "page_end": 360,
  "title": "6.9 特殊机场和特殊航路",
  "snippet_id": "doc_a:ver_a2:0080",
  "document_label": "AIP China",
  "version_label": "v2"
}
```

Required minimum:

- `document_id`
- `version_id`
- `node_id`
- `page_start`
- `page_end`

## `Evidence`

`evidence[]` is distinct from raw citations. It is the normalized fact layer used by verdict logic.

```json
{
  "evidence_id": "ev_1",
  "kind": "supporting",
  "statement": "Manual A requires condition Z before procedure X is allowed.",
  "citation_ids": ["cit_1"],
  "source_count": 1
}
```

Recommended `kind` values:

- `supporting`
- `contradicting`
- `context`

## `Gap`

`gaps[]` captures what the manuals do not establish.

```json
{
  "gap_id": "gap_1",
  "type": "missing_requirement",
  "statement": "No cited manual text confirms procedure X is allowed under condition Y.",
  "severity": "high",
  "related_citation_ids": []
}
```

Recommended `type` values:

- `missing_requirement`
- `missing_definition`
- `missing_scope_match`
- `insufficient_evidence`

## `Conflict`

`conflicts[]` captures cross-manual or intra-manual contradictions that matter to the verdict.

```json
{
  "conflict_id": "conf_1",
  "type": "cross_manual_conflict",
  "summary": "Manual A allows procedure X, while Manual B forbids it under the same condition.",
  "citation_ids": ["cit_1", "cit_2"],
  "resolution_status": "unresolved"
}
```

Recommended `type` values:

- `cross_manual_conflict`
- `version_conflict`
- `interpretation_conflict`

## `ExecutionContext`

`execution_context` should be explicit enough for debugging and UI display without exposing internal traces only.

```json
{
  "workspace_id": "ws_123",
  "target": {
    "requested_mode": "manual_set",
    "resolved_mode": "multi_manual_federated",
    "manual_set_id": "ms_123"
  },
  "resolved_manuals": [
    {
      "document_id": "doc_a",
      "version_id": "ver_a2",
      "label": "AIP China"
    },
    {
      "document_id": "doc_b",
      "version_id": "ver_b5",
      "label": "Company SOP"
    }
  ],
  "retrieval": {
    "per_document_top_k": 5,
    "global_top_k": 8,
    "selection_mode": "outline_llm",
    "documents_considered": 2,
    "documents_with_hits": 2
  },
  "merge": {
    "strategy": "global_rerank",
    "candidate_count": 10,
    "selected_citation_count": 4
  },
  "generation": {
    "provider_id": "provider_123",
    "model": "openai/qwen-plus",
    "temperature": 0
  }
}
```

Required minimum:

- `workspace_id`
- resolved execution `mode`
- resolved manuals with `document_id` and `version_id`

## `ComplianceRun`

Recommended response schema:

```json
{
  "id": "cr_123",
  "workspace_id": "ws_123",
  "compliance_check_id": "cc_123",
  "status": "completed",
  "mode": "multi_manual_federated",
  "question": "Can a special-airport operation use procedure X under condition Y?",
  "summary": "The manuals do not fully support the requested operation.",
  "answer": "Verdict is fail because the cited manuals either prohibit the operation or do not establish the required exception.",
  "verdict": "fail",
  "confidence": 0.74,
  "citations": [
    {
      "citation_id": "cit_1",
      "document_id": "doc_a",
      "version_id": "ver_a2",
      "node_id": "0080",
      "page_start": 353,
      "page_end": 360,
      "title": "6.9 特殊机场和特殊航路",
      "snippet_id": "doc_a:ver_a2:0080",
      "document_label": "AIP China",
      "version_label": "v2"
    }
  ],
  "evidence": [
    {
      "evidence_id": "ev_1",
      "kind": "supporting",
      "statement": "Manual A requires additional approval before procedure X may be used.",
      "citation_ids": ["cit_1"],
      "source_count": 1
    }
  ],
  "gaps": [
    {
      "gap_id": "gap_1",
      "type": "insufficient_evidence",
      "statement": "No cited manual confirms the requested exception for condition Y.",
      "severity": "high",
      "related_citation_ids": []
    }
  ],
  "conflicts": [],
  "execution_context": {
    "workspace_id": "ws_123",
    "target": {
      "requested_mode": "manual_set",
      "resolved_mode": "multi_manual_federated",
      "manual_set_id": "ms_123"
    },
    "resolved_manuals": [
      {
        "document_id": "doc_a",
        "version_id": "ver_a2",
        "label": "AIP China"
      },
      {
        "document_id": "doc_b",
        "version_id": "ver_b5",
        "label": "Company SOP"
      }
    ],
    "retrieval": {
      "per_document_top_k": 5,
      "global_top_k": 8,
      "selection_mode": "outline_llm",
      "documents_considered": 2,
      "documents_with_hits": 2
    },
    "merge": {
      "strategy": "global_rerank",
      "candidate_count": 10,
      "selected_citation_count": 4
    },
    "generation": {
      "provider_id": "provider_123",
      "model": "openai/qwen-plus",
      "temperature": 0
    }
  },
  "metrics": {
    "retrieve_ms": 820,
    "merge_ms": 110,
    "answer_ms": 1650,
    "total_ms": 2580,
    "manual_count": 2,
    "documents_considered": 2,
    "documents_with_hits": 2,
    "global_selected_section_count": 4,
    "input_tokens": 3200,
    "output_tokens": 480,
    "total_tokens": 3680
  },
  "error": null,
  "created_at": "2026-04-07T12:00:00Z",
  "started_at": "2026-04-07T12:00:01Z",
  "finished_at": "2026-04-07T12:00:12Z"
}
```

## Error model

Recommended HTTP and domain error handling:

### `400 Bad Request`

Use for malformed payloads or incompatible execution parameters.

Examples:

- invalid `target.mode`
- `per_document_top_k <= 0`
- both `manual_set_id` and `document_id` missing

### `404 Not Found`

Use when a workspace-scoped resource does not exist or is not visible in the caller's tenant/workspace scope.

Examples:

- workspace not found
- manual set not found
- compliance check not found
- run not found

### `409 Conflict`

Use for resource state conflicts.

Examples:

- referenced document has no queryable version
- manual set contains duplicate document bindings with incompatible version policy
- run cannot be started because referenced check is inactive

### `422 Unprocessable Entity`

Use when the request is syntactically valid but cannot produce a truthful compliance run.

Examples:

- target manual set resolves to zero manuals
- resolved version exists but `parse_status != index_ready`
- result contract requires federated mode but only one manual is permitted by policy

### `429 Too Many Requests`

Use for tenant/workspace concurrency limits and queue backpressure.

### `500 Internal Server Error`

Unexpected service error.

### `502 Bad Gateway`

Upstream LLM/provider failure when the service itself is healthy but the model call failed.

### Suggested error body

```json
{
  "error": {
    "code": "manual_not_queryable",
    "message": "Resolved document version is not ready for querying.",
    "details": {
      "document_id": "doc_a",
      "version_id": "ver_a2",
      "parse_status": "parsing"
    }
  }
}
```

Recommended stable `error.code` values:

- `workspace_not_found`
- `manual_set_not_found`
- `compliance_check_not_found`
- `compliance_run_not_found`
- `document_not_found`
- `version_not_found`
- `manual_not_queryable`
- `manual_set_empty`
- `invalid_target`
- `invalid_execution_mode`
- `run_conflict`
- `provider_unavailable`
- `queue_overloaded`

## Sync/Async execution model

### Recommended baseline

1. Public contract defaults to async.
2. `POST /compliance-runs` returns `202 Accepted` with run resource when queued.
3. Client polls `GET /compliance-runs/{run_id}` for status and final result.
4. Optional SSE endpoint streams status transitions and partial execution metadata.

### Allowed best-effort sync path

Allow `execution_mode = "sync"` only when:

- workspace policy permits it
- request scope is small enough
- service can complete within a bounded server timeout

If the service cannot complete synchronously, it should still be allowed to downgrade to async and return `202 Accepted` rather than fail artificially.

## Acceptance Criteria

## Contract acceptance

1. Compliance API is specified as independent endpoints, not as a thin prose wrapper over current chat endpoints.
2. The spec adds explicit workspace-scoped resources for:
   - `manual_sets`
   - `compliance_checks`
   - `compliance_runs`
3. The spec explicitly distinguishes:
   - `single_manual`
   - `multi_manual_federated`
4. The multi-manual contract explicitly states service-layer federation semantics:
   - per-document fan-out
   - global merge/rerank
   - one final answer
5. Result schema includes at least:
   - `status`
   - `answer`
   - `summary`
   - `citations[]`
   - `evidence[]`
   - `gaps[]`
   - `conflicts[]`
   - `confidence` or `verdict`
   - `execution_context`
6. Every citation in compliance result includes full provenance minimum:
   - `document_id`
   - `version_id`
   - `node_id`
   - `page_start`
   - `page_end`
7. Error model and sync/async execution model are both explicitly defined.

## Truthfulness acceptance

1. The spec does not claim PageIndex core provides native unified cross-manual retrieval.
2. The spec does not reuse current misleading “multi-document skill config but single-document runtime” semantics.
3. The recommended public API is truthful even if the backend later reuses existing internal retrieval/generation helpers.

## Minimum viable implementation acceptance

The eventual Phase 3 MVP can be considered acceptable if it supports:

1. Creating and reading workspace-scoped `manual_sets`.
2. Starting an ad hoc `compliance_run` against:
   - one explicit document/version
   - one manual set with federated retrieval
3. Polling run status until terminal state.
4. Returning a machine-friendly terminal payload with:
   - `status`
   - `summary`
   - `answer`
   - `verdict`
   - `citations`
   - `evidence`
   - `gaps`
   - `conflicts`
   - `execution_context`
5. Returning citation provenance for every cited section across all involved manuals.
6. Returning truthful metrics including `manual_count` greater than `1` for federated runs.
