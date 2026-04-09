# Phase 0.5: Stabilization And Service Shaping

## Goal

Phase 0.5 is the bridge between:

- `Phase 0` — a working single-user local FastAPI service
- `Phase 1/2` — a tenant-aware, provider-aware, chat-capable service

Its purpose is to stabilize the initial backend, remove the most dangerous product/contract mismatches, and prepare the codebase for real service deployment without pretending the system is already production-grade.

## Why This Phase Exists

During implementation, several changes were too important to postpone to a later “enhancement” phase:

- queue separation for parse jobs
- MySQL / Redis / MinIO wiring
- provider-aware execution
- better chat run tracing
- skill-level retrieval and generation settings
- preliminary session and execution context modeling

These do not fit cleanly inside the original `Phase 0` wording, but they also do not yet amount to a fully productized multi-tenant service.

So Phase 0.5 should be understood as:

- a stabilization phase
- a service-boundary clarification phase
- a contract-hardening phase

## What Phase 0.5 Covers

### 1. Service split

- API service and worker service are separated
- parse jobs can run through Redis-backed queue mode
- runtime now resembles a real service instead of a notebook/demo workflow

### 2. Storage and persistence abstraction

- local filesystem assumptions are wrapped behind storage services
- MySQL metadata and MinIO artifacts can be used
- Redis queue integration is available

### 3. Skill execution hardening

- skill request parameters are no longer “stored only”; they are applied during execution
- trace artifacts persist model request/response details
- runtime metrics and execution context are exposed for frontend consumption

### 4. Product mismatch discovery

Phase 0.5 also surfaced key product issues that were not obvious in the earlier backend-only framing:

- skill chat UI looked multi-turn while backend behavior was still single-turn
- provider selection and model selection needed clearer ownership
- session semantics needed explicit definition

These findings directly motivated the later Phase 2 chat/session work.

## Deliverables

Phase 0.5 should be considered complete when the following are true:

- API service and worker service can be run independently
- parse jobs are persisted and observable
- uploaded documents, structures, and traces can survive process restarts
- provider-aware skill execution is visible and traceable
- frontend can rely on run-level execution context instead of guessing runtime behavior

## Explicit Non-Goals

Phase 0.5 does **not** claim the system is already:

- fully multi-tenant as a product
- hardened for public internet exposure
- compliance-ready
- concurrency-safe for large-scale chat workloads
- a cleanly split OSS service product

Those belong to the next productization stage.

## Relationship To Later Phases

- `Phase 0` gave us a usable local service
- `Phase 0.5` made that service structurally credible
- `Phase 1` formalized external components and tenancy direction
- `Phase 2` completed provider/session/chat semantics
- `Phase 3` should focus on productization: security, concurrency, compliance API, multi-manual query, and open-source service framing
