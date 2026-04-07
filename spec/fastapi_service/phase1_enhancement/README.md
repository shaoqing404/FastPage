# Phase 1: Enhancement

## Goal

Turn the Phase 0 single-user local service into a more complete backend with cleaner deployment boundaries and better performance.

## Planned Scope

### 1. Technical Stack Upgrades

Introduce:

- `MySQL` for durable relational metadata
- `MinIO` for object storage of PDFs, parsed artifacts, and exports
- optional queue or worker separation for parse jobs

Migration intent:

- replace local SQLite with MySQL
- replace local file artifact storage with MinIO
- keep storage and persistence interfaces stable so service code changes are limited

### 2. Multi-User and Multi-Tenant

Introduce:

- explicit users
- explicit tenants / workspaces
- API key based service access
- tenant-scoped documents, skills, jobs, and chat history

Rules:

- every mutable business object is tenant-owned
- document version restore and parse jobs must be tenant-scoped
- skills may later support shared/public visibility, but default to private per tenant

### API Key Management

Phase 1 adds tenant-scoped API keys for service-to-service or script-based access.

Required endpoints:

- `POST /api/v1/apikeys` — create key and return plaintext only once
- `GET /api/v1/apikeys` — list keys for current tenant without returning plaintext
- `DELETE /api/v1/apikeys/{key_id}` — revoke key

Authentication model in Phase 1:

- browser/session access continues to use `Authorization: Bearer <token>`
- service access may use `X-API-Key: <key>`
- protected endpoints support either bearer token or API key

Storage rules:

- store only hashed API keys
- store metadata such as `name`, `created_at`, `last_used_at`, `revoked_at`
- never store retrievable plaintext secrets after creation

### 3. Performance Optimization

Focus areas:

- cache parsed structures aggressively
- cache outline-first metadata
- reduce repeated PDF page extraction
- precompute page text materializations for hot documents
- add query-time tracing for section selection and answer generation
- optimize retrieval path for repeated skills and repeated documents

## Phase 1 Deliverables

- MySQL-backed metadata layer
- MinIO-backed artifact layer
- API keys and permission checks
- tenant-aware service architecture
- faster retrieval pipeline and better runtime observability

## Explicit Non-Goals

- full enterprise auth stack
- complicated quota / billing
- advanced RBAC
- distributed job orchestration unless Phase 0 throughput proves insufficient
