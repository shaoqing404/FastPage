---
name: pageindex-release-distribute
description: Use when releasing PageIndex-Service from a local workspace: inspect changes, commit and push eligible code, rebuild Docker images, refresh the desktop export bundle, and optionally distribute the exported code to an intranet host.
---

# PageIndex Release Distribute

Use this project skill for PageIndex-Service release/distribution requests that combine git submission, Docker rebuilds, desktop export, and optional intranet transfer.

## Required Questions

Before starting, ask the user two short questions unless the current request already answers them:

1. Should the refreshed export be pushed to an intranet host? If yes, collect host, account, destination path, and preferred transfer scope (`code only` or `full bundle`).
2. Should any customer-specific terms be redacted or blocked from the export/commit, such as operation manuals, airline names, customer names, routes, tenant names, or other sensitive identifiers? Ask for the exact terms or patterns.

Do not print passwords, API keys, tokens, or full private `.env` contents. If credentials are needed for transfer, use the provided credentials only in the command/session.

## Default Boundaries

- Repository root: `/Users/mac/Developer/element_workspace/PageIndex-Service`.
- Default Docker mode: `full` mode, not local SQLite mode.
- Treat local/SQLite mode as deprecated and mention that only when relevant.
- Never commit or export private env files: `.env`, `.env.*`, `docker/.env`.
- Never commit `specs/` or `spec/` engineering process files unless the user explicitly overrides this boundary.
- Do not assume customer intranet endpoints are reachable beyond the requested transfer target.
- Preserve user or other-agent changes. Do not revert unrelated files.

## Workflow

1. Inspect state:

```bash
git status --short
git fetch origin main
git log --oneline --decorate --graph --left-right --cherry-pick origin/main...HEAD
```

Review `git diff --stat` and identify files eligible for commit. Exclude private env files and process artifacts.

2. Commit and push:

- Stage only eligible files.
- Commit with a concise release-oriented message.
- If local and remote histories diverged, integrate `origin/main` by merge or rebase without losing either side.
- Push the current branch to `origin`.

3. Rebuild local Docker full stack:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml --profile full build api frontend
docker compose --env-file docker/.env -f docker/docker-compose.yml --profile full up -d mysql redis minio elasticsearch api frontend
```

4. Verify service health:

```bash
curl -fsS http://127.0.0.1:22223/healthz
curl -fsS http://127.0.0.1:5173/providers
```

When Phase 5 runtime paths changed, prefer the targeted container test:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml --profile full exec -T api sh -c 'DATA_DIR=/tmp/pageindex-test-data uv run --with pytest python -m pytest tests/phase4/test_pageindex_llm_failfast.py tests/phase4/test_direct_chat_adapter.py tests/phase5/test_endpoint_resolution.py tests/phase4/test_pageindex_retrieval_contract.py tests/phase4/test_skill_stream_runtime_contract.py tests/phase4/test_provider_execution_model_normalization.py tests/phase4/test_node_embedding_service.py tests/phase4/test_pageindex_native_rerank.py -q'
```

5. Build distribution image packages:

```bash
bash /Users/mac/.codex/skills/pageindex-docker-build/scripts/build_pageindex_images.sh \
  /Users/mac/Developer/element_workspace/PageIndex-Service \
  /Users/mac/Desktop/pageindex-export/images
```

6. Refresh the desktop export:

```bash
bash scripts/pageindex_export.sh /Users/mac/Desktop/pageindex-export
```

Remove stale image tarballs with obsolete names if they could confuse distribution. Then verify the export excludes private files and process artifacts:

```bash
find /Users/mac/Desktop/pageindex-export/code/PageIndex-Service \
  \( -name .env -o -path '*/docker/.env' -o -path '*/.git/*' -o -path '*/node_modules/*' -o -path '*/specs/*' -o -name .DS_Store -o -name '.tmp_*' \) -print
```

7. Optional intranet distribution:

- Only do this if the user requested it or answered yes to the required question.
- Prefer `rsync -az --delete` for code-only distribution.
- For full bundle distribution, confirm enough disk/network budget first.
- Verify the remote destination path after transfer.

Example:

```bash
rsync -az --delete -e "ssh -o StrictHostKeyChecking=accept-new" \
  /Users/mac/Desktop/pageindex-export/code/PageIndex-Service/ \
  user@host:/target/PageIndex-Service/
```

## Final Report

Report:

- commit hash and pushed branch
- Docker build and startup results
- health/test results
- desktop export path and size
- image tarball names
- intranet transfer target and verification, if performed
- redaction/customer-term decision
- remaining risks, including whether customer intranet smoke was not performed
