import os
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.db import Base
from app.models import Tenant, User, Workspace, WorkspaceInvite, WorkspaceMembership


class TestPhase45InvariantConstraints(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

        with Session(self.engine) as db:
            tenant = Tenant(id="tenant_1", name="Tenant 1", status="active")
            founder = User(
                id="user_founder",
                tenant_id=tenant.id,
                username="founder",
                email=" Founder@Example.com ",
                password_hash="secret",
                is_active=True,
            )
            member = User(
                id="user_member",
                tenant_id=tenant.id,
                username="member",
                email="member@example.com",
                password_hash="secret",
                is_active=True,
            )
            guest = User(
                id="user_guest",
                tenant_id=tenant.id,
                username="guest",
                email="guest@example.com",
                password_hash="secret",
                is_active=True,
            )
            workspace = Workspace(
                id="ws_1",
                tenant_id=tenant.id,
                name="Workspace 1",
                slug="workspace-1",
                status="active",
                is_default=False,
                created_by=founder.id,
            )
            db.add_all([tenant, founder, member, guest, workspace])
            db.commit()

    def test_user_email_is_normalized_and_unique(self):
        with Session(self.engine) as db:
            founder = db.get(User, "user_founder")
            self.assertEqual(founder.email, "founder@example.com")

            duplicate = User(
                id="user_duplicate",
                tenant_id="tenant_1",
                username="duplicate",
                email=" founder@example.com ",
                password_hash="secret",
                is_active=True,
            )
            db.add(duplicate)
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_active_founder_unique_index_allows_only_one_active_founder(self):
        with Session(self.engine) as db:
            founder_membership = WorkspaceMembership(
                id="wm_founder",
                workspace_id="ws_1",
                user_id="user_founder",
                role="founder",
                status="active",
                permissions_override_json="{}",
                created_by="user_founder",
            )
            removed_founder = WorkspaceMembership(
                id="wm_removed_founder",
                workspace_id="ws_1",
                user_id="user_member",
                role="founder",
                status="removed",
                permissions_override_json="{}",
                created_by="user_founder",
            )
            db.add_all([founder_membership, removed_founder])
            db.commit()

        with Session(self.engine) as db:
            active_founder_conflict = WorkspaceMembership(
                id="wm_conflict_founder",
                workspace_id="ws_1",
                user_id="user_guest",
                role="founder",
                status="active",
                permissions_override_json="{}",
                created_by="user_founder",
            )
            db.add(active_founder_conflict)
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_pending_invite_unique_index_is_normalized_and_status_scoped(self):
        with Session(self.engine) as db:
            historical_invite = WorkspaceInvite(
                id="invite_revoked",
                workspace_id="ws_1",
                email="Invitee@example.com",
                role="member",
                permissions_override_json="{}",
                status="revoked",
                invited_by="user_founder",
                expires_at=datetime.utcnow(),
            )
            pending_invite = WorkspaceInvite(
                id="invite_pending",
                workspace_id="ws_1",
                email=" Invitee@example.com ",
                role="member",
                permissions_override_json="{}",
                status="pending",
                invited_by="user_founder",
                expires_at=datetime.utcnow(),
            )
            db.add_all([historical_invite, pending_invite])
            db.commit()

            self.assertEqual(pending_invite.email, "invitee@example.com")

        with Session(self.engine) as db:
            conflicting_pending_invite = WorkspaceInvite(
                id="invite_conflict",
                workspace_id="ws_1",
                email="invitee@example.com",
                role="guest",
                permissions_override_json="{}",
                status="pending",
                invited_by="user_founder",
                expires_at=datetime.utcnow(),
            )
            db.add(conflicting_pending_invite)
            with self.assertRaises(IntegrityError):
                db.commit()


if __name__ == "__main__":
    unittest.main()
