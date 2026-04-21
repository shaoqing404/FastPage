# Phase 5: Maintenance, Audit, and Governance

## 1. Positioning

`Phase 5` starts only after `Phase 4.8` has closed the real operator usage gaps on the current product surface.

This phase is not a continuation of basic control-plane completion work.

Its job is to turn the already-usable PageIndex service into a system that can be:

- maintained as a long-lived multi-tenant product
- audited through explicit operator and system records
- governed through explainable scope, ownership, and review semantics
- extended without reintroducing Phase 4 ambiguity around runtime truth and product truth

In short:

- `Phase 4.x` finishes product-operability
- `Phase 5` becomes the maintenance + audit主体 + governance parent stage

`Phase 5` must treat the closed `Phase 4.x` contracts as its baseline, not reopen them casually.

## 2. Why This Phase Exists

By the end of `Phase 4.8`, the service should already support:

- workspace operation
- provider / KB / document / skill / skill-chat usage
- access portrait visibility
- operator-facing control-plane continuity

That is enough to use the product.

It is not yet enough to run it as a durable platform.

The missing layer is:

- maintenance-oriented ownership and review semantics
- explicit audit and inspection surfaces
- durable policy around shared resources and resource scope
- operational records that explain who changed what, where, and why
- platform guardrails that support long-term multi-workspace operation

`Phase 5` exists to absorb that layer.

## 3. Core Boundary

### 3.1 Phase 5 is responsible for

- maintenance-oriented platform surfaces
- audit center / audit records / audit inspection flows
- governance workflows and review semantics
- durable resource ownership and sharing policy
- long-term operational visibility
- export / import productization
- migration portability
- explicit shared-resource rules across tenant and workspace boundaries

### 3.2 Phase 5 is not responsible for

- reopening basic workspace CRUD/auth/context foundations already closed in `Phase 4`
- speculative redesign of already-usable pages without an audit/maintenance reason
- replacing existing product truth with frontend-only heuristics
- introducing broad new AI/runtime experiments unrelated to maintenance or audit goals

## 4. Phase 5 Product Thesis

The central thesis of `Phase 5` is:

> resources that can affect multiple operators or multiple workspaces must have explicit ownership, explicit visibility, explicit reviewability, and explicit auditability.

This applies especially to:

- providers
- API keys
- workspaces
- memberships
- skills
- knowledge bases
- compliance definitions and runs

## 5. Design Principles

### 5.1 Saved truth beats runtime guesswork

If the product needs a durable configuration, it must be represented as saved state, not only as runtime override.

### 5.2 Shared resources require explicit scope

Any resource that can be reused across workspaces must expose:

- owner scope
- access scope
- effective visibility
- effective defaults / fallback order

### 5.3 Auditability is a product requirement

If an operator can create, update, share, bind, or revoke something, the platform should be able to explain:

- who performed the action
- what changed
- when it changed
- which tenant/workspace it affected

### 5.4 Maintenance is not just observability

`Phase 5` maintenance includes:

- durable admin flows
- cleanup and lifecycle policy
- resource inspection and dependency reasoning
- recoverable change workflows
- reviewable mutations

It is broader than logs and dashboards.

## 6. Initial Requirement Streams

### 6.1 Audit and maintenance主体

`Phase 5` should establish a real audit/maintenance主体 rather than leaving operations scattered across individual resource pages.

This includes:

- audit-oriented inspection surfaces
- maintenance-oriented dependency views
- review queues or reviewable change lists where appropriate
- durable operational history for high-impact resources

At minimum, high-impact changes should become inspectable for:

- provider creation / update / delete
- provider sharing / unsharing
- workspace default changes
- skill provider/model rebinding
- KB rebinding on skills
- workspace membership and capability mutations

### 6.2 Tenant lifecycle, organization semantics, and isolation truth

`Phase 5` must stop treating `tenant` as a backend-only implementation word.

For product semantics, the tenant is the real organization boundary:

- `tenant = organization`
- `workspace = collaboration space inside one organization`
- tenant remains the hard isolation boundary for:
  - providers
  - API keys
  - documents / KBs / skills / runs
  - storage layout
  - future billing / quota / audit scope

This has several design consequences that must be handled explicitly in `Phase 5`.

#### Current product contradiction that Phase 5 must resolve

Current implementation reality is:

- there is still no formal self-serve tenant creation flow
- `POST /api/v1/workspaces` creates a workspace inside the current tenant, not a new organization
- accepting a workspace invite currently auto-creates or reactivates `tenant_membership` in the target tenant and then creates `workspace_membership`

That means a workspace invite currently acts as:

- organization entry
- plus workspace entry

This is implementation-valid, but not yet product-clear.

`Phase 5` must explicitly decide and document:

- whether workspace invite should continue to imply organization membership
- whether organization-level invite and workspace-level invite should become separate product concepts
- how tenant membership should be explained in UI and docs
- how cross-organization onboarding should appear to an invited user

#### Required Phase 5 outputs

1. Organization creation and lifecycle

- formal tenant creation API and product entry
- explicit default-workspace bootstrap for a newly created tenant
- organization identity surface:
  - name
  - slug/code where needed
  - founder/owner semantics

2. Organization membership management

- inspect tenant memberships
- add / invite / remove tenant members
- role and status management for tenant membership
- explicit relation between tenant membership and workspace membership

3. Invite model clarification

- document whether the system supports:
  - organization invite
  - workspace invite
  - both
- if both exist, define:
  - which one creates tenant membership
  - which one creates workspace membership
  - whether workspace invite is allowed without prior organization membership
- if workspace invite continues to imply organization membership, this must be explicit in user-facing copy and operator documentation

4. Isolation explanation

- operators must be able to understand that:
  - different workspaces inside one tenant are not equivalent to different organizations
  - true customer isolation requires different tenants
  - workspace is for collaboration partitioning, not for tenant-grade isolation

#### User-facing terminology requirement

`Phase 5` should prefer product-facing terms such as:

- `organization`
- `organization member`
- `organization-shared provider`
- `workspace provider`

Internal/backend wording like `tenant provider` may remain in code, but should not be the primary customer-facing vocabulary.

### 6.3 Provider ownership, sharing, and defaulting

`Phase 5` formalizes provider as a dual-scope resource.

#### Provider types

- `tenant provider`
  - owned by the tenant
  - managed by tenant-level admins
  - can be shared to:
    - all workspaces
    - selected workspaces
- `workspace provider`
  - owned by one workspace
  - visible and usable only inside that workspace
  - cannot be elevated into tenant-shared scope by simple relabeling

#### Product rules

- provider scope must be explicit in API output and UI
- `tenant provider` does not automatically mean “usable by every workspace”
- sharing must be explicit and reviewable
- tenant-wide sharing governance must not be limited to only the workspaces visible in the current session context
- a workspace may only bind providers that are actually available to it
- a workspace may set a workspace default provider only from its available provider set
- tenant default provider remains valid as a fallback layer
- duplicate import behavior and repeated workspace-copy creation must be governed explicitly rather than relying on accidental naming side effects

#### Governance requirements

`Phase 5` must provide a true tenant-wide sharing surface for organization-shared providers:

- inspect all workspaces in the tenant that a shared provider is available to
- grant or revoke provider availability across the tenant
- distinguish clearly between:
  - sharing a tenant/organization provider to workspaces
  - importing/forking a workspace-owned copy from a shared source
- prevent or explicitly manage repeated imports of the same shared provider into the same workspace
- expose dependency reasoning before destructive actions:
  - which skills bind this provider
  - which workspaces default to it
  - which workspace-owned copies originated from it

#### Recommended resolution order

1. skill saved provider
2. explicit runtime test override
3. workspace default provider
4. tenant default provider
5. system default provider

The product path should prefer saved binding, not habitual runtime override.

### 6.4 Skills and skill chat as saved configuration surfaces

`Phase 5` should close the remaining ambiguity between `Skills` and `Skill Chat`.

#### Canonical product path

1. create a skill card in `Skills`
2. click the card
3. enter that skill's dedicated configuration + testing page
4. test the saved or draft configuration there

`SkillChatPage` is the correct conceptual base for that page, but it must become a real skill configuration surface rather than a mixed runtime console.

#### Saved state requirements

Skill saved configuration must durably represent:

- `knowledge_base_id`
- `provider_id`
- `model`
- `system_prompt`
- any retrieval / generation / conversation options that the product decides are true skill defaults

The following rules apply:

- provider binding must be saved on the skill, not left as runtime-only override
- model selection must be provider-aware
- model should primarily come from provider-backed choices:
  - `default_model`
  - `supported_models`
- incompatible provider/model combinations must be blocked before save
- runtime-only test overrides may remain, but must be visibly marked as run-only

#### Route and IA requirements

- `Skills` must be the canonical library entry point
- skill detail/config/test must use one canonical route family
- `/skills/chat/:id` and `/chat/skills/:id` must not continue as parallel product truths

### 6.5 Knowledge Base binding policy for skills

For the current `Phase 5` scope:

- one skill binds one `knowledge_base_id`
- multi-KB skill authoring is not required
- `document_ids` remains only as a compatibility field where needed

Product truth should be KB-first:

- operators configure the skill against one KB
- compatibility document projections may still exist in APIs
- legacy document-shim semantics must not remain the main authoring model

## 7. Suggested Phase 5 Workstreams

### Workstream A: Audit Platform Foundation

Goal:

- create durable audit records and operator-facing audit inspection surfaces

This workstream should also cover tenant / organization lifecycle mutations:

- organization creation
- organization membership changes
- workspace invite acceptance when it implies organization entry

### Workstream B: Shared Resource Governance

Goal:

- formalize ownership, sharing, and dependency semantics for providers, API keys, and other reusable resources

This workstream must explicitly include tenant-wide provider governance rather than only workspace-local consumption surfaces.

### Workstream C: Skill / KB / Provider Governance UX

Goal:

- close the product truth around skill saved configuration, KB binding, and provider/model linkage

### Workstream D: Portability and Long-Term Operations

Goal:

- add the export/import and migration-oriented work that intentionally stayed outside `Phase 4`

## 8. Acceptance Standard

`Phase 5` is not complete when an audit page merely exists.

It is complete only when:

- organization vs workspace semantics are product-clear and enforceable
- tenant creation and tenant membership lifecycle no longer rely on implicit or undocumented behavior
- shared-resource ownership is explicit and enforceable
- provider scope and sharing are understandable to operators
- high-impact mutations are reviewable and auditable
- the skill / provider / KB product surface uses saved truth rather than runtime guesswork
- maintenance-oriented operator flows do not require undocumented workarounds
- long-term governance and audit capabilities are clearly separated from the closed `Phase 4.x` control-plane foundation

## 9. Non-Goals for the First Phase 5 Slice

The first `Phase 5` slice should not automatically include:

- a full enterprise org tree
- fine-grained policy engine across every resource type
- billing/chargeback productization
- quota engine across every runtime path
- speculative AI governance features unrelated to current operator flows

These may follow later, but they are not required to define or begin `Phase 5`.
