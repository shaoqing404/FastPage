import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import sqlalchemy as sa

from scripts.phase47.runtime_reset import REPO_OWNED_SCHEMA_TABLES

sys.modules.setdefault("dotenv", MagicMock())


PHASE3_COMPLIANCE_REVISION = "20260407_0005"
PHASE4_BACKFILL_REVISION = "20260410_0007"
PHASE45_INVARIANT_REVISION = "20260415_0008"
CURRENT_MIGRATION_HEAD = "20260515_0015"
EXPECTED_SCHEMA_TABLES = set(REPO_OWNED_SCHEMA_TABLES)


class TestPhase4MigrationsSmoke(unittest.TestCase):
    def setUp(self):
        try:
            from alembic.config import Config
            self.Config = Config
            from alembic import command
            self.command = command
            from alembic.script import ScriptDirectory
            self.ScriptDirectory = ScriptDirectory
            from app.core.config import get_settings
            self.get_settings = get_settings
        except ImportError:
            self.skipTest("alembic is not installed. Skipping migration smoke test.")

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "phase4_migration_smoke.db"
        self.db_url = f"sqlite:///{db_path}"
        previous_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = self.db_url
        self.get_settings.cache_clear()

        def restore_database_url() -> None:
            if previous_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_database_url
            self.get_settings.cache_clear()

        self.addCleanup(restore_database_url)
        self.alembic_cfg = self.Config("alembic.ini")
        self.alembic_cfg.set_main_option("sqlalchemy.url", self.db_url)

    def test_migration_script_directory_can_list_heads(self):
        script = self.ScriptDirectory.from_config(self.alembic_cfg)
        self.assertIn(CURRENT_MIGRATION_HEAD, script.get_heads())

    def test_local_phase4_upgrade_downgrade(self):
        # Build the pre-Phase-4 schema for real instead of stamping an empty DB.
        self.command.upgrade(self.alembic_cfg, PHASE3_COMPLIANCE_REVISION)

        # Upgrade to the Phase 4 head.
        self.command.upgrade(self.alembic_cfg, CURRENT_MIGRATION_HEAD)

        # Downgrade back to the Phase 3 checkpoint to exercise downgrade paths.
        self.command.downgrade(self.alembic_cfg, PHASE3_COMPLIANCE_REVISION)

        # Upgrade again to verify the chain is repeatable.
        self.command.upgrade(self.alembic_cfg, CURRENT_MIGRATION_HEAD)

        engine = sa.create_engine(self.db_url, future=True)
        self.addCleanup(engine.dispose)
        inspector = sa.inspect(engine)
        self.assertEqual(set(inspector.get_table_names()), EXPECTED_SCHEMA_TABLES)
        self.assertIn("active_founder_workspace_id", {col["name"] for col in inspector.get_columns("workspace_memberships")})
        self.assertIn("pending_normalized_email", {col["name"] for col in inspector.get_columns("workspace_invites")})
        self.assertIn("must_change_password", {col["name"] for col in inspector.get_columns("users")})
        self.assertIn("uploaded_via_kb_id", {col["name"] for col in inspector.get_columns("documents")})
        for column_name in (
            "routing_index_status",
            "routing_index_path",
            "routing_index_error",
            "routing_index_version",
        ):
            self.assertIn(column_name, {col["name"] for col in inspector.get_columns("document_versions")})
        for column_name in (
            "document_id",
            "version_id",
            "node_id",
            "parent_node_id",
            "depth",
            "title",
            "breadcrumb",
            "page_start",
            "page_end",
            "route_summary",
            "contrastive_summary",
            "aliases_json",
            "keywords_json",
            "manual_profile_text",
            "created_at",
            "updated_at",
        ):
            self.assertIn(column_name, {col["name"] for col in inspector.get_columns("document_routing_nodes")})
        self.assertTrue(any(index["name"] == "uq_workspace_memberships_active_founder_workspace_id" for index in inspector.get_indexes("workspace_memberships")))
        self.assertTrue(any(index["name"] == "uq_workspace_invites_workspace_pending_normalized_email" for index in inspector.get_indexes("workspace_invites")))
        self.assertTrue(any(index["name"] == "ix_users_email" and index.get("unique", False) for index in inspector.get_indexes("users")))
        self.assertTrue(any(index["name"] == "ix_documents_uploaded_via_kb_id" for index in inspector.get_indexes("documents")))
        self.assertTrue(any(index["name"] == "ix_document_versions_routing_index_status" for index in inspector.get_indexes("document_versions")))
        self.assertTrue(any(constraint["name"] == "uq_document_routing_nodes_version_node" for constraint in inspector.get_unique_constraints("document_routing_nodes")))
        self.assertTrue(any(index["name"] == "ix_document_routing_nodes_document_version" for index in inspector.get_indexes("document_routing_nodes")))
        self.assertTrue(any(index["name"] == "ix_document_routing_nodes_version_parent_node" for index in inspector.get_indexes("document_routing_nodes")))
        self.assertTrue(any(index["name"] == "ix_document_routing_nodes_version_depth" for index in inspector.get_indexes("document_routing_nodes")))

        self.assertTrue(True, "Migration smoke test completed successfully.")

    def test_phase46_doc_kb_origin_upgrade_tolerates_existing_column_and_index(self):
        self.command.upgrade(self.alembic_cfg, PHASE45_INVARIANT_REVISION)

        engine = sa.create_engine(self.db_url, future=True)
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            conn.execute(sa.text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"))
            conn.execute(sa.text("ALTER TABLE documents ADD COLUMN uploaded_via_kb_id VARCHAR(64)"))
            conn.execute(sa.text("CREATE INDEX ix_documents_uploaded_via_kb_id ON documents (uploaded_via_kb_id)"))

        self.command.upgrade(self.alembic_cfg, CURRENT_MIGRATION_HEAD)

        with engine.begin() as conn:
            version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
        self.assertEqual(version, CURRENT_MIGRATION_HEAD)

    def test_phase45_upgrade_rejects_duplicate_normalized_user_emails(self):
        self.command.upgrade(self.alembic_cfg, PHASE4_BACKFILL_REVISION)

        engine = sa.create_engine(self.db_url, future=True)
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            now = "2026-04-15 00:00:00"
            conn.execute(
                sa.text(
                    """
                    INSERT INTO tenants (id, name, status, created_at)
                    VALUES (:tenant_id, :name, :status, :created_at)
                    """
                ),
                {"tenant_id": "tenant_test", "name": "Tenant Test", "status": "active", "created_at": now},
            )
            conn.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        id, tenant_id, username, email, password_hash, can_create_workspace,
                        is_platform_admin, is_active, created_at, updated_at
                    )
                    VALUES
                        (:id1, :tenant_id, :username1, :email1, :password_hash, 0, 0, 1, :created_at, :updated_at),
                        (:id2, :tenant_id, :username2, :email2, :password_hash, 0, 0, 1, :created_at, :updated_at)
                    """
                ),
                {
                    "id1": "user_one",
                    "id2": "user_two",
                    "tenant_id": "tenant_test",
                    "username1": "user_one",
                    "username2": "user_two",
                    "email1": "Founder@example.com",
                    "email2": " founder@example.com ",
                    "password_hash": "secret",
                    "created_at": now,
                    "updated_at": now,
                },
            )

        with self.assertRaises(Exception) as ctx:
            self.command.upgrade(self.alembic_cfg, PHASE45_INVARIANT_REVISION)

        self.assertIn("unique normalized user emails", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
