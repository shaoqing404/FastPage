# FastAPI Service Plan

This folder contains the staged plan for turning the current PageIndex workspace into a FastAPI-based service.

## Planning Rules

- Phase 0 optimizes for working functionality, not full production hardening.
- Security is intentionally simplified in Phase 0, but the data model and service boundaries should not block later multi-user and multi-tenant support.
- PDF parsing/indexing should reuse the current PageIndex code path where possible.
- Storage starts locally in Phase 0, then evolves to object storage and relational persistence in Phase 1.
- Frontend is out of scope for implementation right now, but backend contracts and handoff notes must be clear enough for a later Vite frontend build.

## Working-Tree Layout

The current working tree restores the closeout-relevant stage docs first.

Current active entries:

- [`phase4_access_and_admin_control_plane/README.md`](phase4_access_and_admin_control_plane/README.md)
- [`phase4_access_and_admin_control_plane/phase4_closeout_status.md`](phase4_access_and_admin_control_plane/phase4_closeout_status.md)
- [`phase5_maintenance_and_audit_governance/README.md`](phase5_maintenance_and_audit_governance/README.md)

Historical phase0-phase3 and shared planning docs remain available in git history and can be restored if the closeout work needs them again.

## Current Phase Gate

As of `2026-04-21`, the parent-stage recommendation is:

- `Phase 4.5`: `Conditional GO`
- `Phase 4.6`: `GO`
- `Phase 4.7`: historical `GO`, but post-`4.8` runtime rerun still pending
- `Phase 4.8`: `NO-GO`
- `Phase 4`: `NO-GO`
- `Phase 5`: `NO-GO`

The current closeout tracker is:

- [`phase4_access_and_admin_control_plane/phase4_closeout_status.md`](phase4_access_and_admin_control_plane/phase4_closeout_status.md)

## Historical Foundation

Build Phase 0 first with:

- `FastAPI`
- `Pydantic`
- `SQLAlchemy` + `Alembic`
- `SQLite` for local metadata persistence
- local filesystem for uploaded PDFs, parsed outputs, versions, and logs
- background job execution in-process first

This keeps implementation small while preserving a clean migration path to:

- `MySQL`
- `MinIO`
- API key based access control
- tenant-scoped ownership and quotas
