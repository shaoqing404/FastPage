# Phase 4 Migration Plan

## Goal

Migrate the current Phase 3 foundation into a Phase 4 access/admin control plane with minimal privilege expansion and minimal behavioral breakage.

This migration must preserve:

- existing tenant/workspace data
- existing workspace-bound resources
- existing auth flows during the transition
- historical ownership/audit attribution

## Fixed Decisions Driving Migration

- default workspace receives full tenant-membership backfill
- non-default workspace uses minimum-authorization backfill only
- founder is unique
- archive only, no purge
- visibility defaults to private
- invite is email-based
- user email is globally unique and case-insensitive

## Migration Inventory

### Existing tables to alter

- `users`
- `workspaces`
- `knowledge_bases`
- `chat_skills`

### New tables to add

- `workspace_memberships`
- `workspace_invites`

## Schema Changes

### `users`

Add:

- `email`
- `can_create_workspace`
- `is_platform_admin`
- `updated_at`

Recommended defaults:

- `can_create_workspace = false`
- `is_platform_admin = false`

Migration note:

- `email` may need a staged rollout if existing data lacks email
- if no user email source exists yet, Phase 4 may temporarily allow `NULL` during first migration and tighten later after backfill/admin remediation

Target constraint:

- case-insensitive unique on `email`

### `workspaces`

Add:

- `archived_at`
- `archived_by`

Optional constraint tightening:

- explicit `status` enum discipline for `active` and `archived`

### `workspace_memberships`

Create:

- `id`
- `workspace_id`
- `user_id`
- `role`
- `status`
- `permissions_override_json`
- `created_by`
- `created_at`
- `updated_at`

Indexes:

- `workspace_id`
- `user_id`
- unique `(workspace_id, user_id)`
- active founder uniqueness where supported

### `workspace_invites`

Create:

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

Indexes:

- `workspace_id`
- normalized email lookup
- `(workspace_id, normalized_email, status)` or equivalent support indexes

### `knowledge_bases`

Add:

- `visibility`

Default:

- `private`

### `chat_skills`

Add:

- `visibility`

Default:

- `private`

## Backfill Strategy

### Step 1. Prepare user email data

If authoritative emails already exist:

- backfill `users.email`

If authoritative emails do not exist yet:

- allow temporary `NULL`
- generate migration review report for rows without email
- block invite acceptance features for users without email until remediated

Phase 4 implementation should assume email is required for invitation flows even if schema tightening is staged.

### Step 2. Backfill default workspace memberships

For each tenant's default workspace:

- backfill all active `tenant_memberships`

Mapping:

- tenant `owner` -> workspace `founder`
- tenant `admin` -> workspace `admin`
- tenant `member` -> workspace `member`

Only one founder is allowed.

If there are multiple tenant owners historically:

- choose one deterministic founder using migration policy
- recommended order:
  1. workspace `created_by` if valid and active
  2. oldest active tenant owner
  3. oldest active tenant admin requiring manual review if no owner

Any non-selected historical owner should be downgraded to workspace `admin` in backfill output if included.

### Step 3. Backfill non-default workspace memberships

Do not backfill all tenant members.

Backfill only the minimum set:

1. `workspace.created_by` -> `founder`
2. users with existing resource ownership in that workspace -> `member`

Resource-owner signals allowed for backfill:

- `documents.owner_user_id`
- `chat_skills.owner_user_id`
- `chat_sessions.user_id`
- `chat_runs.user_id`
- `knowledge_bases.created_by`
- `api_keys.created_by` where `workspace_id` matches

Do not use weak signals:

- mere tenant membership
- historical access guesses
- inferred “probably had access”

### Step 4. Founder gap review

If a non-default workspace has no resolvable founder candidate:

- do not guess
- emit migration review item
- require post-migration admin remediation

Recommended output:

- migration log table entry
- or generated report artifact

### Step 5. Backfill visibility

For all existing rows:

- `knowledge_bases.visibility = 'private'`
- `chat_skills.visibility = 'private'`

Reason:

- safest default
- avoids privilege expansion during migration

### Step 6. Leave tenant memberships in place

Do not remove or rewrite `tenant_memberships`.

Phase 4 behavior after migration:

- tenant membership remains tenant gate
- workspace membership becomes workspace gate

## Runtime Compatibility Plan

### Token and principal compatibility

During the rollout:

- old token payloads may not contain workspace membership claims
- principal resolution must still load fresh DB-backed tenant/workspace membership state

Recommended approach:

- keep token minimal
- resolve current tenant/workspace membership server-side on each request

### Application-layer compatibility

Use application-layer compatibility for:

- archived workspace access blocking
- lazy invite expiry handling
- founder invariant enforcement in services
- default empty `permissions_override_json`

## Migration Ordering

Recommended order:

1. add columns to `users`, `workspaces`, `knowledge_bases`, `chat_skills`
2. create `workspace_memberships`
3. create `workspace_invites`
4. backfill default workspace memberships
5. backfill non-default workspace memberships
6. backfill visibility
7. generate migration review items for unresolved founder cases
8. add founder uniqueness constraint/index
9. deploy app changes that require workspace memberships in principal

## Rollout Safety

### Recommended rollout sequence

1. migrate schema
2. backfill data
3. deploy code that can read both old and new principal-compatible state
4. enable new admin APIs
5. tighten behavioral enforcement

### Rollback considerations

High-risk areas:

- founder uniqueness enforcement
- email uniqueness enforcement
- principal resolution requiring workspace membership

Recommended rollback posture:

- migration scripts must be additive wherever possible
- code should tolerate temporary `NULL email` during staged rollout if the database must transition gradually
- founder backfill conflicts must fail safe into migration review, not silent privilege grants

## Test Expectations

Migration verification should include:

- default workspace full backfill mapping
- non-default workspace minimum-authority backfill
- no accidental tenant-wide privilege expansion
- founder uniqueness after backfill
- private visibility defaults on KB and Skill rows
- unresolved founder cases logged for review rather than auto-guessed
