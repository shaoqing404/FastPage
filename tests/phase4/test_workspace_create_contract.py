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

from app.core.principal import Principal
from app.models import TenantMembership, User, Workspace, WorkspaceMembership


WORKSPACES_ROUTER_MODULE_NAME = "phase45_workspaces_router_under_test"
WORKSPACES_ROUTER_PATH = Path(__file__).resolve().parents[2] / "app" / "api" / "routers" / "workspaces.py"
workspaces_router_spec = importlib.util.spec_from_file_location(WORKSPACES_ROUTER_MODULE_NAME, WORKSPACES_ROUTER_PATH)
workspaces_router_module = importlib.util.module_from_spec(workspaces_router_spec)
assert workspaces_router_spec is not None and workspaces_router_spec.loader is not None
sys.modules[WORKSPACES_ROUTER_MODULE_NAME] = workspaces_router_module
workspaces_router_spec.loader.exec_module(workspaces_router_module)
workspaces_router = workspaces_router_module.router


class TestWorkspaceCreateContract(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(workspaces_router)
        self.db = MagicMock()
        self.principal = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_default",
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role="member",
            workspace_membership_status="active",
            workspace_permissions={},
            user=User(
                id="user_1",
                tenant_id="tenant_legacy",
                username="creator",
                email="creator@example.com",
                can_create_workspace=True,
                is_platform_admin=False,
                is_active=True,
            ),
        )
        self.app.dependency_overrides[workspaces_router_module.get_db] = lambda: self.db
        self.app.dependency_overrides[workspaces_router_module.get_current_principal] = lambda: self.principal
        self.addCleanup(self.app.dependency_overrides.clear)

    def _client(self) -> TestClient:
        return TestClient(self.app)

    def _response_payload(self) -> dict[str, object]:
        return {
            "access_token": "token-new-workspace",
            "token_type": "bearer",
            "user": {
                "id": "user_1",
                "tenant_id": "tenant_1",
                "workspace_id": "ws_new",
                "username": "creator",
                "email": "creator@example.com",
                "can_create_workspace": True,
                "is_platform_admin": False,
                "membership_role": "founder",
                "tenant_membership_role": "member",
                "tenant_membership_status": "active",
                "workspace_membership_role": "founder",
                "workspace_membership_status": "active",
            },
            "workspace": {
                "id": "ws_new",
                "tenant_id": "tenant_1",
                "name": "New Workspace",
                "slug": "new-workspace",
                "status": "active",
                "is_default": False,
            },
            "tenant_membership": {
                "id": "tm_1",
                "tenant_id": "tenant_1",
                "role": "member",
                "status": "active",
            },
            "workspace_membership": {
                "id": "wm_new",
                "workspace_id": "ws_new",
                "user_id": "user_1",
                "role": "founder",
                "status": "active",
                "permissions_override": {},
                "permissions": {"can_manage_members": True},
            },
            "memberships": [
                {
                    "id": "tm_1",
                    "tenant_id": "tenant_1",
                    "role": "member",
                    "status": "active",
                }
            ],
        }

    @patch(f"{WORKSPACES_ROUTER_MODULE_NAME}.build_auth_response_payload")
    @patch(f"{WORKSPACES_ROUTER_MODULE_NAME}.resolve_auth_context")
    @patch(f"{WORKSPACES_ROUTER_MODULE_NAME}.create_workspace")
    def test_post_workspaces_returns_new_active_context(
        self,
        mock_create_workspace,
        mock_resolve_auth_context,
        mock_build_auth_response_payload,
    ):
        created_workspace = Workspace(
            id="ws_new",
            tenant_id="tenant_1",
            name="New Workspace",
            slug="new-workspace",
            status="active",
            is_default=False,
        )
        mock_create_workspace.return_value = created_workspace
        mock_resolve_auth_context.return_value = MagicMock(
            user=self.principal.user,
            tenant_id="tenant_1",
            tenant_membership=TenantMembership(id="tm_1", tenant_id="tenant_1", role="member", status="active"),
            workspace=created_workspace,
            workspace_membership=WorkspaceMembership(
                id="wm_new",
                workspace_id="ws_new",
                user_id="user_1",
                role="founder",
                status="active",
                permissions_override_json="{}",
            ),
            workspace_permissions={"can_manage_members": True},
        )
        mock_build_auth_response_payload.return_value = self._response_payload()

        with self._client() as client:
            response = client.post(
                "/api/v1/workspaces",
                json={"name": "New Workspace"},
            )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["access_token"], "token-new-workspace")
        self.assertEqual(payload["workspace"]["id"], "ws_new")
        self.assertEqual(payload["user"]["workspace_id"], "ws_new")
        self.assertEqual(payload["workspace_membership"]["role"], "founder")
        mock_resolve_auth_context.assert_called_once_with(
            self.db,
            self.principal.user,
            tenant_id="tenant_1",
            workspace_id="ws_new",
        )


if __name__ == "__main__":
    unittest.main()
