# Workspace Invitation Flow

## Scope

This document defines the Phase 4 workspace invitation model and acceptance flow.

It covers:

- invitation data model
- statuses
- lifecycle transitions
- email matching rules
- acceptance rules
- archive interaction

It does not cover:

- outbound email delivery implementation
- public registration UX design

## Fixed Decisions

The following are frozen for Phase 4:

- invite is email-based
- invite must support not-yet-registered users
- invite acceptance must be bound to the logged-in user's normalized email
- invite cannot be accepted by another account
- changing target email requires revoke-and-reinvite
- archived workspace makes pending invites unusable

## Data Model

`workspace_invites` fields:

- `id`
- `workspace_id`
- `email`
- `role`
- `permissions_override_json`
- `status`
- `invited_by`
- `accepted_user_id`
- `expires_at`
- `accepted_at`
- `revoked_at`
- `created_at`
- `updated_at`

### Enum

`status`:

- `pending`
- `accepted`
- `expired`
- `revoked`

### Role targets

Allowed invite target roles:

- `admin`
- `member`
- `guest`

Invite should not directly target `founder`.

Founder is acquired only by founder transfer flow.

## Email Rules

### User email

`User.email` is the matching source of truth.

Requirements:

- globally unique
- case-insensitive uniqueness
- normalized before invite comparison

### Invite email comparison

Comparison should use normalized email values:

- trim whitespace
- lower-case

Acceptance rule:

- logged-in user's normalized `email` must equal invite normalized `email`

If mismatch:

- reject with a stable authorization/validation error

## Lifecycle

### Create

Actor:

- workspace founder
- workspace admin
- future platform admin

On create:

- workspace must be active
- inviter must have `can_manage_invites`
- target role must be valid
- optional `permissions_override_json` must pass key whitelist validation
- if a pending invite already exists for the same normalized email in the same workspace, reject or replace according to final API policy

Recommended initial policy:

- reject duplicate pending invite with `409`

### Accept

Actor:

- logged-in user whose normalized email matches invite target email

Rules:

- invite must be `pending`
- invite must not be expired
- invite must not be revoked
- workspace must not be archived
- current user email must match invite email

On success, transactionally:

1. create or reactivate `workspace_membership`
2. apply invited `role`
3. apply invited `permissions_override_json`
4. set invite `status = accepted`
5. set `accepted_user_id`
6. set `accepted_at`

### Revoke

Actor:

- workspace founder
- workspace admin
- future platform admin

Rules:

- only `pending` invites can be revoked directly
- accepted invites are historical records, not revocable invitations

On revoke:

- set `status = revoked`
- set `revoked_at`

### Expire

An invite is expired when:

- current time > `expires_at`
- and status is still `pending`

Expiration may be handled:

- lazily during read/accept checks
- or by background reconciliation

Phase 4 recommendation:

- accept lazy evaluation first
- optionally persist state transition later

## Archive Interaction

Frozen rule:

- archived workspace invalidates invite usability

Implementation guidance:

- workspace archive does not need to batch update invite rows
- pending invites may remain stored as `pending`
- acceptance path must reject if workspace is archived

Optional later enhancement:

- archive flow may bulk mark pending invites as `revoked`

Phase 4 does not require that batch update.

## Registration And Login Handoff

### Required product flow

Recommended product flow:

1. user opens invite link
2. if not authenticated:
   - redirect to login or registration
3. after authentication:
   - return to invite acceptance flow
4. validate logged-in email against invite email
5. accept or reject

### Backend contract assumptions

Phase 4 backend should support:

- accepting invite after login with matching email
- failing fast on mismatch
- working for already-registered users

Registration pipeline itself may remain outside this scope if not yet implemented, but the invite acceptance API must be compatible with it.

## Conflict Handling

### Existing membership exists

If the accepting user already has a workspace membership:

- if membership is `active`, recommended behavior is:
  - reject as already joined
- if membership is `disabled` or `removed`, recommended behavior is:
  - reactivate and update according to invite role/override

This behavior should be explicit in service code and tests.

### Email mismatch

If authenticated email does not match invite email:

- reject
- do not permit “claiming” the invite
- require inviter to revoke and issue a new invite if target email changes

## Recommended API Surface

- `GET /api/v1/workspaces/{workspace_id}/invites`
- `POST /api/v1/workspaces/{workspace_id}/invites`
- `POST /api/v1/workspace-invites/{invite_id}/accept`
- `POST /api/v1/workspaces/{workspace_id}/invites/{invite_id}/revoke`

Recommended response shape for invite resources:

```json
{
  "id": "wsi_123",
  "workspace_id": "ws_123",
  "email": "user@example.com",
  "role": "member",
  "status": "pending",
  "expires_at": "2026-04-20T12:00:00Z",
  "accepted_user_id": null,
  "accepted_at": null,
  "revoked_at": null,
  "created_at": "2026-04-10T12:00:00Z",
  "updated_at": "2026-04-10T12:00:00Z"
}
```

## Test Requirements

Must cover:

- invite creation for unregistered email
- invite acceptance by matching registered email
- rejection on mismatched email
- rejection on expired invite
- rejection on revoked invite
- rejection on archived workspace
- reactivation path for disabled/removed membership if accepted policy chooses reactivation
