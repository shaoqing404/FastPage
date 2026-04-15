# FastAPI Service Plan

This folder contains the staged plan for turning the current PageIndex workspace into a FastAPI-based service.

## Planning Rules

- Phase 0 optimizes for working functionality, not full production hardening.
- Security is intentionally simplified in Phase 0, but the data model and service boundaries should not block later multi-user and multi-tenant support.
- PDF parsing/indexing should reuse the current PageIndex code path where possible.
- Storage starts locally in Phase 0, then evolves to object storage and relational persistence in Phase 1.
- Frontend is out of scope for implementation right now, but backend contracts and handoff notes must be clear enough for a later Vite frontend build.

## Folder Layout

- [`phase0_init/README.md`](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase0_init/README.md)
- [`phase0_5_stabilization/README.md`](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase0_5_stabilization/README.md)
- [`phase1_enhancement/README.md`](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase1_enhancement/README.md)
- [`phase2_chat_app_extension/README.md`](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/README.md)
- [`phase3_service_productization/README.md`](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase3_service_productization/README.md)
- [`phase4_access_and_admin_control_plane/README.md`](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/README.md)
- [`shared/api_design.md`](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/shared/api_design.md)
- [`shared/data_model.md`](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/shared/data_model.md)
- [`shared/frontend_handoff_for_gemini.md`](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/shared/frontend_handoff_for_gemini.md)

## Current Recommendation

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
