# Phase 3.3: Knowledge Base and Multi-Manual Retrieval

## Goal

Introduce a formal `knowledge_base` layer between workspace and documents so that:

- documents are grouped into reusable tenant/workspace-scoped knowledge containers
- skills bind to a KB instead of binding directly to one PDF or a raw `document_ids` list
- multi-manual retrieval becomes a truthful runtime behavior rather than a configuration illusion

This document turns the feasibility result from [multi_manual_feasibility.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/multi_manual_feasibility.md) into a product model.

## Why KB Is The Right Product Abstraction

Current code has:

- `documents`
- `document_versions`
- `skills.document_ids`

Current code does **not** have:

- a first-class grouping resource above documents
- a truthful multi-document execution model
- a reusable resource that both skill chat and compliance APIs can target

If Phase 3 keeps only `document_ids` on `skills`, the product model stays fragmented:

- skills own one notion of document grouping
- compliance would need a second grouping concept such as `manual_set`
- runtime semantics remain easy to misstate

`knowledge_base` is a better first-class resource because it can unify:

- skills
- multi-manual chat
- compliance checks
- document enable/disable policy
- pinned-version policy
- future KB-level retrieval settings

## Product Model

Recommended hierarchy:

- `tenant`
- `workspace`
- `knowledge_base`
- `documents`
- `document_versions`

Interpretation:

- `tenant`: hard isolation boundary
- `workspace`: in-tenant collaboration/resource boundary
- `knowledge_base`: reusable query scope within one workspace
- `document`: one uploaded PDF/manual
- `document_version`: one concrete parseable revision

## Current-State Gap

### 1. Skills currently bind raw `document_ids`

Relevant code:

- [chat_skill.py](/Users/shaoqing/workspace/PageIndex/app/models/chat_skill.py)
- [skill_service.py](/Users/shaoqing/workspace/PageIndex/app/services/skill_service.py)
- [SkillsPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/SkillsPage.tsx)

This is enough for storage and UI, but not enough for a stable product model because:

- there is no reusable grouping resource
- the same document grouping cannot be shared cleanly by multiple skills and compliance flows
- document enablement and version resolution rules have nowhere to live

### 2. Runtime still collapses to one document

Relevant code:

- [chat.py](/Users/shaoqing/workspace/PageIndex/app/api/routers/chat.py)
- [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py)

The runtime currently selects one effective document even when a skill is linked to many.

### 3. PageIndex core remains a document index builder

Relevant code and analysis:

- [pageindex_service.py](/Users/shaoqing/workspace/PageIndex/app/services/pageindex_service.py)
- [multi_manual_feasibility.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/multi_manual_feasibility.md)

PageIndex core currently works best as:

- PDF -> structured tree
- document-scoped retrieval primitive

So KB should first be a **service/product layer abstraction**, not a required deep core rewrite.

## Resource Model

### `knowledge_bases`

Workspace-scoped grouping resource.

Core fields:

```json
{
  "id": "kb_123",
  "tenant_id": "tenant_123",
  "workspace_id": "ws_123",
  "name": "airport-ops-kb",
  "description": "Airport operations and company manual corpus",
  "status": "active",
  "retrieval_profile": {
    "mode": "federated_fanout",
    "per_document_top_k": 3,
    "global_top_k": 8
  },
  "created_by": "user_123",
  "created_at": "2026-04-07T12:00:00Z",
  "updated_at": "2026-04-07T12:00:00Z"
}
```

### `knowledge_base_documents`

Join resource defining which manuals participate in a KB and how they resolve at runtime.

Core fields:

```json
{
  "knowledge_base_id": "kb_123",
  "document_id": "doc_123",
  "pinned_version_id": "ver_456",
  "enabled": true,
  "label": "Company SOP",
  "sort_order": 10
}
```

Rules:

- one document may belong to many KBs within the same workspace or tenant policy
- one KB may contain many documents
- `enabled=false` excludes the document from runtime fan-out without removing membership
- `pinned_version_id=null` means resolve active version at execution time

### Skill binding

Recommended target model:

- `ChatSkill.knowledge_base_id`

Compatibility path:

- keep `document_ids` during migration
- forbid new “multi-doc but no KB” semantics once KB is introduced

## Runtime Model

### Recommended execution path for KB-backed skill/chat

1. Resolve `knowledge_base_id`
2. Load enabled KB documents
3. Resolve one effective version per document
4. Rewrite query once using session history
5. Run per-document retrieval
6. Merge/rerank globally
7. Build final bounded context
8. Generate one answer

This keeps the recommended feasibility approach:

- service-layer federation
- one final answer
- full provenance

### Why not deep-core-first

Deep PageIndex core changes may come later, but Phase 3 should not block on them because:

- KB as a product resource can be implemented without changing the core index builder
- current feasibility already supports a service-layer path
- product semantics become clean immediately even before core evolution

## KB And PageIndex Core Relationship

Short version:

- PageIndex core remains the document indexing primitive
- KB is the product/query abstraction added by the service

Recommended near-term split:

- core responsibility:
  - build document structure
  - expose document descriptions and node summaries
  - return page content and structure-level metadata
- service responsibility:
  - group documents into KBs
  - resolve enabled/pinned versions
  - perform federated multi-document retrieval
  - emit cross-document citations and metrics

## API Surface

Recommended endpoints:

- `GET /api/v1/workspaces/{workspace_id}/knowledge-bases`
- `POST /api/v1/workspaces/{workspace_id}/knowledge-bases`
- `GET /api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}`
- `PATCH /api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}`
- `PUT /api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}/documents`
- `POST /api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}/documents`
- `PATCH /api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}/documents/{document_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}/documents/{document_id}`

## Citation Contract

Any KB-backed multi-manual response must include at minimum:

- `knowledge_base_id`
- `document_id`
- `version_id`
- `node_id`
- `page_start`
- `page_end`

Recommended shape:

```json
{
  "knowledge_base_id": "kb_123",
  "document_id": "doc_123",
  "version_id": "ver_456",
  "node_id": "0080",
  "page_start": 353,
  "page_end": 360,
  "title": "6.9 特殊机场和特殊航路",
  "snippet_id": "kb_123:doc_123:ver_456:0080"
}
```

## Migration Plan

### Phase 3 migration target

1. add KB tables/resources
2. keep current documents and versions unchanged
3. add `knowledge_base_id` to skills
4. preserve `document_ids` only as a temporary compatibility layer
5. migrate existing single-doc skills:
   - either create one KB per skill
   - or create shared KBs where the grouping is obviously reusable

### Defer

- full PageIndex core `query_kb()` abstraction
- advanced KB-level prefiltering/index acceleration
- knowledge graph or vector overlay

## Acceptance Criteria

- KB exists as a first-class workspace-scoped resource
- one skill can bind one KB instead of raw `document_ids`
- KB can contain multiple enabled documents with optional pinned versions
- runtime semantics for KB-backed skills are truthful for both single-manual and multi-manual use
- no API contract pretends that a multi-doc skill silently runs only the first document
- citations carry complete provenance for KB-backed execution
