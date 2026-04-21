import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())

from app.api.routers import auth as auth_router_module
from app.api.routers import platform as platform_router_module
from app.api.routers import workspace_invites as workspace_invites_router_module
from app.api.routers import workspaces as workspaces_router_module
from app.core.auth import ActiveTenantContext
from app.core.db import Base
from app.core.principal import Principal
from app.models import Tenant, TenantMembership, User, Workspace, WorkspaceInvite, WorkspaceMembership
from app.services.workspace_access_service import resolve_workspace_capabilities


class TestPhase47ApiVerification(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self._seed_data()

        self.token_patcher = patch("app.core.auth.create_access_token", return_value="phase47-token")
        self.token_patcher.start()
        self.addCleanup(self.token_patcher.stop)

        self.app = FastAPI()
        self.app.include_router(auth_router_module.router)
        self.app.include_router(platform_router_module.router)
        self.app.include_router(workspaces_router_module.router)
        self.app.include_router(workspace_invites_router_module.router)

        self.app.dependency_overrides[auth_router_module.get_db] = self._override_get_db
        self.app.dependency_overrides[platform_router_module.get_db] = self._override_get_db
        self.app.dependency_overrides[workspaces_router_module.get_db] = self._override_get_db
        self.app.dependency_overrides[workspace_invites_router_module.get_db] = self._override_get_db
        self.addCleanup(self.app.dependency_overrides.clear)

    def _seed_data(self) -> None:
        now = datetime.utcnow()
        with Session(self.engine) as db:
            db.add_all(
                [
                    Tenant(id="tenant_1", name="Tenant One", status="active", created_at=now),
                    Tenant(id="tenant_2", name="Tenant Two", status="active", created_at=now),
                ]
            )
            db.commit()

            db.add_all(
                [
                    User(
                        id="user_platform_admin",
                        tenant_id="tenant_1",
                        username="platform_admin",
                        email="platform-admin@example.com",
                        password_hash="secret",
                        is_platform_admin=True,
                        can_create_workspace=True,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    User(
                        id="user_alice",
                        tenant_id="tenant_2",
                        username="alice",
                        email="alice@example.com",
                        password_hash="secret",
                        is_platform_admin=False,
                        can_create_workspace=True,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    User(
                        id="user_bob",
                        tenant_id="tenant_1",
                        username="bob",
                        email="bob@example.com",
                        password_hash="secret",
                        is_platform_admin=False,
                        can_create_workspace=False,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    User(
                        id="user_ops_admin",
                        tenant_id="tenant_1",
                        username="ops_admin",
                        email="ops-admin@example.com",
                        password_hash="secret",
                        is_platform_admin=False,
                        can_create_workspace=False,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    User(
                        id="user_invited",
                        tenant_id="tenant_2",
                        username="invited_user",
                        email="invited@example.com",
                        password_hash="secret",
                        is_platform_admin=False,
                        can_create_workspace=False,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            db.commit()

            db.add_all(
                [
                    TenantMembership(
                        id="tm_platform_admin_t1",
                        tenant_id="tenant_1",
                        user_id="user_platform_admin",
                        role="admin",
                        status="active",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    TenantMembership(
                        id="tm_alice_t1",
                        tenant_id="tenant_1",
                        user_id="user_alice",
                        role="member",
                        status="active",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    TenantMembership(
                        id="tm_alice_t2",
                        tenant_id="tenant_2",
                        user_id="user_alice",
                        role="member",
                        status="active",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    TenantMembership(
                        id="tm_bob_t1",
                        tenant_id="tenant_1",
                        user_id="user_bob",
                        role="member",
                        status="active",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    TenantMembership(
                        id="tm_ops_admin_t1",
                        tenant_id="tenant_1",
                        user_id="user_ops_admin",
                        role="member",
                        status="active",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            db.commit()

            db.add_all(
                [
                    Workspace(
                        id="ws_default",
                        tenant_id="tenant_1",
                        name="Default Workspace",
                        slug="default-workspace",
                        status="active",
                        is_default=True,
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    Workspace(
                        id="ws_ops",
                        tenant_id="tenant_1",
                        name="Ops Workspace",
                        slug="ops-workspace",
                        status="active",
                        is_default=False,
                        created_by="user_alice",
                        created_at=now,
                        updated_at=now,
                    ),
                    Workspace(
                        id="ws_tenant2",
                        tenant_id="tenant_2",
                        name="Tenant Two Workspace",
                        slug="tenant-two-workspace",
                        status="active",
                        is_default=True,
                        created_by="user_alice",
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            db.commit()

            db.add_all(
                [
                    WorkspaceMembership(
                        id="wm_platform_admin_default",
                        workspace_id="ws_default",
                        user_id="user_platform_admin",
                        role="founder",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    WorkspaceMembership(
                        id="wm_alice_default",
                        workspace_id="ws_default",
                        user_id="user_alice",
                        role="admin",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    WorkspaceMembership(
                        id="wm_alice_ops",
                        workspace_id="ws_ops",
                        user_id="user_alice",
                        role="founder",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    WorkspaceMembership(
                        id="wm_bob_ops",
                        workspace_id="ws_ops",
                        user_id="user_bob",
                        role="member",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    WorkspaceMembership(
                        id="wm_ops_admin_ops",
                        workspace_id="ws_ops",
                        user_id="user_ops_admin",
                        role="admin",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                    WorkspaceMembership(
                        id="wm_alice_tenant2",
                        workspace_id="ws_tenant2",
                        user_id="user_alice",
                        role="founder",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            db.commit()

            db.add_all(
                [
                    WorkspaceInvite(
                        id="invite_accept_existing",
                        workspace_id="ws_ops",
                        email="invited@example.com",
                        role="member",
                        permissions_override_json="{}",
                        status="pending",
                        invited_by="user_alice",
                        expires_at=now + timedelta(days=3),
                        created_at=now,
                        updated_at=now,
                    ),
                    WorkspaceInvite(
                        id="invite_claim_new",
                        workspace_id="ws_ops",
                        email="claim-new@example.com",
                        role="guest",
                        permissions_override_json="{}",
                        status="pending",
                        invited_by="user_alice",
                        expires_at=now + timedelta(days=3),
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            db.commit()

    def _override_get_db(self):
        with Session(self.engine) as db:
            yield db

    def _client(self) -> TestClient:
        return TestClient(self.app)

    def _principal(
        self,
        *,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
        workspace_role: str,
    ) -> Principal:
        with Session(self.engine) as db:
            user = db.get(User, user_id)
            assert user is not None
        return Principal(
            kind="session",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role=workspace_role,
            workspace_membership_status="active",
            workspace_permissions=resolve_workspace_capabilities(workspace_role, "{}"),
            user=user,
        )

    def _set_current_principal(self, principal: Principal) -> None:
        self.app.dependency_overrides[auth_router_module.get_current_principal] = lambda: principal
        self.app.dependency_overrides[workspaces_router_module.get_current_principal] = lambda: principal

    def _set_platform_admin_session(self, user_id: str) -> None:
        with Session(self.engine) as db:
            user = db.get(User, user_id)
            assert user is not None
        self.app.dependency_overrides[platform_router_module.require_platform_admin_session] = lambda: user

    def test_workspace_create_and_list_remain_tenant_scoped(self):
        self._set_current_principal(
            self._principal(
                user_id="user_alice",
                tenant_id="tenant_1",
                workspace_id="ws_default",
                workspace_role="admin",
            )
        )

        with self._client() as client:
            create_response = client.post("/api/v1/workspaces", json={"name": "Phase47 Workspace"})
            self.assertEqual(create_response.status_code, 201)
            created = create_response.json()
            self.assertEqual(created["workspace"]["tenant_id"], "tenant_1")
            self.assertEqual(created["workspace_membership"]["role"], "founder")
            self.assertEqual(created["user"]["workspace_id"], created["workspace"]["id"])

            list_response = client.get("/api/v1/workspaces")
            self.assertEqual(list_response.status_code, 200)
            workspaces = list_response.json()

        workspace_ids = {item["id"] for item in workspaces}
        self.assertIn("ws_default", workspace_ids)
        self.assertIn("ws_ops", workspace_ids)
        self.assertIn(created["workspace"]["id"], workspace_ids)
        self.assertNotIn("ws_tenant2", workspace_ids)
        self.assertTrue(all(item["tenant_id"] == "tenant_1" for item in workspaces))

    def test_context_switch_rejects_cross_tenant_workspace_and_keeps_positive_path_explicit(self):
        def _active_tenant_context(db, _credentials):
            user = db.get(User, "user_alice")
            tenant_membership = db.get(TenantMembership, "tm_alice_t1")
            assert user is not None
            assert tenant_membership is not None
            return ActiveTenantContext(user=user, tenant_membership=tenant_membership)

        with patch.object(
            auth_router_module,
            "require_active_session_tenant_context",
            side_effect=_active_tenant_context,
        ):
            with self._client() as client:
                success = client.post(
                    "/api/v1/auth/context/switch",
                    json={"workspace_id": "ws_ops"},
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(success.status_code, 200)
                self.assertEqual(success.json()["workspace"]["id"], "ws_ops")
                self.assertEqual(success.json()["tenant_membership"]["tenant_id"], "tenant_1")

                denied = client.post(
                    "/api/v1/auth/context/switch",
                    json={"workspace_id": "ws_tenant2"},
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(denied.status_code, 401)
                self.assertEqual(denied.json()["detail"], "Workspace not in active tenant")

    def test_invite_accept_and_claim_flows_expose_negative_paths_explicitly(self):
        current_session_user_id = "user_bob"

        def _require_user(db, _credentials):
            user = db.get(User, current_session_user_id)
            assert user is not None
            return user

        with patch("app.api.deps.require_user", side_effect=_require_user):
            with self._client() as client:
                mismatch = client.post(
                    "/api/v1/workspace-invites/invite_accept_existing/accept",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(mismatch.status_code, 403)
                self.assertIn("email does not match", mismatch.json()["detail"])

                current_session_user_id = "user_invited"
                accepted = client.post(
                    "/api/v1/workspace-invites/invite_accept_existing/accept",
                    headers={"Authorization": "Bearer test-token"},
                )
                self.assertEqual(accepted.status_code, 200)
                accepted_payload = accepted.json()
                self.assertEqual(accepted_payload["invite"]["status"], "accepted")
                self.assertEqual(accepted_payload["workspace"]["id"], "ws_ops")
                self.assertEqual(accepted_payload["tenant_membership"]["tenant_id"], "tenant_1")
                self.assertEqual(accepted_payload["workspace_membership"]["role"], "member")

                claimed = client.post(
                    "/api/v1/workspace-invites/invite_claim_new/claim",
                    json={"password": "claim-pass-123", "username": "claim_new_user"},
                )
                self.assertEqual(claimed.status_code, 200)
                claimed_payload = claimed.json()
                self.assertEqual(claimed_payload["workspace"]["id"], "ws_ops")
                self.assertEqual(claimed_payload["workspace_membership"]["role"], "guest")
                self.assertEqual(claimed_payload["user"]["email"], "claim-new@example.com")

                claim_replay = client.post(
                    "/api/v1/workspace-invites/invite_claim_new/claim",
                    json={"password": "claim-pass-123", "username": "claim_new_user"},
                )
                self.assertEqual(claim_replay.status_code, 409)
                self.assertEqual(claim_replay.json()["detail"], "Invite has already been accepted")

        with Session(self.engine) as db:
            invited_user = db.get(User, "user_invited")
            accepted_membership = db.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == "ws_ops",
                    WorkspaceMembership.user_id == "user_invited",
                )
            )
            claimed_user = db.scalar(select(User).where(User.email == "claim-new@example.com"))
            self.assertIsNotNone(invited_user)
            self.assertIsNotNone(accepted_membership)
            self.assertEqual(invited_user.tenant_id, "tenant_1")
            self.assertEqual(accepted_membership.status, "active")
            self.assertIsNotNone(claimed_user)

    def test_platform_admin_visibility_and_portrait_route_access_control(self):
        with self._client() as client:
            missing_bearer = client.get("/api/v1/platform/users/user_alice/access-portrait")
            self.assertEqual(missing_bearer.status_code, 401)
            self.assertEqual(missing_bearer.json()["detail"], "Missing bearer token")

            api_key_denied = client.get(
                "/api/v1/platform/workspaces/ws_ops/access-portrait",
                headers={"X-API-Key": "phase47-api-key"},
            )
            self.assertEqual(api_key_denied.status_code, 403)
            self.assertEqual(api_key_denied.json()["detail"], "Platform admin session required")

        self._set_platform_admin_session("user_platform_admin")
        with self._client() as client:
            workspaces_response = client.get("/api/v1/platform/workspaces")
            self.assertEqual(workspaces_response.status_code, 200)
            workspace_ids = {item["id"] for item in workspaces_response.json()}
            self.assertIn("ws_default", workspace_ids)
            self.assertIn("ws_ops", workspace_ids)
            self.assertIn("ws_tenant2", workspace_ids)

            portrait_response = client.get("/api/v1/platform/workspaces/ws_ops/access-portrait")
            self.assertEqual(portrait_response.status_code, 200)
            portrait = portrait_response.json()
            self.assertEqual(portrait["workspace"]["id"], "ws_ops")
            self.assertTrue(portrait["membership_summary"]["active_founder_invariant_ok"])

    def test_capability_enforcement_and_founder_archive_invariants_are_explicit(self):
        self._set_current_principal(
            self._principal(
                user_id="user_bob",
                tenant_id="tenant_1",
                workspace_id="ws_ops",
                workspace_role="member",
            )
        )
        with self._client() as client:
            metadata_denied = client.patch("/api/v1/workspaces/ws_ops", json={"name": "Denied Rename"})
            self.assertEqual(metadata_denied.status_code, 403)
            self.assertEqual(
                metadata_denied.json()["detail"],
                "Missing workspace capability: can_edit_workspace_metadata",
            )

        self._set_current_principal(
            self._principal(
                user_id="user_ops_admin",
                tenant_id="tenant_1",
                workspace_id="ws_ops",
                workspace_role="admin",
            )
        )
        with self._client() as client:
            founder_transfer_denied = client.post(
                "/api/v1/workspaces/ws_ops/founder-transfer",
                json={"target_user_id": "user_bob"},
            )
            self.assertEqual(founder_transfer_denied.status_code, 403)
            self.assertEqual(founder_transfer_denied.json()["detail"], "Founder transfer is forbidden")

        self._set_current_principal(
            self._principal(
                user_id="user_platform_admin",
                tenant_id="tenant_1",
                workspace_id="ws_default",
                workspace_role="founder",
            )
        )
        with self._client() as client:
            archive_denied = client.post("/api/v1/workspaces/ws_default/archive")
            self.assertEqual(archive_denied.status_code, 409)
            self.assertEqual(archive_denied.json()["detail"], "Default workspace cannot be archived")


if __name__ == "__main__":
    unittest.main()
