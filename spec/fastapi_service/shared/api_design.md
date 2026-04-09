# API Design Sketch

## Auth

### `POST /api/v1/auth/login`

Phase 0 request:

```json
{
  "username": "admin",
  "password": "hardcoded-secret"
}
```

Phase 0 response:

```json
{
  "access_token": "session-or-token",
  "token_type": "bearer",
  "user": {
    "id": "user_default",
    "tenant_id": "tenant_default",
    "username": "admin"
  }
}
```

## Documents

### `POST /api/v1/documents/upload`

Multipart upload of PDF.

Response:

```json
{
  "document_id": "doc_xxx",
  "version_id": "ver_xxx",
  "status": "uploaded"
}
```

### `GET /api/v1/documents`

List logical documents.

### `GET /api/v1/documents/{document_id}`

Get logical document detail and active version.

### `GET /api/v1/documents/{document_id}/versions`

List versions for one logical document.

### `GET /api/v1/documents/{document_id}/versions/{version_id}`

Get detail for one specific version.

### `POST /api/v1/documents/{document_id}/parse`

Trigger parse for active or specified version.

### `POST /api/v1/documents/{document_id}/reparse`

Create a new parse job for the active version.

### `POST /api/v1/documents/{document_id}/versions/{version_id}/restore`

Mark a previous version as current.

### `GET /api/v1/documents/{document_id}/structure`

Return parsed structure for the active version.

### `DELETE /api/v1/documents/{document_id}`

Delete the logical document and all stored versions/artifacts.

## Skills

### `POST /api/v1/skills`

```json
{
  "name": "special-airports",
  "system_prompt": "Answer concisely from the selected manual.",
  "document_ids": ["doc_xxx"],
  "model": "openai/qwen-plus",
  "request_config": {
    "temperature": 0,
    "reasoning": {
      "enabled": false
    }
  }
}
```

### `GET /api/v1/skills`

### `GET /api/v1/skills/{skill_id}`

### `PATCH /api/v1/skills/{skill_id}`

### `DELETE /api/v1/skills/{skill_id}`

## Chat

### `POST /api/v1/chat/ask`

```json
{
  "question": "特殊机场有哪些",
  "document_id": "doc_xxx",
  "model": "openai/qwen-plus",
  "request_config": {
    "temperature": 0,
    "reasoning": {
      "enabled": false
    }
  }
}
```

### `POST /api/v1/chat/skills/{skill_id}/run`

```json
{
  "question": "特殊机场有哪些"
}
```

Response shape:

```json
{
  "run_id": "run_xxx",
  "status": "completed",
  "answer": "...",
  "selected_sections": [
    {
      "node_id": "0080",
      "title": "6.9 特殊机场和特殊航路",
      "start_index": 353,
      "end_index": 360
    }
  ],
  "metrics": {
    "retrieve_ms": 420,
    "answer_ms": 1830,
    "total_ms": 2250
  }
}
```

## Metrics

### `GET /api/v1/jobs`

List parse jobs.

Supported filters:

- `document_id`

### `GET /api/v1/jobs/{job_id}`

### `GET /api/v1/runs`

List chat/query runs.

Supported filters:

- `document_id`
- `skill_id`

### `GET /api/v1/runs/{run_id}`

### `GET /api/v1/metrics/overview`

Return lightweight dashboards for parse and query health.

## Auth Additional Endpoint

### `POST /api/v1/auth/logout`

Invalidate the current bearer token or session.
