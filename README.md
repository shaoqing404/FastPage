# PageIndex Service

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-00a393.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED.svg)](https://www.docker.com/)

PageIndex Service is an internal-document search and research console built around the open-source [PageIndex](https://github.com/VectifyAI/PageIndex) framework.

It is designed for enterprise knowledge bases where documents are long, structured, and operationally important: manuals, policies, reports, standards, compliance material, and other source-of-truth files.

The project has two complementary retrieval modes:

- **Fast Search**: low-latency section and node search for explicit facts, definitions, requirements, numeric lookups, and obvious chapter/section questions.
- **DeepResearch**: the original PageIndex reasoning path for multi-step, cross-section, official-source, and evidence-complete answers.

Fast Search is the main speed-oriented product surface. DeepResearch remains the accuracy-first path when a question needs broader reasoning or complete evidence expansion.

## What It Does

1. **Search long structured documents quickly**
   Fast Search returns ranked document sections in roughly sub-second to low-second latency on validated Chinese manual cohorts, with `node_top_k` configurable by the user.

2. **Keep the accurate research path available**
   DeepResearch keeps the original outline reasoning and evidence expansion path for cross-chapter questions, compliance-style decisions, and official-answer workflows.

3. **Manage documents and knowledge bases**
   The console supports document upload, parsing, versioning, knowledge-base binding, and skill configuration.

4. **Run skill chat and compliance jobs**
   Skills can bind to knowledge bases and run asynchronous chat/research tasks. Compliance runs use the same worker and observability foundation.

5. **Deploy inside enterprise environments**
   The service supports MySQL, Redis, MinIO/S3-compatible storage, queue-backed workers, workspace isolation, and private-provider endpoints.

6. **Operate with concurrency and observability**
   Workers run through Redis queues with memory guardrails, lifecycle controls, and runtime observation streams for long-running jobs.

## Fast Search vs DeepResearch

Use **Fast Search** when the user asks for a concrete section, fact, definition, number, requirement, or obvious topic:

- "特殊机场有哪些？"
- "厦门高崎机场有什么特殊规定？"
- "某条运行限制在哪里？"

Fast Search returns node cards: section title, page range, score, summary/snippet, active backend, and fallback information.

Use **DeepResearch** when the answer needs multiple sections or official reasoning:

- "雨夜能否降落高崎机场？"
- "这些材料是否足以支持统一结论？"
- "请给出完整官方依据。"

DeepResearch is slower because it performs structured reasoning and evidence expansion. That is expected. The product boundary is intentional: fast for direct retrieval, deep for complete reasoning.

## Deployment Model

Recommended production deployment uses the complete component stack:

- FastAPI backend
- React/Vite frontend console
- MySQL for persistent application state
- Redis for queues and worker coordination
- MinIO or S3-compatible storage for documents and artifacts
- Elasticsearch 8.x as the required B4.2 runtime search index
- OpenAI-compatible LLM, rerank, and embedding providers

SQLite/local mode exists for development, but it is not the recommended production mode.

## Quick Start

Commands in this section assume you start from the repository root.

### 1. Configure the environment

For Docker deployment:

```bash
cd docker
cp .env.example .env
```

Set the required secrets and provider values:

```env
APP_ENV=prod
API_HOST=0.0.0.0
API_PORT=22223

ADMIN_USERNAME=admin
ADMIN_PASSWORD=strong-admin-password
SECRET_KEY=long-random-secret-key

DATABASE_MODE=mysql
MYSQL_HOST=mysql
MYSQL_PORT=3306
MYSQL_DATABASE=pageindex
MYSQL_USER=pageindex
MYSQL_PASSWORD=change-me

TASK_QUEUE_BACKEND=redis
REDIS_HOST=redis
REDIS_PORT=6379

STORAGE_BACKEND=minio
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minio
MINIO_SECRET_KEY=change-me
MINIO_BUCKET=pageindex

LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key
```

### 2. Configure rerank and embedding providers

Rerank is strongly recommended for DeepResearch quality:

```env
SYSTEM_RERANK_ENABLED=true
SYSTEM_RERANK_PROVIDER_TYPE=openai_compatible
SYSTEM_RERANK_BASE_URL=https://api.your-rerank-provider.com/v1
SYSTEM_RERANK_API_KEY=sk-your-rerank-key
SYSTEM_RERANK_MODEL=bge-reranker-v2-m3
```

Embedding is required for dense Fast Search and ES-backed acceleration:

```env
SYSTEM_EMBEDDING_ENABLED=true
SYSTEM_EMBEDDING_PROVIDER_TYPE=openai_compatible
SYSTEM_EMBEDDING_BASE_URL=https://api.your-embedding-provider.com/v1
SYSTEM_EMBEDDING_API_KEY=sk-your-embedding-key
SYSTEM_EMBEDDING_MODEL=text-embedding-v4
SYSTEM_EMBEDDING_BATCH_SIZE=10

ROUTING_EMBEDDINGS_BUILD_MODE=enabled
```

`SYSTEM_EMBEDDING_BATCH_SIZE=10` is a conservative default for OpenAI-compatible providers with small batch limits.

### 3. Configure Elasticsearch for B4.2 runtime search

Starting with `B4.2`, Elasticsearch is the required runtime search index for Fast Search and DeepResearch context retrieval. ES stores node metadata, searchable `section_text` / page-text fields, lexical fields, embedding vectors, `routing_index_version`, and document/version/tenant metadata where available.

```env
ROUTING_NODE_ES_ENABLED=true
ROUTING_NODE_ES_HOST=127.0.0.1
ROUTING_NODE_ES_PORT=9200
ROUTING_NODE_ES_USER=elastic
ROUTING_NODE_ES_PASSWORD=change-me
ROUTING_NODE_ES_USE_SSL=false
ROUTING_NODE_ES_INDEX_PREFIX=pageindex-node-embeddings
```

If ES is disabled, unavailable, missing an index, stale, or lacks `section_text`, runtime search reports `data_not_ready` / degraded readiness. It does not silently fall back to local embedding artifact exact scan as a production backend.

Runtime PDF extraction is disabled by default and is only allowed as explicit debug / emergency fallback:

```env
DEEPRESEARCH_RUNTIME_PDF_FALLBACK_ENABLED=false
```

Existing local embedding artifact bundles and exact-scan code are legacy transitional infrastructure. They may be used for migration, diagnostics, and historical B2/B2.8 validation, but new runtime product features must not depend on artifact exact scan. Use the maintenance CLI to seed ES from known legacy bundles when needed:

```bash
uv run python scripts/phase47/node_embedding_es_maintenance.py --action check

# Dry-run a known local bundle file.
uv run python scripts/phase47/node_embedding_es_maintenance.py \
  --action sync \
  --dry-run \
  --bundle-paths '["/absolute/path/to/bundle.json"]'

# Real sync: omit --dry-run.
uv run python scripts/phase47/node_embedding_es_maintenance.py \
  --action sync \
  --bundle-paths '["/absolute/path/to/bundle.json"]'
```

For a controlled end-to-end check against the configured DB, object storage, and ES cluster, run:

```bash
uv run python scripts/phase47/es_full_validation.py
```

That validation script performs real ES writes when ES is enabled and a bundle is found.

### 4. Start the backend stack

```bash
cd docker
./start.sh
```

The API runs at `http://127.0.0.1:22223` by default.

### 5. Start the frontend

```bash
cd frontend
npm install
VITE_API_BASE_URL=http://127.0.0.1:22223/api/v1 npm run dev
```

Open `http://localhost:5173`.

## Using the Console

1. Upload and parse documents from **Documents**.
2. Create a **Knowledge Base** and enable the target documents.
3. Create or open a **Skill** bound to that knowledge base.
4. Use **Fast Search** for direct section lookup.
5. Use **DeepResearch** in Skill Chat for long-form answers and cross-section reasoning.

Fast Search is also available as a standalone console page for quick document lookup and debugging.

## Important Environment Variables

Core:

- `APP_ENV`
- `API_HOST`
- `API_PORT`
- `SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

Runtime services:

- `DATABASE_MODE`
- `DATABASE_URL` expert override
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_DATABASE`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `TASK_QUEUE_BACKEND`
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` / `REDIS_DB`
- `STORAGE_BACKEND`

Storage:

- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`
- `MINIO_PREFIX_PATH`
- `MINIO_SECURE`

Model providers:

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `SYSTEM_RERANK_ENABLED`
- `SYSTEM_RERANK_BASE_URL`
- `SYSTEM_RERANK_API_KEY`
- `SYSTEM_RERANK_MODEL`
- `SYSTEM_EMBEDDING_ENABLED`
- `SYSTEM_EMBEDDING_BASE_URL`
- `SYSTEM_EMBEDDING_API_KEY`
- `SYSTEM_EMBEDDING_MODEL`
- `SYSTEM_EMBEDDING_BATCH_SIZE`

Routing and Fast Search:

- `ROUTING_ROUTE_DOCS_BUILD_MODE`
- `ROUTING_SYNTHETIC_QUERIES_BUILD_MODE`
- `ROUTING_EMBEDDINGS_BUILD_MODE`
- `ROUTING_NODE_ES_ENABLED`
- `ROUTING_NODE_ES_HOST`
- `ROUTING_NODE_ES_PORT`
- `ROUTING_NODE_ES_USER`
- `ROUTING_NODE_ES_PASSWORD`
- `ROUTING_NODE_ES_USE_SSL`
- `ROUTING_NODE_ES_URL`
- `ROUTING_NODE_ES_INDEX_PREFIX`
- `DEEPRESEARCH_RUNTIME_PDF_FALLBACK_ENABLED`

Worker and observability:

- `WORKER_PROCESS_COUNT`
- `WORKER_MAX_TASKS_PER_CHILD`
- `WORKER_MAX_RSS_MB`
- `WORKER_HEARTBEAT_INTERVAL_SECONDS`
- `WORKER_HEARTBEAT_TTL_SECONDS`
- `OBSERVATION_TEXT_MAX_CHARS`

## Engineering Notes For Agents

### Main backend modules

- `app/api/routers/search.py`: Fast Search API surface.
- `app/schemas/search.py`: Fast Search request/response contract.
- `app/services/node_shadow_service.py`: node corpus loading, scoring, Fast Search response assembly, and shadow evaluation.
- `app/services/node_embedding_service.py`: legacy embedding artifact bundles, provider batching, transitional artifact exact scan, and ES runtime search indexing helpers.
- `app/services/chat_service.py`: DeepResearch / skill chat runtime.
- `app/services/compliance_service.py`: async compliance runtime.
- `app/services/routing_consumer_service.py`: shared manual/routing helpers.

### Frontend modules

- `frontend/src/pages/FastSearchPage.tsx`: standalone Fast Search workspace.
- `frontend/src/pages/SkillChatPage.tsx`: Skill Chat with Fast Search / DeepResearch mode selection.
- `frontend/src/features/search/api.ts`: Fast Search API client.
- `frontend/src/components/search/FastSearchNodeList.tsx`: reusable node result cards.

### API sketch

Fast Search:

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

Response includes:

- `nodes`
- `latency_ms`
- `boundary_flags`
- `active_backend`
- `fallback_reason`
- `requested_dense_source`
- `dense_source`

DeepResearch / skill chat remains on the existing chat endpoints and SSE flow.

### B4.2 Fast Search backend rule

1. Use ES-backed node / section text / vector data when the target document version is indexed and fresh.
2. If ES is missing, stale, or lacks `section_text`, report `data_not_ready` / degraded readiness.
3. Do not use local embedding artifact exact scan as a production runtime fallback.
4. Runtime PDF extraction is debug / emergency only and does not satisfy B4.2 performance GO.

Search requests do not perform long-running ES sync. ES sync is handled by maintenance scripts and future operational surfaces.

### Validation and tests

Backend targeted tests:

```bash
uv run pytest tests/api/test_search.py
uv run python -m unittest tests.phase4.test_node_embedding_service tests.phase4.test_node_shadow_service tests.phase4.test_node_shadow_eval
```

Frontend build:

```bash
cd frontend
npm run build
```

ES maintenance and validation:

```bash
uv run python scripts/phase47/node_embedding_es_maintenance.py --action check
uv run python scripts/phase47/node_embedding_es_maintenance.py \
  --action sync \
  --dry-run \
  --bundle-paths '["/absolute/path/to/bundle.json"]'
uv run python scripts/phase47/es_full_validation.py
```

Real-manual Fast Search benchmark evidence is produced by:

```bash
uv run python scripts/phase47/real_manual_shadow_eval.py
```

## Open Source Note

This repository is derived from PageIndex under the [MIT license](LICENSE). It packages the upstream framework into an implementation-oriented service surface with enterprise deployment, observability, Fast Search, and DeepResearch workflows.
