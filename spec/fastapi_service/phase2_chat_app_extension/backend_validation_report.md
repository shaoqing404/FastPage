# Phase 2 Backend Validation Report

This file is updated by running:

```bash
.venv/bin/python spec/fastapi_service/phase2_chat_app_extension/backend_validation.py
```

## Scope

- real provider direct ask
- real provider skill run
- answer marker and citations payload
- API key revoke negative path
- cross-tenant access negative path
- session message ordering baseline
- migration consistency baseline for empty schema and old schema patch-up

## Deferred

- high-concurrency 20~50 request smoke
- frontend parser/display validation for `answer_with_marker`
- full provider matrix beyond current OpenAI-compatible path

## Latest Result

Validation completed successfully with:

- real provider direct ask: passed
- real provider skill run: passed
- `answer_with_marker` marker presence: passed
- `citations` payload presence: passed
- API key revoke negative path: passed
- cross-tenant document access denial: passed
- session message ordering baseline: passed
- migration baseline on empty schema: passed
- migration patch baseline on old schema: passed

Captured run references:

- direct run id: `29c81d77-e6e7-4c5b-b6b7-7dea1b565c07`
- skill run id: `fa3194de-9e50-491a-a752-aca1fe681447`
- validation session id: `0676741d-4203-42f2-aea4-2a74793309a0`

Operational note:

- a stable `SECRET_KEY` is now required in runtime config for provider decryption, API key hashing, and JWT stability
- providers created before this fix with a random process-local secret may need to be recreated
