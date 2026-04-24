# Workspace Admin API

## Scope

This document defines the Phase 4 backend API surface for workspace administration.

It covers:

- workspace member management
- founder transfer
- invite management
- workspace archive
- visibility updates on KB and Skill resources
- workspace context switch

It does not cover:

- tenant lifecycle
- platform operator console
- purge/delete APIs

## Fixed Decisions

All frozen decisions from Phase 4 apply here and must not be reopened.

Particularly important for this API set:

- `workspace_memberships` is required
- founder is unique and transferable
- admin cannot manage other admin
- invite is email-based and bound to logged-in email acceptance
- archive only, no delete
- visibility never raises capability above membership role/override

## Workspace Members

### `GET /api/v1/workspaces/{workspace_id}/members`

Purpose:

- list workspace memberships

Allowed actors:

- founder
- admin
- future platform admin

Suggested response fields:

- `id`
- `workspace_id`
- `user_id`
- `email`
- `role`
- `status`
- `permissions_override`
- `created_at`
- `updated_at`

### `POST /api/v1/workspaces/{workspace_id}/members`

Purpose:

- directly add an already-existing user to a workspace

Recommended Phase 4 posture:

- optional
- may be supported for admin convenience
- invite flow remains the primary user-facing path

If implemented, allowed actors:

- founder
- admin
- future platform admin

Rules:

- actor must not create another `admin` unless actor is founder
- actor must not create `founder`

### `PATCH /api/v1/workspaces/{workspace_id}/members/{membership_id}`

Purpose:

- update role/status/override on workspace membership

Allowed actors:

- founder
- admin with restrictions
- future platform admin

Patchable fields:

- `role`
- `status`
- `permissions_override`

Rules:

- admin may update only `member` and `guest`
- admin may not promote to `admin`
- admin may not demote/remove any `admin`
- founder may manage all non-founder memberships
- founder changes on founder membership itself are only allowed through founder transfer flow

### `DELETE /api/v1/workspaces/{workspace_id}/members/{membership_id}`

Recommended semantics:

- soft remove membership
- set `status = removed`

Allowed actors:

- founder
- admin with same restrictions as patch
- future platform admin

Rules:

- admin may remove only `member` and `guest`
- founder may remove non-founder memberships
- founder membership itself cannot be removed through generic delete

## Founder Transfer

### `POST /api/v1/workspaces/{workspace_id}/founder-transfer`

Purpose:

- transfer founder ownership to another existing workspace member

Allowed actors:

- current founder
- future platform admin

Payload:

```json
{
  "target_user_id": "user_123"
}
```

Rules:

- workspace must be active
- target must already have active workspace membership
- target role may be `admin`, `member`, or `guest`
- transactionally:
  - target becomes `founder`
  - previous founder becomes `admin`

Errors:

- `404` if workspace/member not found
- `409` if founder invariant would be broken
- `403` or domain-specific auth error if actor is not founder/platform admin

## Workspace Invites

### `GET /api/v1/workspaces/{workspace_id}/invites`

Purpose:

- list invites in the workspace

Allowed actors:

- founder
- admin
- future platform admin

### `POST /api/v1/workspaces/{workspace_id}/invites`

Purpose:

- create workspace invite by email

Allowed actors:

- founder
- admin
- future platform admin

Payload:

```json
{
  "email": "user@example.com",
  "role": "member",
  "permissions_override": {
    "can_manage_api_keys": false
  },
  "expires_at": "2026-04-20T12:00:00Z"
}
```

Rules:

- workspace must be active
- admin may invite only `member` or `guest`
- only founder/platform admin may invite `admin`
- may never invite `founder`

### `POST /api/v1/workspace-invites/{invite_id}/accept`

Purpose:

- accept invite as the authenticated user

Allowed actors:

- any authenticated user with matching email

Rules:

- invite email must match logged-in user email after normalization
- invite must be pending and valid
- workspace must not be archived
- membership creation/reactivation + invite acceptance must be transactional

### `POST /api/v1/workspaces/{workspace_id}/invites/{invite_id}/revoke`

Purpose:

- revoke pending invite

Allowed actors:

- founder
- admin
- future platform admin

Rules:

- only pending invite is revocable
- archived workspace may still allow revoke for hygiene, but this is optional

## Workspace Archive

### `POST /api/v1/workspaces/{workspace_id}/archive`

Purpose:

- archive workspace

Allowed actors:

- founder
- future platform admin

Payload:

```json
{
  "reason": "optional text"
}
```

Rules:

- default workspace cannot be archived
- archived workspace becomes frozen
- no batch physical cleanup
- resources remain stored

Effects:

- set `workspace.status = archived`
- set `archived_at`
- set `archived_by`
- later operational access is blocked by authorization layer

## Visibility Update APIs

### Knowledge Base

Modify:

- `PATCH /api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}`

Patchable fields should include:

- `name`
- `description`
- `status`
- `retrieval_profile`
- `visibility`

### Skill

Modify:

- `PATCH /api/v1/skills/{skill_id}`

Patchable fields should include:

- existing mutable fields
- `visibility`

Rules:

- write requires:
  - workspace capability permitting resource management
  - and visibility policy permitting edit

## Workspace Context Switch

### `POST /api/v1/auth/context/switch`

Purpose:

- switch active workspace context without relogin

Allowed actors:

- authenticated principal with active membership in target workspace and tenant

Payload:

```json
{
  "workspace_id": "ws_123"
}
```

Response should mirror login/context response shape:

- new bearer token
- active tenant/workspace info
- active tenant membership
- active workspace membership

Rules:

- target workspace must belong to active tenant unless cross-tenant switching is explicitly introduced later
- target workspace must not be archived
- caller must have active workspace membership in target workspace

## Suggested Service Modules

Recommended new services:

- `workspace_membership_service.py`
- `workspace_invite_service.py`
- `workspace_admin_service.py`
- `workspace_access_service.py`

Recommended updates:

- `auth.py`
- `deps.py`
- `principal.py`
- `knowledge_base_service.py`
- `skill_service.py`

## Test Coverage Requirements

Must cover:

- founder-only action enforcement
- admin restriction against managing other admins
- invite role restrictions
- archive blocking
- context switch to archived or unauthorized workspace rejected
- visibility updates enforce allowed enum values
- member/guest capability differences on admin APIs
