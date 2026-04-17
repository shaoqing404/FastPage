# Phase 4.7 Verification Artifact Cleanup And Retention Rule

- Stage: `Phase 4.7`
- Repository: `/Users/shaoqing/workspace/PageIndex`
- Purpose: remove ad hoc cleanup decisions from live validation.

## 1. Naming Rule

Use a stable prefix for all temporary runtime-validation artifacts:

- user: `phase47_val_<timestamp>`
- workspace slug: `phase47-validation-<suffix>`
- provider: `phase47-validation-provider-<suffix>`
- knowledge base: `Phase47 Validation KB <suffix>`
- skill: `Phase47 Validation Skill <suffix>`
- API key: `phase47-validation-key-<suffix>`

Email format:

- `phase47+<timestamp>@example.test`

## 2. Password Rule

Temporary validation passwords must never be written to repo-tracked files.

Allowed handling:

- hold in process memory during scripted execution
- show once in terminal output if the operator explicitly chooses a reset-password flow

Forbidden handling:

- storing cleartext passwords in Markdown
- storing cleartext passwords in `results/`
- committing cleartext passwords to git

If `reset-password` is exercised, record only:

- target user id
- reset timestamp
- actor id
- whether the subsequent change-password flow passed

## 3. Cleanup Matrix

Clean immediately after a successful validation run:

- temp API keys: revoke
- temp skills: delete
- temp knowledge bases: delete
- temp documents and document versions: delete
- temp parse jobs and chat runs created off those documents: remove indirectly through supported delete paths
- temp providers: delete after dependent runs/documents/skills are removed

Deactivate and retain for short audit correlation:

- temp users: patch `is_active=false`
- temp workspaces: archive

Retain as evidence:

- latest passing JSON validation artifact under `results/`
- latest failing JSON validation artifact under `results/`
- closeout report references to those artifacts

## 4. Retention Window

Default retention windows:

- passing JSON validation artifact: retain until the next successful `Phase 4.7` rerun, and at least 14 days
- failing JSON validation artifact: retain until the failure is triaged and superseded, and at least 14 days
- disabled validation users and archived validation workspaces: retain until the next clean reset cycle

No physical-delete requirement is introduced here for archived users/workspaces because purge is explicitly outside `Phase 4.x`.

## 5. Failure Rule

If validation fails mid-run:

- do not perform broad cleanup
- keep created artifacts in place for triage
- record every created id in the JSON report
- mark the run as `retained_for_failure_analysis=true`

Allowed exception:

- revoke any leaked temp API key immediately if leaving it active would be risky

## 6. Success Rule

If validation passes:

- perform supported cleanup in the scripted order
- write the final cleanup status into the JSON artifact
- confirm no temp API key remains active
- confirm temp workspace is archived
- confirm temp user is inactive

## 7. Cleanup Order

Use this order after a successful run:

1. revoke API key
2. delete skill
3. delete document
4. delete knowledge base
5. delete provider
6. archive workspace
7. disable validation user

Rationale:

- provider delete can fail while runs still reference it
- document delete removes parse jobs and chat runs for the validation document
- workspace archive should happen only after in-workspace cleanup is complete

## 8. Required Report Fields

Every validation JSON artifact must contain:

- `created.user_id`
- `created.workspace_id`
- `created.provider_id`
- `created.knowledge_base_id`
- `created.document_id`
- `created.skill_id`
- `created.api_key_id`
- `cleanup.status`
- `cleanup.retained_for_failure_analysis`
- `cleanup.remaining_artifacts`

## 9. Boundary

This rule operationalizes `Phase 4.7`.

It does not:

- introduce a long-term archive system
- replace future governance retention policy
- authorize manual DB deletion as the default cleanup path
