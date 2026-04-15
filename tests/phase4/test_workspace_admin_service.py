import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.principal import Principal
from app.models import User, Workspace, WorkspaceMembership
from app.services.workspace_admin_service import (
    _assert_assignable_role,
    _assert_manageable_target,
    archive_workspace,
    transfer_workspace_founder,
)

class TestWorkspaceAdminService(unittest.TestCase):
    def setUp(self):
        self.user_founder = User(id="user_founder")
        self.user_admin = User(id="user_admin")
        
        self.principal_founder = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role="founder",
            workspace_membership_status="active",
            workspace_permissions={"can_transfer_founder": True, "can_archive_workspace": True, "can_manage_members": True},
            user=self.user_founder,
        )

        self.principal_admin = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role="admin",
            workspace_membership_status="active",
            workspace_permissions={"can_manage_members": True},
            user=self.user_admin,
        )

    def test_founder_can_manage_non_founder_membership(self):
        # Founder managing a member
        target_membership = WorkspaceMembership(id="m_1", role="member")
        _assert_manageable_target(self.principal_founder, target_membership, desired_role="admin")
        _assert_manageable_target(self.principal_founder, target_membership, desired_role="guest")
        
        # Founder allocating
        _assert_assignable_role(self.principal_founder, role="admin")

    def test_admin_can_only_manage_member_or_guest(self):
        target_guest = WorkspaceMembership(id="m_2", role="guest")
        
        # Admin managing guest -> member
        _assert_manageable_target(self.principal_admin, target_guest, desired_role="member")
        
        # Admin assigning
        _assert_assignable_role(self.principal_admin, role="guest")
        _assert_assignable_role(self.principal_admin, role="member")

    def test_admin_cannot_manage_admin(self):
        target_admin = WorkspaceMembership(id="m_3", role="admin")
        
        with self.assertRaises(HTTPException) as ctx:
            _assert_manageable_target(self.principal_admin, target_admin, desired_role="member")
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx2:
            _assert_assignable_role(self.principal_admin, role="admin")
        self.assertEqual(ctx2.exception.status_code, 403)

    def test_founder_membership_cannot_be_managed_via_generic(self):
        target_founder = WorkspaceMembership(id="m_4", role="founder")
        target_member = WorkspaceMembership(id="m_5", role="member")

        with self.assertRaises(HTTPException) as ctx1:
            _assert_manageable_target(self.principal_founder, target_founder, desired_role="admin")
        self.assertIn("founder transfer", str(ctx1.exception.detail).lower())

        with self.assertRaises(HTTPException) as ctx2:
            _assert_manageable_target(self.principal_founder, target_member, desired_role="founder")
        self.assertIn("founder transfer", str(ctx2.exception.detail).lower())

    @patch("app.services.workspace_admin_service._get_workspace_for_admin_operation")
    @patch("app.services.workspace_admin_service.list_active_founder_memberships")
    @patch("app.services.workspace_admin_service._get_membership_user_or_404")
    def test_founder_transfer(self, mock_get_user, mock_list_founders, mock_get_ws):
        db = MagicMock()
        mock_ws = Workspace(id="ws_1")
        mock_get_ws.return_value = mock_ws
        
        current_founder = WorkspaceMembership(id="mem_1", user_id="user_founder", role="founder")
        target_member = WorkspaceMembership(id="mem_2", user_id="target_user", role="member", status="active")
        
        # list_active_founder_memberships called twice (before and after)
        mock_list_founders.side_effect = [[current_founder], [target_member]]
        
        db.scalar.return_value = target_member
        
        result = transfer_workspace_founder(
            db, 
            self.principal_founder, 
            "ws_1", 
            target_user_id="target_user"
        )
        
        self.assertEqual(current_founder.role, "admin")
        self.assertEqual(target_member.role, "founder")
        self.assertEqual(result["workspace_id"], "ws_1")

    @patch("app.services.workspace_admin_service._get_workspace_for_admin_operation")
    @patch("app.services.workspace_admin_service.list_active_founder_memberships")
    def test_founder_transfer_translates_db_founder_conflict(self, mock_list_founders, mock_get_ws):
        db = MagicMock()
        mock_get_ws.return_value = Workspace(id="ws_1")
        current_founder = WorkspaceMembership(id="mem_1", user_id="user_founder", role="founder", status="active")
        target_member = WorkspaceMembership(id="mem_2", user_id="target_user", role="member", status="active")
        mock_list_founders.return_value = [current_founder]
        db.scalar.return_value = target_member
        db.flush.side_effect = [None, IntegrityError("stmt", {}, Exception("active_founder_workspace_id"))]

        with self.assertRaises(HTTPException) as ctx:
            transfer_workspace_founder(db, self.principal_founder, "ws_1", target_user_id="target_user")

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("founder invariant", ctx.exception.detail)
        db.rollback.assert_called_once()

    @patch("app.services.workspace_admin_service._get_workspace_for_admin_operation")
    def test_default_workspace_archive_rejected(self, mock_get_ws):
        db = MagicMock()
        mock_ws = Workspace(id="ws_1", is_default=True)
        mock_get_ws.return_value = mock_ws
        
        with self.assertRaises(HTTPException) as ctx:
            archive_workspace(db, self.principal_founder, "ws_1")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Default workspace cannot be archived", ctx.exception.detail)

    @patch("app.services.workspace_admin_service._get_workspace_for_admin_operation")
    def test_non_default_workspace_archive_success(self, mock_get_ws):
        db = MagicMock()
        mock_ws = Workspace(id="ws_1", is_default=False, status="active")
        mock_get_ws.return_value = mock_ws
        
        result = archive_workspace(db, self.principal_founder, "ws_1")
        
        self.assertEqual(mock_ws.status, "archived")
        self.assertIsNotNone(mock_ws.archived_at)
        self.assertEqual(mock_ws.archived_by, "user_founder")
        self.assertEqual(result["status"], "archived")

if __name__ == "__main__":
    unittest.main()
