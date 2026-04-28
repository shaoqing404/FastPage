# Fast Search Product Surface

- Repository root: current PageIndex checkout
- Parent stage: `Phase 4 Access, Admin, and Pre-Phase5 Closeout`
- Status date: `2026-04-27`
- Current decision: `Fast Search product surface GO for scoped validation`

## 1. Product Intent

Fast Search exists to reduce the time needed to locate explicit sections inside long structured documents.

It is not a replacement for the original PageIndex reasoning path.

The product now has two retrieval modes:

- `Fast Search`: low-latency node retrieval for obvious section, fact, definition, numeric, and requirement questions.
- `DeepResearch`: the original reasoning / outline / evidence-expansion path for cross-section, multi-condition, compliance, and official-answer workflows.

The intended user-facing boundary is:

- Fast Search is the quick lookup surface.
- DeepResearch is the complete reasoning surface.

## 2. Why This Exists

The original PageIndex path is accurate but can be slow because it performs outline reasoning and evidence expansion.

The B-stage routing work showed that real Chinese operating-manual questions with explicit section signals can be served much faster through node search:

- real manual cohort: `results/questions.json` plus P0 questions
- default `node_top_k=10`
- Fast Search wall-clock p50 around `993ms`
- original retrieval p50 around `62452ms`
- paired p50 speedup around `59.8x`
- section-local questions hit at `@10` in the real manual cohort

The same diagnostics also showed that multi-node reasoning questions remain out of scope for Fast Search:

- "雨夜能否降落高崎机场？" requires special-airport, low-visibility, landing-minima, wet/contaminated runway, and crosswind evidence.
- node top-k retrieval alone does not provide complete evidence expansion for that class of question.

## 3. Scope

### In scope

- standalone Fast Search API
- standalone Fast Search console page
- Skill Chat mode switch between `Fast Search` and `DeepResearch`
- configurable `node_top_k`
- node-card result display
- backend diagnostics for active backend, degraded readiness, and fallback reason
- ES-required runtime search over indexed node text, section text, lexical fields, and embeddings

### Out of scope

- changing `chat_service.py` live retrieval behavior
- changing compliance retrieval
- changing the evidence layer
- changing SSE stream contracts
- automatic confidence routing
- replacing DeepResearch with Fast Search
- runtime artifact exact-scan fallback as a production backend

## 4. B4.2 Retrieval Model

Starting with `B4.2`, Elasticsearch is the required runtime search contract for Fast Search and DeepResearch context retrieval.

Runtime indexed data must include:

- node metadata
- title and breadcrumb lexical fields
- `section_text` and page-text searchable fields / metadata
- embedding vector
- `routing_index_version`
- `document_id`, `version_id`, and tenant/workspace metadata where available

Fast Search requires ES-ready node / `section_text` / vector index data. DeepResearch citation context should read from ES-backed indexed section text or page-text data, not runtime PDF extraction.

Missing ES index, ES search errors, missing `section_text`, or stale routing-version data are `data_not_ready` / degraded runtime states. They are not silent production fallbacks to local artifacts or PDF extraction.

Search requests do not perform long-running ES synchronization. Existing legacy artifacts may be used by migration or maintenance tooling to seed ES:

```bash
uv run python scripts/phase47/node_embedding_es_maintenance.py --action check
uv run python scripts/phase47/node_embedding_es_maintenance.py \
  --action sync \
  --dry-run \
  --bundle-paths '["/absolute/path/to/bundle.json"]'
uv run python scripts/phase47/node_embedding_es_maintenance.py \
  --action sync \
  --bundle-paths '["/absolute/path/to/bundle.json"]'
```

The direct maintenance CLI accepts explicit bundle files. `scripts/phase47/es_full_validation.py` is the current end-to-end validation script that discovers a DB/storage bundle and performs real ES writes when ES is enabled.

### Artifact disposition

The existing embedding artifact bundle and exact-scan code is legacy transitional infrastructure. It may remain temporarily for migration, diagnostics, and historical B2/B2.8 validation, but it is not maintained as a product backend after `B4.2`.

New runtime features must not depend on artifact exact scan. Future cleanup can remove artifact exact scan once ES build and backfill are stable.

## 5. API Contract

Endpoint:

```http
POST /api/v1/search/fast
```

Request:

```json
{
  "document_id": "document-id",
  "version_id": "version-id",
  "query": "特殊机场有哪些？",
  "node_top_k": 10,
  "include_snippets": true
}
```

Constraints:

- `node_top_k` defaults to `10`
- allowed range is `5` to `20`

Response includes:

```json
{
  "mode": "hybrid",
  "node_top_k": 10,
  "latency_ms": 123,
  "nodes": [
    {
      "node_id": "0080",
      "title": "6.9 特殊机场和特殊航路",
      "page_start": 353,
      "page_end": 360,
      "score": 0.95,
      "source": "document_routing_nodes",
      "snippet": "...",
      "summary": "..."
    }
  ],
  "boundary_flags": [],
  "fallback_recommendation": null,
  "active_backend": "es_shadow",
  "fallback_reason": null,
  "requested_dense_source": "es_shadow",
  "dense_source": "es_shadow"
}
```

`boundary_flags` are advisory. They do not automatically switch the request to DeepResearch.

## 6. Frontend Contract

Fast Search appears in two places:

- standalone `/search` page
- Skill Chat mode switch

Skill Chat behavior:

- `DeepResearch` remains the default mode.
- `Fast Search` calls `/api/v1/search/fast`.
- Fast Search does not create a chat run.
- Fast Search does not use SSE.
- Fast Search results render as node cards, not as assistant messages.
- complex-query flags display a recommendation to use DeepResearch.

The current implementation intentionally does not include full ES readiness / sync UX. A document can be parse-ready while ES is not synced; Fast Search should report `data_not_ready` / degraded readiness instead of using local artifact exact scan as a production fallback.

## 7. Environment

Embedding:

```env
SYSTEM_EMBEDDING_ENABLED=true
SYSTEM_EMBEDDING_PROVIDER_TYPE=openai_compatible
SYSTEM_EMBEDDING_BASE_URL=https://api.your-embedding-provider.com/v1
SYSTEM_EMBEDDING_API_KEY=sk-your-key
SYSTEM_EMBEDDING_MODEL=text-embedding-v4
SYSTEM_EMBEDDING_BATCH_SIZE=10
ROUTING_EMBEDDINGS_BUILD_MODE=enabled
```

ES:

```env
ROUTING_NODE_ES_ENABLED=true
ROUTING_NODE_ES_HOST=127.0.0.1
ROUTING_NODE_ES_PORT=9200
ROUTING_NODE_ES_USER=elastic
ROUTING_NODE_ES_PASSWORD=change-me
ROUTING_NODE_ES_USE_SSL=false
ROUTING_NODE_ES_INDEX_PREFIX=pageindex-node-embeddings
```

For B4.2 runtime validation, ES must be enabled and populated before Fast Search / DeepResearch runtime search can be considered GO. Example development environments may still leave ES disabled, but that state is not a production runtime fallback.

Runtime PDF extraction is disabled by default:

```env
DEEPRESEARCH_RUNTIME_PDF_FALLBACK_ENABLED=false
```

It may only be enabled as explicit debug / emergency fallback and does not count as a performance GO condition.

## 8. Validation

Required targeted backend tests:

```bash
uv run pytest tests/api/test_search.py
uv run python -m unittest tests.phase4.test_node_embedding_service tests.phase4.test_node_shadow_service tests.phase4.test_node_shadow_eval
```

Required frontend validation:

```bash
cd frontend
npm run build
```

Required ES validation for runtime GO:

```bash
uv run python scripts/phase47/node_embedding_es_maintenance.py --action check
uv run python scripts/phase47/node_embedding_es_maintenance.py \
  --action sync \
  --dry-run \
  --bundle-paths '["/absolute/path/to/bundle.json"]'
uv run python scripts/phase47/es_full_validation.py
```

## 9. Gate

Current gate:

- `Fast Search API surface`: `GO`
- `Fast Search standalone page`: `GO`
- `Skill Chat Fast Search entry`: `GO`
- `ES-backed runtime search readiness`: `NO-GO` when ES index is missing, stale, or lacks `section_text`
- `DeepResearch runtime context`: `NO-GO` when it requires runtime PDF extraction for production readiness
- `ES readiness / sync UX`: `DEFERRED`
- `Auto confidence routing`: `DEFERRED`

The scoped Fast Search product surface is ready for UI/API validation as a separate fast lookup path.

Runtime GO requires ES build/backfill to populate fresh indexed `section_text` / page-text metadata and embeddings for the target document versions. Artifact exact scan and runtime PDF extraction are legacy/debug paths and do not satisfy B4.2 runtime GO.
