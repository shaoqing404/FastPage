# Data Model Sketch

## Core Entities

### Tenant

- `id`
- `name`
- `status`
- `created_at`

Phase 0 note:

- seed one row: `tenant_default`

### User

- `id`
- `tenant_id`
- `username`
- `password_hash`
- `is_active`
- `created_at`

Phase 0 note:

- seed one row: `user_default`

### Document

Logical file identity across versions.

- `id`
- `tenant_id`
- `owner_user_id`
- `display_name`
- `source_filename`
- `active_version_id`
- `status`
- `created_at`
- `updated_at`

### DocumentVersion

- `id`
- `document_id`
- `version_no`
- `storage_path`
- `file_hash`
- `parse_status`
- `parsed_structure_path`
- `parse_error`
- `created_at`

### ParseJob

- `id`
- `tenant_id`
- `document_id`
- `version_id`
- `status`
- `current_step`
- `progress_percent`
- `started_at`
- `finished_at`
- `duration_ms`
- `error_message`

### ChatSkill

- `id`
- `tenant_id`
- `owner_user_id`
- `name`
- `description`
- `system_prompt`
- `document_scope_type`
- `model`
- `request_config_json`
- `is_active`
- `created_at`
- `updated_at`

Rule:

- `model` is a top-level field, for example `openai/qwen-plus`
- `request_config_json` stores only request parameters such as `temperature`, `reasoning`, token limits, retrieval flags, and similar options
- `request_config_json` must not store the model identifier

### ChatSkillDocument

- `skill_id`
- `document_id`

### ChatRun

- `id`
- `tenant_id`
- `user_id`
- `document_id`
- `skill_id`
- `model`
- `question`
- `answer`
- `status`
- `selected_sections_json`
- `metrics_json`
- `started_at`
- `finished_at`

## Design Constraints

- Use `tenant_id` from day one even in single-user mode.
- Treat `Document` and `DocumentVersion` separately from day one.
- Persist request config as JSON so model flags can evolve without frequent schema changes.
- Keep artifact paths abstract enough to swap local FS for MinIO later.
