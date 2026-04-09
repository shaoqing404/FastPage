# Phase 3.5: Foundational Capabilities

## Goal

Define the minimum hardening work required to make the current FastAPI service safe enough for production-style deployment and future public OSS service release, without redesigning the frontend and without attempting a full implementation in this phase.

This document is a service hardening audit plus a scoped spec. It is based on current code reality in:

- `/Users/shaoqing/workspace/PageIndex/app/main.py`
- `/Users/shaoqing/workspace/PageIndex/app/core/config.py`
- `/Users/shaoqing/workspace/PageIndex/app/core/auth.py`
- `/Users/shaoqing/workspace/PageIndex/app/core/bootstrap.py`
- `/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py`
- `/Users/shaoqing/workspace/PageIndex/app/services/storage_service.py`
- `/Users/shaoqing/workspace/PageIndex/app/services/document_service.py`
- `/Users/shaoqing/workspace/PageIndex/app/api/routers/documents.py`
- `/Users/shaoqing/workspace/PageIndex/docker/docker-compose.yml`
- `/Users/shaoqing/workspace/PageIndex/docker/.env.example`
- `/Users/shaoqing/workspace/PageIndex/frontend/src/lib/api/client.ts`

## Current Audit Summary

The service already has the rough boundaries of a deployable API, but several defaults are still operator-console grade rather than public-service grade.

Most important current gaps:

- CORS is permissive by default and combined with `allow_credentials=True`.
- Docker examples bind publicly by default with `0.0.0.0`.
- Provider `base_url` is accepted and later used for outbound probing without strong validation.
- Secrets still rely on weak or placeholder defaults and `SECRET_KEY` is overloaded for both JWT signing and provider-secret encryption.
- Upload only checks filename suffix; there is no request-size or file-size limit.
- Error handling is mostly ad hoc `HTTPException` strings with no stable service taxonomy.
- Schema evolution is still `Base.metadata.create_all()` plus startup patch logic, with no migration discipline.
- There is no explicit audit log for auth events, API key usage, provider secret changes, or admin actions.
- Deployment examples are not safe for OSS publication in current form.

## Non-Goals

- No frontend redesign.
- No broad auth model redesign beyond hardening boundaries already implied by current code.
- No full implementation of audit/event pipeline in this phase.
- No breaking API rewrite unless needed to stabilize error or security contracts.

## Must-Have

These items should be treated as blockers before presenting this repository as a public OSS service or recommending it for internet-exposed deployment.

### 1. Safer CORS defaults

Current state:

- `app/main.py` enables `CORSMiddleware` with `allow_credentials=True`, `allow_methods=["*"]`, and `allow_headers=["*"]`.
- `app/core/config.py` defaults `CORS_ALLOW_ORIGINS` to a long allowlist including `localhost`, `127.0.0.1`, `0.0.0.0`, and broad internal IP patterns via `CORS_ALLOW_ORIGIN_REGEX`.

Risk:

- Current defaults are acceptable for local LAN development, but too permissive for a service template.
- Credentialed cross-origin requests should not be paired with broad regex defaults in an OSS-facing baseline.

Spec:

- Introduce explicit runtime modes in `app/core/config.py`:
  - `APP_ENV=dev|test|prod`
  - prod default must not allow wildcard-like regex behavior.
- In `app/main.py`, keep CORS middleware but drive it from validated config:
  - prod default: no implicit origins; startup should fail if UI/browser auth is expected but origin config is empty.
  - dev default: allow existing localhost origins only.
  - remove `0.0.0.0` from origin defaults.
  - `CORS_ALLOW_ORIGIN_REGEX` should default to empty in prod-oriented config.
- Narrow methods/headers to the smallest set the current frontend needs, or keep broad values only in `dev`.

Minimal frontend support:

- No frontend redesign required.
- `frontend/src/lib/api/client.ts` may keep `VITE_API_BASE_URL` support; only document that browser deployments must set it explicitly for non-local environments.

### 2. Safe bind/listen defaults and deployment split

Current state:

- `docker/docker-compose.yml` runs uvicorn with `--host ${API_HOST:-0.0.0.0}`.
- `docker/.env.example` sets `API_HOST=0.0.0.0`.
- `frontend/src/lib/api/client.ts` infers API base from `window.location.hostname:22223`.

Risk:

- Public bind is the default even in the example runtime.
- This encourages accidental internet/LAN exposure before auth, CORS, and reverse-proxy assumptions are hardened.

Spec:

- Add `API_HOST` default split:
  - local/dev example: `127.0.0.1`
  - containerized reverse-proxy example: `0.0.0.0`, but only in a clearly labeled production sample.
- Replace the single Docker sample with two documented modes:
  - local single-host dev
  - behind-proxy deployment
- `docker/README.md` must state that direct public exposure of uvicorn is not the recommended deployment shape.
- Keep current frontend client behavior, but require `VITE_API_BASE_URL` in non-local deployments.

### 3. Provider `base_url` validation and outbound safety

Current state:

- `app/services/provider_service.py` persists arbitrary `payload.base_url`.
- `probe_provider_models()` constructs outbound `/models` requests directly from stored `base_url`.

Risk:

- This is an SSRF-class surface if exposed to untrusted tenants/operators.
- Scheme, host, path shape, loopback/internal targets, and credential-bearing URLs are not validated.

Spec:

- Add a provider URL validator in `app/services/provider_service.py` or a dedicated validation module:
  - allow only `http` and `https`.
  - reject embedded credentials in URL.
  - normalize trailing slash behavior.
  - reject obviously unsafe hosts in prod mode unless explicitly allowed by config:
    - `localhost`
    - `127.0.0.0/8`
    - link-local/private/internal CIDRs
    - container metadata IPs and similar reserved targets
- Add config gates in `app/core/config.py`:
  - `PROVIDER_URL_ALLOW_PRIVATE_NETS=false` by default in prod.
  - optional allowlist for trusted hostnames or suffixes.
- Probe requests should use the validated normalized URL, with clear timeout and sanitized error output.
- API responses must never echo decrypted secrets or raw upstream credential material.

### 4. Secret management baseline

Current state:

- `app/core/config.py` provides insecure defaults for `ADMIN_PASSWORD` and `SECRET_KEY`.
- `SECRET_KEY` is used for JWT signing and API key hashing salt and provider-secret encryption.
- `docker/.env.example` currently contains concrete database, Redis, and MinIO credentials and internal hostnames.

Risk:

- The current example file is not safe for OSS publication.
- One secret is serving too many roles.
- Weak defaults can silently ship into deployments.

Spec:

- In `app/core/config.py`, fail startup in prod when any of these are default/weak/empty:
  - `SECRET_KEY`
  - `ADMIN_PASSWORD`
  - provider env API key when system provider is enabled
- Split secret purposes:
  - `JWT_SECRET_KEY`
  - `ENCRYPTION_KEY` for provider/API-secret encryption
  - maintain compatibility fallback only for dev migration window
- Keep API key hashing independent from reversible encryption material.
- Replace `docker/.env.example` with placeholder-only values:
  - no real internal IPs
  - no real passwords
  - no `root` database user
- `config_spec.md` should be extended to describe secret classes and prod requirements.

### 5. Upload size and content limits

Current state:

- `app/services/document_service.py` only checks `file.filename.endswith(".pdf")`.
- `app/services/storage_service.py` streams uploads directly to disk/object storage.
- `app/api/routers/documents.py` accepts upload with no explicit size guard.

Risk:

- Oversized uploads can exhaust disk, temp space, object storage bandwidth, or API worker memory.
- Filename suffix is not a sufficient content check.

Spec:

- Add upload guard config in `app/core/config.py`:
  - `MAX_UPLOAD_BYTES`
  - optional `MAX_UPLOAD_PAGES` later, but byte-size is required first
- Enforce request/file size before persistence:
  - validate `Content-Length` when present
  - hard-stop while streaming if actual bytes exceed limit
- Validate PDF magic bytes in `app/services/document_service.py` before accepting as a PDF.
- Return a stable `413` error for payload-too-large cases.
- Document reverse-proxy/body-size alignment in `docker/README.md`.

### 6. Error taxonomy baseline

Current state:

- Errors are mostly raw `HTTPException(detail="...")` across routes and services.
- There is no stable machine-readable error code contract.

Risk:

- Clients cannot reliably distinguish auth failures, quota/limit failures, validation failures, provider failures, or transient upstream failures.
- Future OSS consumers will overfit to English strings.

Spec:

- Add a global error envelope in `app/main.py` via exception handlers.
- Introduce stable application error codes, for example:
  - `AUTH_INVALID_CREDENTIALS`
  - `AUTH_TOKEN_INVALID`
  - `AUTH_API_KEY_INVALID`
  - `PROVIDER_URL_INVALID`
  - `PROVIDER_PROBE_FAILED`
  - `UPLOAD_INVALID_FILE`
  - `UPLOAD_TOO_LARGE`
  - `RESOURCE_NOT_FOUND`
  - `CONFLICT_STATE`
  - `INTERNAL_ERROR`
- Keep HTTP status codes, but return a JSON shape like:
  - `error.code`
  - `error.message`
  - `error.request_id`
  - optional `error.details`
- Minimal frontend change only if current UI needs to read `error.detail` during transition. Backend can preserve `detail` alongside the new envelope for compatibility if needed.

### 7. Migration discipline beyond startup patching

Current state:

- `app/core/bootstrap.py` runs `Base.metadata.create_all()` and `_ensure_phase2_columns()` on startup.
- There is no Alembic directory or migration history in the repository.

Risk:

- Startup-time schema mutation is not safe enough for public deployments, repeated upgrades, or multi-instance rollouts.
- Schema state can drift across environments with no explicit version boundary.

Spec:

- Stop expanding the bootstrap patch pattern.
- Introduce migration discipline as a required capability before further productization:
  - add Alembic or equivalent migration system
  - record an initial baseline migration matching current schema
  - convert Phase 2 patch columns into formal migrations
- `app/core/bootstrap.py` should be reduced to bootstrap data creation only; schema mutation must move out of request-serving startup.
- Deployment docs must require migration execution before API startup.

### 8. Audit log for auth and high-risk admin actions

Current state:

- `app/core/auth.py` updates `last_used_at` for API keys, but there is no durable audit event stream.
- Provider create/update/delete and login/token events are not audit logged.

Risk:

- Security-sensitive actions cannot be reconstructed.
- Public service operators need at least a minimal audit trail.

Spec:

- Add a minimal audit event model and write path for:
  - login success/failure
  - token revocation
  - API key create/revoke/use
  - provider create/update/delete/probe
  - document upload/delete
- Keep this append-only and metadata-light for now.
- Required fields:
  - event id
  - timestamp
  - tenant id
  - actor type/id
  - action
  - target resource type/id
  - result
  - request id
- Do not log raw bearer tokens, API keys, or provider secrets.

### 9. OSS-safe deployment configuration

Current state:

- `docker/.env.example` is environment-specific rather than template-safe.
- `docker/Dockerfile` and compose setup are minimal but do not document prod assumptions.

Risk:

- The current Docker assets are too easy to misuse as if they were production-ready.

Spec:

- Replace current example secrets and addresses with safe placeholders.
- Add explicit deployment notes for:
  - reverse proxy / TLS termination expectation
  - persistent volume expectations
  - database and Redis externalization
  - body-size limits matching upload limits
  - migration step before app startup
- Keep Docker changes minimal; do not redesign the frontend or deployment stack in this phase.

## Should-Have

These items materially improve robustness and should land in the same productization wave if capacity permits, but they are not absolute blockers for the first OSS service cut if the must-have set is done well.

### 1. Request ID and structured logging

Current state:

- No request ID middleware or structured service log contract is visible in `app/main.py`.

Spec:

- Add request ID middleware in `app/main.py`.
- Include request ID in error envelope and audit events.
- Standardize JSON logs for request start/end, upstream provider probe failure, parse scheduling, and auth failures.

### 2. More explicit provider probe policy

Current state:

- `probe_provider_models()` reaches arbitrary `/models` candidates with a fixed timeout and stores discovered models.

Spec:

- Separate "save provider" from "probe provider" semantics in API docs and error codes.
- Add probe timeout and retry settings to `app/core/config.py`.
- Sanitize upstream bodies before surfacing them in `HTTPException.detail`.

### 3. Secret rotation and decryption-failure handling

Current state:

- Providers become undecryptable if `SECRET_KEY` changes.

Spec:

- Add a rotation path:
  - support current key plus optional previous key(s) for decrypt-only during migration window
  - provide a re-encrypt maintenance operation later
- In `provider_service.py`, map decryption failures to a stable secret-rotation error code, not only a free-form message.

### 4. Upload and storage hygiene

Current state:

- Upload path is fixed to `source.pdf`, which is good for path safety, but file dedupe and content inspection are minimal.

Spec:

- Record upload byte size and MIME sniff result on `DocumentVersion`.
- Ensure storage backends expose consistent failure classes for write/read/delete operations.
- Add cleanup policy documentation for temporary files in `storage_service.py` and container runtime.

### 5. Compatibility transition for frontend error handling

Current state:

- `frontend/src/lib/api/client.ts` only has generic 401 interception.

Spec:

- If new error envelope lands, keep `detail` compatibility during transition.
- Optional minimal client update:
  - read `error.code` for redirect/logout cases later
  - no page redesign or request-layer rewrite

## Later

These items are useful but should not block Phase 3.4 closure.

### 1. Full RBAC-oriented audit model

- Current service is still effectively single-admin plus tenant-aware schema.
- Rich authorization audit and policy-diff logs should wait for Phase 3.1 tenant/workspace evolution.

### 2. Advanced egress policy management

- Per-tenant outbound allowlists, DNS pinning, and proxy-controlled egress are valuable, but the immediate requirement is basic SSRF risk reduction for provider URLs.

### 3. End-user visible audit UI

- Audit retrieval endpoints and UI can wait.
- Phase 3.4 only needs event capture and operator-accessible storage.

### 4. Full content scanning and document security pipeline

- Antivirus scanning, PDF parser sandboxing, and page-count quotas are good next steps, but byte-size limits and signature validation are the minimum requirement now.

### 5. Deployment matrix expansion

- Helm, Kubernetes manifests, and multi-stage production image optimization are later concerns.
- Phase 3.4 only needs a safer baseline Docker story and explicit deployment assumptions.

## File-Oriented Change Map

The intended implementation surface for a later execution phase is:

- `app/main.py`
  - request ID middleware
  - unified exception handlers
  - environment-aware CORS wiring
- `app/core/config.py`
  - env mode split
  - validated CORS settings
  - bind/listen related config
  - upload limit config
  - provider outbound safety config
  - split secret config
- `app/core/auth.py`
  - audit hooks for login/token/API key events
  - stable auth error codes
  - secret split adoption
- `app/core/bootstrap.py`
  - remove schema patch growth
  - keep only bootstrap-data concerns
- `app/services/provider_service.py`
  - URL normalization/validation
  - probe safety and sanitized upstream error handling
  - provider event audit hooks
- `app/services/document_service.py`
  - PDF signature validation
  - upload byte-limit enforcement
  - stable upload error classes
- `app/services/storage_service.py`
  - streaming byte-count enforcement
  - storage error normalization
- `app/api/routers/documents.py`
  - preserve current API shape
  - only minimal support for size-limit/status-code behavior
- `docker/.env.example`
  - safe placeholders only
- `docker/docker-compose.yml`
  - safer dev defaults
  - clear separation from internet-facing deployment assumptions
- `docker/README.md`
  - migration, reverse proxy, TLS, upload/body-size notes
- `frontend/src/lib/api/client.ts`
  - optional compatibility-only changes for new error envelope or explicit API base documentation

## Priority Summary

### Must resolve before public OSS service positioning

- CORS hardening
- safer bind/listen defaults
- provider `base_url` validation and SSRF reduction
- secret management baseline
- upload size/content limits
- stable error taxonomy
- formal migration discipline
- audit log for auth and admin-risk actions
- OSS-safe deployment examples

### Can follow immediately after the first hardened cut

- request ID and structured logs
- secret rotation ergonomics
- richer storage/upload metadata
- limited frontend compatibility cleanup

### Can wait for later phases

- full audit UI
- advanced egress controls
- advanced document security scanning
- broader deployment packaging
