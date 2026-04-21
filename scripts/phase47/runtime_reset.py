#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[2]

REPO_OWNED_SCHEMA_TABLES: tuple[str, ...] = (
    "alembic_version",
    "api_keys",
    "audit_events",
    "chat_messages",
    "chat_runs",
    "chat_sessions",
    "chat_skill_documents",
    "chat_skills",
    "compliance_checks",
    "compliance_runs",
    "document_versions",
    "documents",
    "knowledge_base_documents",
    "knowledge_bases",
    "migration_review_items",
    "model_providers",
    "parse_jobs",
    "revoked_tokens",
    "tenant_memberships",
    "tenants",
    "users",
    "workspace_invites",
    "workspace_memberships",
    "workspaces",
)

REPO_LOCAL_RUNTIME_DIRS: tuple[Path, ...] = (
    ROOT / "data",
    ROOT / "logs",
    ROOT / "results",
)


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _minio_root_prefix(settings) -> str:
    prefix = (settings.minio_prefix_path or "").strip("/")
    if prefix:
        return f"{prefix}/tenants/"
    return "tenants/"


def _describe_targets() -> dict[str, object]:
    from app.core.config import get_settings

    settings = get_settings()
    return {
        "repository_root": str(ROOT),
        "database_mode": settings.database_mode,
        "database_url": settings.database_url,
        "storage_backend": settings.storage_backend,
        "task_queue_backend": settings.task_queue_backend,
        "minio_bucket": settings.minio_bucket,
        "minio_root_prefix": _minio_root_prefix(settings),
        "local_runtime_dirs": [str(path) for path in REPO_LOCAL_RUNTIME_DIRS],
        "repo_owned_schema_tables": list(REPO_OWNED_SCHEMA_TABLES),
    }


def _require_execute(args: argparse.Namespace, action: str) -> None:
    if not args.execute:
        raise SystemExit(f"{action} 是破坏性操作。先 dry-run 确认，再加 --execute。")


def describe_targets(_: argparse.Namespace) -> int:
    _print_json(_describe_targets())
    return 0


def reset_mysql(args: argparse.Namespace) -> int:
    from app.core.config import get_settings

    settings = get_settings()
    if settings.database_mode != "mysql":
        raise SystemExit("reset-mysql 只允许在 DATABASE_MODE=mysql 时执行。")

    engine = sa.create_engine(settings.database_url, future=True)
    try:
        inspector = sa.inspect(engine)
        existing_tables = set(inspector.get_table_names())
        owned_tables = set(REPO_OWNED_SCHEMA_TABLES)
        unexpected_tables = sorted(existing_tables - owned_tables)
        missing_tables = sorted(owned_tables - existing_tables)

        payload = {
            "database_url": settings.database_url,
            "existing_owned_tables": sorted(existing_tables & owned_tables),
            "missing_owned_tables": missing_tables,
            "unexpected_tables": unexpected_tables,
        }

        if unexpected_tables:
            payload["status"] = "blocked"
            payload["reason"] = "发现未列入 runbook 的表，已停止，避免误删共享数据。"
            _print_json(payload)
            return 2

        if not args.execute:
            payload["status"] = "dry_run"
            _print_json(payload)
            return 0

        with engine.begin() as conn:
            conn.execute(sa.text("SET FOREIGN_KEY_CHECKS=0"))
            for table_name in REPO_OWNED_SCHEMA_TABLES:
                if table_name in existing_tables:
                    conn.execute(sa.text(f"DELETE FROM {table_name}"))
            conn.execute(sa.text("SET FOREIGN_KEY_CHECKS=1"))

        payload["status"] = "completed"
        _print_json(payload)
        return 0
    finally:
        engine.dispose()


def reset_minio(args: argparse.Namespace) -> int:
    from app.core.config import get_settings

    settings = get_settings()
    if settings.storage_backend != "minio":
        raise SystemExit("reset-minio 只允许在 STORAGE_BACKEND=minio 时执行。")
    if not settings.minio_bucket:
        raise SystemExit("MINIO_BUCKET 为空，无法确认 repo-owned 范围。")
    if not settings.minio_endpoint:
        raise SystemExit("MINIO_ENDPOINT 为空，无法连接 MinIO。")

    root_prefix = _minio_root_prefix(settings)
    payload = {
        "minio_endpoint": settings.minio_endpoint,
        "minio_bucket": settings.minio_bucket,
        "minio_root_prefix": root_prefix,
    }
    if not args.execute:
        payload["status"] = "dry_run"
        _print_json(payload)
        return 0

    try:
        from minio import Minio
    except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
        raise SystemExit("当前环境缺少 minio 依赖，无法执行 reset-minio。") from exc

    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    deleted: list[str] = []
    for obj in client.list_objects(settings.minio_bucket, prefix=root_prefix, recursive=True):
        client.remove_object(settings.minio_bucket, obj.object_name)
        deleted.append(obj.object_name)

    payload["status"] = "completed"
    payload["deleted_count"] = len(deleted)
    payload["deleted_preview"] = deleted[:20]
    _print_json(payload)
    return 0


def reset_local(args: argparse.Namespace) -> int:
    payload = {
        "local_runtime_dirs": [str(path) for path in REPO_LOCAL_RUNTIME_DIRS],
    }
    if not args.execute:
        payload["status"] = "dry_run"
        _print_json(payload)
        return 0

    removed: dict[str, list[str]] = {}
    for directory in REPO_LOCAL_RUNTIME_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
        removed[str(directory)] = []
        for child in directory.iterdir():
            removed[str(directory)].append(child.name)
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        directory.mkdir(parents=True, exist_ok=True)

    payload["status"] = "completed"
    payload["removed_entries"] = removed
    _print_json(payload)
    return 0


def rebuild(_: argparse.Namespace) -> int:
    from app.core.auth import resolve_auth_context
    from app.core.bootstrap import init_db
    from app.core.config import get_settings
    from app.core.db import engine
    from app.models import Tenant, TenantMembership, User, Workspace, WorkspaceMembership

    settings = get_settings()
    init_db()

    with Session(engine) as db:
        tenant = db.get(Tenant, "tenant_default")
        user = db.scalar(sa.select(User).where(User.username == settings.admin_username))
        workspace = db.scalar(
            sa.select(Workspace).where(
                Workspace.tenant_id == "tenant_default",
                Workspace.is_default.is_(True),
            )
        )
        tenant_membership = None
        workspace_membership = None
        context = None
        if user is not None:
            tenant_membership = db.scalar(
                sa.select(TenantMembership).where(
                    TenantMembership.tenant_id == "tenant_default",
                    TenantMembership.user_id == user.id,
                )
            )
            if workspace is not None:
                workspace_membership = db.scalar(
                    sa.select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == workspace.id,
                        WorkspaceMembership.user_id == user.id,
                    )
                )
            context = resolve_auth_context(db, user)

        version = db.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        bootstrap_ready = bool(
            tenant
            and user
            and workspace
            and tenant_membership
            and workspace_membership
            and context is not None
        )
        payload = {
            "status": "completed",
            "database_url": settings.database_url,
            "alembic_version": version,
            "bootstrap_ready": bootstrap_ready,
            "tenant_id": tenant.id if tenant is not None else None,
            "user_id": user.id if user is not None else None,
            "workspace_id": workspace.id if workspace is not None else None,
            "tenant_role": tenant_membership.role if tenant_membership is not None else None,
            "workspace_role": workspace_membership.role if workspace_membership is not None else None,
            "resolved_workspace_id": context.workspace.id if context is not None else None,
        }
        _print_json(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 4.7 reset/rebuild helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe_parser = subparsers.add_parser("describe", help="打印当前 repo-owned runtime 目标")
    describe_parser.set_defaults(func=describe_targets)

    mysql_parser = subparsers.add_parser("reset-mysql", help="清理 repo-owned MySQL 表数据")
    mysql_parser.add_argument("--execute", action="store_true")
    mysql_parser.set_defaults(func=reset_mysql)

    minio_parser = subparsers.add_parser("reset-minio", help="清理 repo-owned MinIO 前缀")
    minio_parser.add_argument("--execute", action="store_true")
    minio_parser.set_defaults(func=reset_minio)

    local_parser = subparsers.add_parser("reset-local", help="清理 repo-local 运行目录")
    local_parser.add_argument("--execute", action="store_true")
    local_parser.set_defaults(func=reset_local)

    rebuild_parser = subparsers.add_parser("rebuild", help="执行 migration + bootstrap 并输出基线摘要")
    rebuild_parser.set_defaults(func=rebuild)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
