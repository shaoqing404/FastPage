import os
import unittest
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.db import Base
from app.core.principal import Principal
from app.models import Tenant, TenantMembership, User, Workspace, WorkspaceMembership
from app.services.workspace_admin_service import create_workspace


@dataclass
class WorkspaceCreatePayload:
    name: str
    slug: str | None = None


class TestWorkspaceCreateService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

        with Session(self.engine) as db:
            tenant = Tenant(id="tenant_1", name="Tenant 1", status="active")
            creator = User(
                id="user_creator",
                tenant_id="tenant_legacy",
                username="creator",
                email="creator@example.com",
                password_hash="secret",
                can_create_workspace=True,
                is_platform_admin=False,
                is_active=True,
            )
            blocked = User(
                id="user_blocked",
                tenant_id="tenant_legacy",
                username="blocked",
                email="blocked@example.com",
                password_hash="secret",
                can_create_workspace=False,
                is_platform_admin=False,
                is_active=True,
            )
            platform_admin = User(
                id="user_platform_admin",
                tenant_id="tenant_legacy",
                username="platform_admin",
                email="platform-admin@example.com",
                password_hash="secret",
                can_create_workspace=False,
                is_platform_admin=True,
                is_active=True,
            )
            db.add_all([tenant, creator, blocked, platform_admin])
            db.add_all(
                [
                    TenantMembership(
                        id="tm_creator",
                        tenant_id="tenant_1",
                        user_id="user_creator",
                        role="member",
                        status="active",
                    ),
                    TenantMembership(
                        id="tm_blocked",
                        tenant_id="tenant_1",
                        user_id="user_blocked",
                        role="member",
                        status="active",
                    ),
                    TenantMembership(
                        id="tm_platform_admin",
                        tenant_id="tenant_1",
                        user_id="user_platform_admin",
                        role="admin",
                        status="active",
                    ),
                ]
            )
            db.commit()

    def _principal(self, user_id: str) -> Principal:
        with Session(self.engine) as db:
            user = db.get(User, user_id)
            assert user is not None
            return Principal(
                kind="session",
                tenant_id="tenant_1",
                workspace_id="ws_default",
                tenant_membership_role="member",
                tenant_membership_status="active",
                workspace_membership_role="member",
                workspace_membership_status="active",
                workspace_permissions={},
                user=user,
            )

    def test_create_workspace_persists_founder_membership_and_normalizes_slug(self):
        with Session(self.engine) as db:
            workspace = create_workspace(
                db,
                self._principal("user_creator"),
                WorkspaceCreatePayload(name="  New Workspace  "),
            )

            self.assertEqual(workspace.tenant_id, "tenant_1")
            self.assertEqual(workspace.name, "New Workspace")
            self.assertEqual(workspace.slug, "new-workspace")
            self.assertEqual(workspace.status, "active")
            self.assertFalse(workspace.is_default)

            founder_membership = db.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace.id,
                    WorkspaceMembership.user_id == "user_creator",
                )
            )
            self.assertIsNotNone(founder_membership)
            assert founder_membership is not None
            self.assertEqual(founder_membership.role, "founder")
            self.assertEqual(founder_membership.status, "active")

    def test_create_workspace_rejects_users_without_create_permission(self):
        with Session(self.engine) as db:
            with self.assertRaises(HTTPException) as ctx:
                create_workspace(
                    db,
                    self._principal("user_blocked"),
                    WorkspaceCreatePayload(name="Denied Workspace"),
                )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("not allowed", ctx.exception.detail)

    def test_create_workspace_allows_platform_admin_bypass(self):
        with Session(self.engine) as db:
            workspace = create_workspace(
                db,
                self._principal("user_platform_admin"),
                WorkspaceCreatePayload(name="Platform Created"),
            )

            self.assertEqual(workspace.slug, "platform-created")
            founder_membership = db.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace.id,
                    WorkspaceMembership.user_id == "user_platform_admin",
                )
            )
            self.assertIsNotNone(founder_membership)

    def test_create_workspace_rejects_duplicate_slug_in_same_tenant(self):
        with Session(self.engine) as db:
            db.add(
                Workspace(
                    id="ws_existing",
                    tenant_id="tenant_1",
                    name="Existing",
                    slug="existing-space",
                    status="active",
                    is_default=False,
                    created_by="user_creator",
                )
            )
            db.commit()

            with self.assertRaises(HTTPException) as ctx:
                create_workspace(
                    db,
                    self._principal("user_creator"),
                    WorkspaceCreatePayload(name="Another", slug=" existing-space "),
                )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("slug already exists", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
