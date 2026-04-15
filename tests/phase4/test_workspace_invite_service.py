import sys
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

# Stub jwt before app imports to avoid dependency errors in minimal environments
sys.modules["jwt"] = MagicMock()

from fastapi import HTTPException
from app.core.principal import Principal
from app.models import User, Workspace, WorkspaceInvite, WorkspaceMembership, TenantMembership
from app.services.workspace_invite_service import (
    _assert_invite_role_allowed,
    _assert_revoke_role_allowed,
    accept_workspace_invite,
    _ensure_active_tenant_membership,
    _upsert_workspace_membership,
)

class TestWorkspaceInviteService(unittest.TestCase):
    def setUp(self):
        self.user_founder = User(id="user_founder")
        self.user_admin = User(id="user_admin")
        self.user_session = User(id="user_session", email="foo@example.com", tenant_id="tenant_old")

        self.principal_founder = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role="founder",
            workspace_membership_status="active",
            workspace_permissions={},
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
            workspace_permissions={"can_manage_invites": True},
            user=self.user_admin,
        )

    def test_admin_cannot_create_or_revoke_admin_invite(self):
        with self.assertRaises(HTTPException) as ctx:
            _assert_invite_role_allowed(self.principal_admin, "admin")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("only invite member or guest", str(ctx.exception.detail))

        # Can invite member
        _assert_invite_role_allowed(self.principal_admin, "member")

        # Founder can invite admin
        _assert_invite_role_allowed(self.principal_founder, "admin")

        invite_admin = WorkspaceInvite(id="inv_1", role="admin")
        with self.assertRaises(HTTPException) as ctx2:
            _assert_revoke_role_allowed(self.principal_admin, invite_admin)
        self.assertEqual(ctx2.exception.status_code, 403)
        self.assertIn("revoke member or guest", str(ctx2.exception.detail))

    @patch("app.core.auth.resolve_auth_context")
    @patch("app.core.auth.create_access_token")
    @patch("app.services.workspace_invite_service._ensure_active_tenant_membership")
    @patch("app.services.workspace_invite_service._upsert_workspace_membership")
    def test_accept_workspace_invite_handoff_and_validation(
        self, mock_upsert, mock_ensure, mock_create_token, mock_resolve_context
    ):
        db = MagicMock()
        
        invite = WorkspaceInvite(
            id="inv_1", 
            workspace_id="ws_1", 
            email="foo@example.com", 
            status="pending",
            expires_at=datetime.utcnow() + datetime.timedelta(days=1) if hasattr(datetime, "timedelta") else datetime.fromtimestamp(datetime.utcnow().timestamp() + 86400),
            role="member",
            permissions_override_json="{}"
        )
        workspace = Workspace(id="ws_1", tenant_id="tenant_target", status="active", is_default=False)
        db.get.side_effect = lambda model, oid: invite if model == WorkspaceInvite else workspace
        
        # Mocks for post-accept
        mock_auth_ctx = MagicMock()
        mock_auth_ctx.workspace = workspace
        mock_auth_ctx.tenant_membership = TenantMembership(id="tm_1", tenant_id="tenant_target", role="member", status="active")
        mock_auth_ctx.workspace_membership = WorkspaceMembership(id="wm_1", workspace_id="ws_1", user_id="user_session", role="member", status="active", permissions_override_json="{}")
        mock_auth_ctx.workspace_permissions = {}
        mock_resolve_context.return_value = mock_auth_ctx
        mock_create_token.return_value = "new_stub_token"

        result = accept_workspace_invite(db, self.user_session, "inv_1")
        
        # Verify tenant handoff
        self.assertEqual(self.user_session.tenant_id, "tenant_target")
        self.assertEqual(result["access_token"], "new_stub_token")
        self.assertEqual(result["workspace"]["id"], "ws_1")
        self.assertEqual(invite.status, "accepted")

    def test_accept_duplicate_email_validation(self):
        db = MagicMock()
        invite = WorkspaceInvite(
            id="inv_1", 
            workspace_id="ws_1", 
            email="bar@example.com", 
            status="pending",
            expires_at=datetime.fromtimestamp(2000000000),
            role="member"
        )
        workspace = Workspace(id="ws_1", tenant_id="tenant_target", status="active")
        db.get.side_effect = lambda model, oid: invite if model == WorkspaceInvite else workspace

        # mismatch
        with self.assertRaises(HTTPException) as ctx:
            accept_workspace_invite(db, self.user_session, "inv_1")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("email does not match", str(ctx.exception.detail))

    def test_accept_invalid_workspace_or_invite_state(self):
        db = MagicMock()
        invite = WorkspaceInvite(
            id="inv_1", 
            workspace_id="ws_1", 
            email="foo@example.com", 
            status="revoked",
            expires_at=datetime.fromtimestamp(2000000000),
            role="member"
        )
        db.get.return_value = invite
        with self.assertRaises(HTTPException) as ctx:
            accept_workspace_invite(db, self.user_session, "inv_1")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("revoked", str(ctx.exception.detail))

    def test_upsert_workspace_membership(self):
        db = MagicMock()
        user = User(id="user_1")
        workspace = Workspace(id="ws_1")
        invite = WorkspaceInvite(id="inv_1", role="member", permissions_override_json="{}")

        # 1. Existing active -> Conflict
        existing_active = WorkspaceMembership(id="wm_1", status="active")
        db.scalar.return_value = existing_active
        with self.assertRaises(HTTPException) as ctx:
            _upsert_workspace_membership(db, user, workspace, invite, now=datetime.utcnow())
        self.assertEqual(ctx.exception.status_code, 409)

        # 2. Existing removed -> Reactivate
        existing_removed = WorkspaceMembership(id="wm_2", status="removed")
        db.scalar.return_value = existing_removed
        res = _upsert_workspace_membership(db, user, workspace, invite, now=datetime.utcnow())
        self.assertEqual(res.status, "active")
        self.assertEqual(res.role, "member")

    @patch("app.services.workspace_invite_service._get_workspace_for_invite_admin")
    def test_create_workspace_invite_unregistered_email_and_duplicates(self, mock_get_ws):
        from app.services.workspace_invite_service import create_workspace_invite
        from dataclasses import dataclass

        @dataclass
        class Payload:
            email: str
            role: str
            permissions_override: dict
            expires_at: datetime = None

        db = MagicMock()
        mock_ws = Workspace(id="ws_1", tenant_id="tenant_1")
        mock_get_ws.return_value = mock_ws
        
        # Test 1: create for unregistered email (basic create success)
        db.scalar.return_value = None  # No duplicate
        
        payload = Payload(email=" NEW@example.com ", role="member", permissions_override={})
        result = create_workspace_invite(db, self.principal_admin, "ws_1", payload)
        
        # Normalized email check
        self.assertEqual(result["email"], "new@example.com")
        self.assertEqual(result["role"], "member")
        self.assertEqual(result["status"], "pending")
        
        # Test 2: duplicate pending invite 409
        # Mock database to return an existing pending invite that hasn't expired
        existing_pending = WorkspaceInvite(
            id="inv_2", 
            email="new@example.com", 
            status="pending", 
            expires_at=datetime.fromtimestamp(2000000000)
        )
        db.scalar.return_value = existing_pending
        
        with self.assertRaises(HTTPException) as ctx:
            create_workspace_invite(db, self.principal_admin, "ws_1", payload)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("already exists", str(ctx.exception.detail))

if __name__ == "__main__":
    unittest.main()
