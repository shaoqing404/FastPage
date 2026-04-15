import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())

from app.core.auth import ActiveTenantContext, AuthContext
from app.core.db import get_db
from app.models import TenantMembership, User, Workspace, WorkspaceMembership
from app.services.workspace_membership_service import resolve_auth_tenant_membership


AUTH_ROUTER_MODULE_NAME = "phase45_auth_router_under_test"
AUTH_ROUTER_PATH = Path(__file__).resolve().parents[2] / "app" / "api" / "routers" / "auth.py"
auth_router_spec = importlib.util.spec_from_file_location(AUTH_ROUTER_MODULE_NAME, AUTH_ROUTER_PATH)
auth_router_module = importlib.util.module_from_spec(auth_router_spec)
assert auth_router_spec is not None and auth_router_spec.loader is not None
sys.modules[AUTH_ROUTER_MODULE_NAME] = auth_router_module
auth_router_spec.loader.exec_module(auth_router_module)
auth_router = auth_router_module.router


class TestAuthContextContract(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(auth_router)
        self.db = MagicMock()
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.addCleanup(self.app.dependency_overrides.clear)

    def _client(self) -> TestClient:
        return TestClient(self.app)

    def _build_auth_context(self, *, tenant_id: str, workspace_id: str) -> AuthContext:
        user = User(
            id="user_1",
            tenant_id="tenant_legacy",
            username="tester",
            email="tester@example.com",
            can_create_workspace=False,
            is_platform_admin=False,
            is_active=True,
        )
        workspace = Workspace(
            id=workspace_id,
            tenant_id=tenant_id,
            name="Workspace",
            slug="workspace",
            status="active",
            is_default=False,
        )
        tenant_membership = TenantMembership(
            id="tm_1",
            tenant_id=tenant_id,
            role="member",
            status="active",
        )
        workspace_membership = WorkspaceMembership(
            id="wm_1",
            workspace_id=workspace_id,
            user_id=user.id,
            role="member",
            status="active",
            permissions_override_json="{}",
        )
        return AuthContext(
            user=user,
            tenant_id=tenant_id,
            workspace=workspace,
            tenant_membership=tenant_membership,
            workspace_membership=workspace_membership,
            workspace_permissions={"can_view_workspace": True},
        )

    @patch("app.services.workspace_membership_service.resolve_active_tenant_membership")
    @patch("app.services.workspace_membership_service.resolve_workspace_tenant_id_hint")
    def test_resolve_auth_tenant_membership_prefers_workspace_hint_over_compat_field(
        self,
        mock_workspace_hint,
        mock_resolve_membership,
    ):
        db = MagicMock()
        mock_workspace_hint.return_value = "tenant_target"

        resolve_auth_tenant_membership(
            db,
            "user_1",
            workspace_id="ws_target",
            compat_tenant_id="tenant_legacy",
        )

        mock_resolve_membership.assert_called_once_with(
            db,
            "user_1",
            tenant_id="tenant_target",
            fallback_tenant_id=None,
        )

    @patch("app.services.workspace_membership_service.resolve_active_tenant_membership")
    def test_resolve_auth_tenant_membership_uses_compat_field_only_without_explicit_hints(
        self,
        mock_resolve_membership,
    ):
        db = MagicMock()

        resolve_auth_tenant_membership(
            db,
            "user_1",
            compat_tenant_id="tenant_legacy",
        )

        mock_resolve_membership.assert_called_once_with(
            db,
            "user_1",
            tenant_id=None,
            fallback_tenant_id="tenant_legacy",
        )

    @patch(f"{AUTH_ROUTER_MODULE_NAME}.create_access_token", return_value="token-current")
    @patch(f"{AUTH_ROUTER_MODULE_NAME}.resolve_session_auth_context")
    def test_get_context_returns_current_contract(self, mock_resolve_session_auth_context, _mock_create_access_token):
        auth_context = self._build_auth_context(tenant_id="tenant_target", workspace_id="ws_target")
        mock_resolve_session_auth_context.return_value = auth_context
        self.db.scalars.return_value.all.return_value = [auth_context.tenant_membership]

        with self._client() as client:
            response = client.get(
                "/api/v1/auth/context",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["user"]["tenant_id"], "tenant_target")
        self.assertEqual(payload["workspace"]["id"], "ws_target")
        self.assertEqual(payload["tenant_membership"]["tenant_id"], "tenant_target")
        self.assertEqual(payload["workspace_membership"]["workspace_id"], "ws_target")

    @patch(f"{AUTH_ROUTER_MODULE_NAME}.create_access_token", return_value="token-switched")
    @patch(f"{AUTH_ROUTER_MODULE_NAME}.resolve_auth_context")
    @patch(f"{AUTH_ROUTER_MODULE_NAME}.require_active_session_tenant_context")
    def test_switch_context_uses_active_tenant_membership_not_user_compat_tenant(
        self,
        mock_require_active_session_tenant_context,
        mock_resolve_auth_context,
        _mock_create_access_token,
    ):
        user = User(
            id="user_1",
            tenant_id="tenant_legacy",
            username="tester",
            email="tester@example.com",
            is_active=True,
        )
        tenant_context = ActiveTenantContext(
            user=user,
            tenant_membership=TenantMembership(
                id="tm_active",
                tenant_id="tenant_target",
                role="member",
                status="active",
            ),
        )
        mock_require_active_session_tenant_context.return_value = tenant_context
        mock_resolve_auth_context.return_value = self._build_auth_context(
            tenant_id="tenant_target",
            workspace_id="ws_target",
        )
        self.db.scalars.return_value.all.return_value = [tenant_context.tenant_membership]

        with self._client() as client:
            response = client.post(
                "/api/v1/auth/context/switch",
                json={"workspace_id": "ws_target"},
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(response.status_code, 200)
        mock_resolve_auth_context.assert_called_once_with(
            self.db,
            user,
            tenant_id="tenant_target",
            workspace_id="ws_target",
        )


if __name__ == "__main__":
    unittest.main()
