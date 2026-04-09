# Releasing And Repository Rename

This document covers two operational topics for this repository:

- renaming the GitHub repository after the service split
- cutting the first public release/tag for the Phase 3 baseline

## Recommended Repository Name

Recommended GitHub repository name:

- `PageIndex-Service`

Why:

- it stays close to the actual project positioning
- it makes the upstream relationship obvious
- it is more accurate than `PageIndex-RAG`, because this repository is not only a RAG demo

Less preferred alternative:

- `PageIndex-RAG`

That name is narrower than the actual service scope and under-describes the console, worker, compliance, and packaging layers.

## Can The Project Keep `PageIndex` As A Prefix?

Practical recommendation:

- yes, if the repository clearly states that it is based on / derived from PageIndex
- yes, if the repository does not present itself as the official upstream PageIndex project
- yes, if the README keeps visible attribution and license continuity

Brand caution:

- the upstream repository is MIT licensed
- this document is not legal advice
- if the project is going to be commercially marketed under a long-lived public brand, confirm naming expectations with the upstream maintainers

Safe naming pattern:

- `PageIndex Service`
- `pageindex-service`

Avoid:

- naming the fork simply `PageIndex`
- wording that implies official ownership by the upstream project

## GitHub Rename Procedure

If you rename the GitHub repository from:

- `https://github.com/shaoqing404/PageIndex`

to:

- `https://github.com/shaoqing404/PageIndex-Service`

then update local remotes with:

```bash
git remote set-url origin https://github.com/shaoqing404/PageIndex-Service.git
git remote -v
git remote set-head origin -a
git fetch origin --prune
```

## Does The Local Folder Need To Be Renamed?

No.

Git tracks the repository by `.git` metadata and remote configuration, not by the parent folder name. The local directory can stay as:

- `~/workspace/PageIndex`

If you want cosmetic consistency, you may rename the local folder later, but it is not required for Git, tags, branches, or future pushes.

## Suggested First Release

For the current public Phase 3 baseline, recommended first tag:

- `v0.1.0`

If you want a short public bake-in before the first stable tag, use:

- `v0.1.0-rc1`

Suggested interpretation:

- `v0.1.0`: first public service baseline
- `v0.1.1`: packaging/doc/runtime fixes
- `v0.2.0`: post-baseline but still pre-1.0 feature expansion

## Release Checklist

Before tagging:

1. Confirm `main` is the intended public baseline branch.
2. Confirm README positioning, attribution, and roadmap are current.
3. Confirm `uv sync --python 3.12` works.
4. Confirm `uv run python -c "import app.main"` works.
5. Confirm `uv run alembic heads` points at one expected head.
6. Confirm `cd frontend && npm run build` works.
7. Confirm `docker compose config` succeeds against `docker/.env.example`.
8. Confirm `docker/.env.example` matches `docker/docker-compose.yml`.
9. Confirm `spec/` is not included in the public push.
10. Confirm Docker image build on a machine with a running Docker daemon.

## Current Known Validation State

Already checked in this repository state:

- `uv sync --python 3.12`
- `uv run python -c "import app.main"`
- `uv run alembic heads`
- `cd frontend && npm run build`
- `docker compose config`

Still worth checking on a Docker-enabled machine before cutting a release:

- `docker build -f Dockerfile .`
- `docker build -f Dockerfile.worker .`
- optional end-to-end `docker compose up`

## Tag And Push Commands

Example stable release:

```bash
git checkout main
git pull --ff-only origin main
git tag -a v0.1.0 -m "PageIndex Service v0.1.0"
git push origin main
git push origin v0.1.0
```

Example release candidate:

```bash
git checkout main
git pull --ff-only origin main
git tag -a v0.1.0-rc1 -m "PageIndex Service v0.1.0-rc1"
git push origin main
git push origin v0.1.0-rc1
```

## Suggested GitHub Release Title

- `PageIndex Service v0.1.0`

## Suggested Release Notes Template

```md
## Summary

First public Phase 3 baseline of PageIndex Service, a deployable service and console layer built on top of PageIndex.

## Included

- FastAPI API and queue-backed worker baseline
- tenant/workspace foundation
- knowledge bases
- skill chat
- compliance checks and compliance runs
- Alembic migration chain
- Python 3.12 + uv source startup path
- Docker and compose packaging for local evaluation

## Upstream Attribution

This project is based on and derived from PageIndex. Thanks to the PageIndex team for the upstream framework and open-source release.

## Notes

- This release is a Phase 3 baseline, not a Phase 4 feature expansion.
- Kubernetes packaging and alternative infrastructure components are follow-up work.
```
