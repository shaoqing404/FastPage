import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core import bootstrap
from app.core.auth import resolve_auth_context
from app.core.db import Base
from app.models import ModelProvider, Tenant, TenantMembership, User, Workspace, WorkspaceMembership


def _engine_for_url(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


class TestBootstrapInitDb(unittest.TestCase):
    def _settings(
        self,
        *,
        database_url: str,
        llm_base_url: str = "",
        llm_api_key: str = "",
    ) -> SimpleNamespace:
        return SimpleNamespace(
            admin_username="admin",
            admin_password="changeme",
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            secret_key="bootstrap-test-secret",
            database_url=database_url,
        )

    def _run_init_db(self, engine, settings: SimpleNamespace) -> None:
        with (
            patch.object(bootstrap, "engine", engine),
            patch.object(bootstrap, "get_settings", return_value=settings),
            patch.object(bootstrap, "_run_migrations", side_effect=lambda: Base.metadata.create_all(bind=engine)),
        ):
            bootstrap.init_db()

    def test_init_db_bootstraps_fresh_sqlite_path_with_login_ready_auth_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "fresh-bootstrap.db"
            database_url = f"sqlite:///{db_path}"
            engine = _engine_for_url(database_url)
            self.addCleanup(engine.dispose)

            self._run_init_db(engine, self._settings(database_url=database_url))

            with Session(engine) as db:
                tenant = db.get(Tenant, "tenant_default")
                user = db.scalar(select(User).where(User.username == "admin"))
                workspace = db.scalar(
                    select(Workspace).where(
                        Workspace.tenant_id == "tenant_default",
                        Workspace.is_default.is_(True),
                    )
                )
                tenant_membership = db.scalar(
                    select(TenantMembership).where(
                        TenantMembership.tenant_id == "tenant_default",
                        TenantMembership.user_id == "user_default",
                    )
                )
                workspace_membership = db.scalar(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == bootstrap.default_workspace_id_for_tenant("tenant_default"),
                        WorkspaceMembership.user_id == "user_default",
                    )
                )

                self.assertIsNotNone(tenant)
                self.assertIsNotNone(user)
                self.assertIsNotNone(workspace)
                self.assertIsNotNone(tenant_membership)
                self.assertIsNotNone(workspace_membership)

                assert workspace is not None
                assert tenant_membership is not None
                assert workspace_membership is not None
                assert user is not None

                self.assertEqual(workspace.id, bootstrap.default_workspace_id_for_tenant("tenant_default"))
                self.assertEqual(workspace.status, "active")
                self.assertTrue(workspace.is_default)
                self.assertTrue(user.is_platform_admin)
                self.assertTrue(user.can_create_workspace)
                self.assertEqual(tenant_membership.role, "owner")
                self.assertEqual(tenant_membership.status, "active")
                self.assertEqual(workspace_membership.role, "founder")
                self.assertEqual(workspace_membership.status, "active")

                context = resolve_auth_context(db, user)
                self.assertEqual(context.tenant_id, "tenant_default")
                self.assertEqual(context.workspace.id, workspace.id)
                self.assertEqual(context.workspace_membership.role, "founder")

    def test_init_db_is_idempotent_and_preserves_default_provider_relationship(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "idempotent-bootstrap.db"
            database_url = f"sqlite:///{db_path}"
            engine = _engine_for_url(database_url)
            self.addCleanup(engine.dispose)
            settings = self._settings(
                database_url=database_url,
                llm_base_url="https://llm.example.test/v1",
                llm_api_key="test-api-key",
            )

            with (
                patch.object(bootstrap, "engine", engine),
                patch.object(bootstrap, "get_settings", return_value=settings),
                patch.object(bootstrap, "_run_migrations", side_effect=lambda: Base.metadata.create_all(bind=engine)),
                patch.object(bootstrap, "encrypt_text", return_value="encrypted-api-key"),
                patch.object(bootstrap, "default_llm_model", return_value="gpt-test"),
            ):
                bootstrap.init_db()

                with Session(engine) as db:
                    workspace = db.scalar(select(Workspace).where(Workspace.is_default.is_(True)))
                    assert workspace is not None
                    db.add(
                        ModelProvider(
                            id="provider_custom_default_scope",
                            tenant_id="tenant_default",
                            workspace_id=None,
                            provider_type="openai_compatible",
                            name="Custom Provider",
                            base_url="https://custom.example.test/v1",
                            api_key_encrypted="encrypted-custom-key",
                            default_model="gpt-custom",
                            supported_models_json='["gpt-custom"]',
                            extra_headers_json="{}",
                            enabled=True,
                            is_default=False,
                            managed_by_system=False,
                        )
                    )
                    db.commit()

                bootstrap.init_db()

            with Session(engine) as db:
                tenant_count = db.scalar(select(func.count()).select_from(Tenant))
                user_count = db.scalar(select(func.count()).select_from(User))
                workspace_count = db.scalar(select(func.count()).select_from(Workspace))
                tenant_membership_count = db.scalar(select(func.count()).select_from(TenantMembership))
                workspace_membership_count = db.scalar(select(func.count()).select_from(WorkspaceMembership))
                provider_count = db.scalar(select(func.count()).select_from(ModelProvider))
                workspace = db.scalar(select(Workspace).where(Workspace.is_default.is_(True)))
                system_provider = db.get(ModelProvider, "provider_system_default")
                custom_provider = db.get(ModelProvider, "provider_custom_default_scope")

                self.assertEqual(tenant_count, 1)
                self.assertEqual(user_count, 1)
                self.assertEqual(workspace_count, 1)
                self.assertEqual(tenant_membership_count, 1)
                self.assertEqual(workspace_membership_count, 1)
                self.assertEqual(provider_count, 2)

                assert workspace is not None
                assert system_provider is not None
                assert custom_provider is not None

                self.assertTrue(system_provider.managed_by_system)
                self.assertIsNone(system_provider.workspace_id)
                self.assertEqual(system_provider.default_model, "gpt-test")
                self.assertEqual(workspace.default_provider_id, system_provider.id)
                self.assertEqual(custom_provider.workspace_id, workspace.id)

    def test_init_db_backfills_missing_default_workspace_membership_and_repairs_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "backfill-bootstrap.db"
            database_url = f"sqlite:///{db_path}"
            engine = _engine_for_url(database_url)
            self.addCleanup(engine.dispose)
            Base.metadata.create_all(bind=engine)

            default_workspace_id = bootstrap.default_workspace_id_for_tenant("tenant_default")
            with Session(engine) as db:
                tenant = Tenant(id="tenant_default", name="Default Tenant", status="disabled")
                user = User(
                    id="user_default",
                    tenant_id="tenant_default",
                    username="admin",
                    password_hash="legacy-secret",
                    is_active=False,
                )
                workspace = Workspace(
                    id=default_workspace_id,
                    tenant_id="tenant_default",
                    name="Default Workspace",
                    slug="default",
                    status="archived",
                    is_default=False,
                    created_by="user_default",
                    archived_at=datetime.utcnow(),
                    archived_by="user_default",
                )
                membership = TenantMembership(
                    id="tm_tenant_default_user_default",
                    tenant_id="tenant_default",
                    user_id="user_default",
                    role="member",
                    status="disabled",
                )
                db.add_all([tenant, user, workspace, membership])
                db.commit()

            self._run_init_db(engine, self._settings(database_url=database_url))

            with Session(engine) as db:
                tenant = db.get(Tenant, "tenant_default")
                user = db.get(User, "user_default")
                workspace = db.get(Workspace, default_workspace_id)
                tenant_membership = db.get(TenantMembership, "tm_tenant_default_user_default")
                workspace_membership = db.scalar(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == default_workspace_id,
                        WorkspaceMembership.user_id == "user_default",
                    )
                )

                assert tenant is not None
                assert user is not None
                assert workspace is not None
                assert tenant_membership is not None
                assert workspace_membership is not None

                self.assertEqual(tenant.status, "active")
                self.assertTrue(user.is_active)
                self.assertTrue(user.is_platform_admin)
                self.assertTrue(user.can_create_workspace)
                self.assertEqual(workspace.status, "active")
                self.assertTrue(workspace.is_default)
                self.assertIsNone(workspace.archived_at)
                self.assertIsNone(workspace.archived_by)
                self.assertEqual(tenant_membership.role, "owner")
                self.assertEqual(tenant_membership.status, "active")
                self.assertEqual(workspace_membership.role, "founder")
                self.assertEqual(workspace_membership.status, "active")

                context = resolve_auth_context(db, user)
                self.assertEqual(context.workspace_membership.role, "founder")

    def test_init_db_preserves_existing_founder_invariant_when_default_admin_membership_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "founder-invariant-bootstrap.db"
            database_url = f"sqlite:///{db_path}"
            engine = _engine_for_url(database_url)
            self.addCleanup(engine.dispose)
            Base.metadata.create_all(bind=engine)

            default_workspace_id = bootstrap.default_workspace_id_for_tenant("tenant_default")
            with Session(engine) as db:
                tenant = Tenant(id="tenant_default", name="Default Tenant", status="active")
                admin_user = User(
                    id="user_default",
                    tenant_id="tenant_default",
                    username="admin",
                    password_hash="secret",
                    is_active=True,
                )
                existing_founder = User(
                    id="user_existing_founder",
                    tenant_id="tenant_default",
                    username="existing_founder",
                    password_hash="secret",
                    is_active=True,
                )
                workspace = Workspace(
                    id=default_workspace_id,
                    tenant_id="tenant_default",
                    name="Default Workspace",
                    slug="default",
                    status="active",
                    is_default=True,
                    created_by="user_existing_founder",
                )
                db.add_all([tenant, admin_user, existing_founder, workspace])
                db.add_all(
                    [
                        TenantMembership(
                            id="tm_tenant_default_user_default",
                            tenant_id="tenant_default",
                            user_id="user_default",
                            role="owner",
                            status="active",
                        ),
                        TenantMembership(
                            id="tm_tenant_default_user_existing_founder",
                            tenant_id="tenant_default",
                            user_id="user_existing_founder",
                            role="admin",
                            status="active",
                        ),
                        WorkspaceMembership(
                            id="wm_existing_founder",
                            workspace_id=default_workspace_id,
                            user_id="user_existing_founder",
                            role="founder",
                            status="active",
                            permissions_override_json="{}",
                            created_by="user_existing_founder",
                        ),
                    ]
                )
                db.commit()

            self._run_init_db(engine, self._settings(database_url=database_url))

            with Session(engine) as db:
                admin_membership = db.scalar(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == default_workspace_id,
                        WorkspaceMembership.user_id == "user_default",
                    )
                )
                founder_memberships = db.scalars(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == default_workspace_id,
                        WorkspaceMembership.role == "founder",
                        WorkspaceMembership.status == "active",
                    )
                ).all()

                assert admin_membership is not None
                self.assertEqual(admin_membership.role, "admin")
                self.assertEqual(admin_membership.status, "active")
                self.assertEqual(len(founder_memberships), 1)
                self.assertEqual(founder_memberships[0].user_id, "user_existing_founder")

    def test_migration_config_uses_mysql_database_url_without_sqlite_special_case(self):
        mysql_url = "mysql+pymysql://pageindex:secret@127.0.0.1:3306/pageindex"

        class DummyConfig:
            def __init__(self, path: str):
                self.path = path
                self.options: dict[str, str] = {}

            def set_main_option(self, key: str, value: str) -> None:
                self.options[key] = value

        with (
            patch.object(bootstrap, "Config", DummyConfig),
            patch.object(bootstrap, "get_settings", return_value=self._settings(database_url=mysql_url)),
        ):
            config = bootstrap._migration_config()

        self.assertTrue(config.path.endswith("alembic.ini"))
        self.assertTrue(config.options["script_location"].endswith("/migrations"))
        self.assertEqual(config.options["sqlalchemy.url"], mysql_url)


if __name__ == "__main__":
    unittest.main()
