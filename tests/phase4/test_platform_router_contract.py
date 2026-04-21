import importlib.util
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())

from app.core.auth import hash_password, verify_login
from app.core.db import Base
from app.models import (
    ApiKey,
    ChatRun,
    ChatSession,
    ChatSkill,
    KnowledgeBase,
    ModelProvider,
    Tenant,
    TenantMembership,
    User,
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
)


PLATFORM_ROUTER_MODULE_NAME = "phase45_platform_router_under_test"
PLATFORM_ROUTER_PATH = Path(__file__).resolve().parents[2] / "app" / "api" / "routers" / "platform.py"
platform_router_spec = importlib.util.spec_from_file_location(PLATFORM_ROUTER_MODULE_NAME, PLATFORM_ROUTER_PATH)
platform_router_module = importlib.util.module_from_spec(platform_router_spec)
assert platform_router_spec is not None and platform_router_spec.loader is not None
sys.modules[PLATFORM_ROUTER_MODULE_NAME] = platform_router_module
platform_router_spec.loader.exec_module(platform_router_module)
platform_router = platform_router_module.router


class TestPlatformRouterContract(unittest.TestCase):
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

        with Session(self.engine) as db:
            tenant_1 = Tenant(id="tenant_1", name="Tenant One", status="active")
            tenant_2 = Tenant(id="tenant_2", name="Tenant Two", status="active")
            db.add_all([tenant_1, tenant_2])
            db.commit()

            platform_admin = User(
                id="user_platform_admin",
                tenant_id="tenant_1",
                username="platform_admin",
                email="platform-admin@example.com",
                password_hash=hash_password("admin-secret"),
                is_platform_admin=True,
                is_active=True,
                can_create_workspace=True,
            )
            alice = User(
                id="user_alice",
                tenant_id="tenant_1",
                username="alice",
                email="alice@example.com",
                password_hash=hash_password("alice-secret"),
                is_platform_admin=False,
                is_active=True,
                can_create_workspace=False,
            )
            bob = User(
                id="user_bob",
                tenant_id="tenant_1",
                username="bob",
                email="bob@example.com",
                password_hash=hash_password("bob-secret"),
                is_platform_admin=False,
                is_active=True,
                can_create_workspace=False,
            )
            db.add_all([platform_admin, alice, bob])
            db.commit()

            db.add_all(
                [
                    TenantMembership(
                        id="tm_admin_t1",
                        tenant_id="tenant_1",
                        user_id="user_platform_admin",
                        role="admin",
                        status="active",
                        created_by="user_platform_admin",
                    ),
                    TenantMembership(
                        id="tm_alice_t1",
                        tenant_id="tenant_1",
                        user_id="user_alice",
                        role="member",
                        status="active",
                        created_by="user_platform_admin",
                    ),
                    TenantMembership(
                        id="tm_alice_t2",
                        tenant_id="tenant_2",
                        user_id="user_alice",
                        role="member",
                        status="active",
                        created_by="user_platform_admin",
                    ),
                    TenantMembership(
                        id="tm_bob_t1",
                        tenant_id="tenant_1",
                        user_id="user_bob",
                        role="member",
                        status="active",
                        created_by="user_platform_admin",
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
                    ),
                    Workspace(
                        id="ws_ops",
                        tenant_id="tenant_1",
                        name="Ops Workspace",
                        slug="ops-workspace",
                        status="active",
                        is_default=False,
                        created_by="user_alice",
                    ),
                    Workspace(
                        id="ws_tenant2",
                        tenant_id="tenant_2",
                        name="Tenant Two Workspace",
                        slug="tenant-two-workspace",
                        status="active",
                        is_default=True,
                        created_by="user_alice",
                    ),
                ]
            )
            db.commit()

            db.add_all(
                [
                    WorkspaceMembership(
                        id="wm_admin_default",
                        workspace_id="ws_default",
                        user_id="user_platform_admin",
                        role="founder",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                    ),
                    WorkspaceMembership(
                        id="wm_alice_default",
                        workspace_id="ws_default",
                        user_id="user_alice",
                        role="admin",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                    ),
                    WorkspaceMembership(
                        id="wm_alice_ops",
                        workspace_id="ws_ops",
                        user_id="user_alice",
                        role="founder",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                    ),
                    WorkspaceMembership(
                        id="wm_bob_ops",
                        workspace_id="ws_ops",
                        user_id="user_bob",
                        role="member",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                    ),
                    WorkspaceMembership(
                        id="wm_alice_tenant2",
                        workspace_id="ws_tenant2",
                        user_id="user_alice",
                        role="founder",
                        status="active",
                        permissions_override_json="{}",
                        created_by="user_platform_admin",
                    ),
                ]
            )
            db.commit()

            now = datetime.utcnow()
            db.add_all(
                [
                    WorkspaceInvite(
                        id="invite_ops_pending",
                        workspace_id="ws_ops",
                        email="pending@example.com",
                        role="member",
                        permissions_override_json="{}",
                        status="pending",
                        invited_by="user_alice",
                        expires_at=now + timedelta(days=3),
                        created_at=now,
                        updated_at=now,
                    ),
                    ModelProvider(
                        id="provider_shared",
                        tenant_id="tenant_1",
                        workspace_id=None,
                        provider_type="openai_compatible",
                        name="Shared Provider",
                        base_url="https://example.com/v1",
                        api_key_encrypted="secret",
                        default_model="openai/qwen-plus",
                        supported_models_json=json.dumps(["openai/qwen-plus"]),
                        extra_headers_json="{}",
                        enabled=True,
                        is_default=True,
                        managed_by_system=True,
                        created_at=now,
                        updated_at=now,
                    ),
                    ModelProvider(
                        id="provider_ops",
                        tenant_id="tenant_1",
                        workspace_id="ws_ops",
                        provider_type="openai_compatible",
                        name="Ops Provider",
                        base_url="https://example.com/v1",
                        api_key_encrypted="secret",
                        default_model="openai/qwen-plus",
                        supported_models_json=json.dumps(["openai/qwen-plus"]),
                        extra_headers_json="{}",
                        enabled=True,
                        is_default=False,
                        managed_by_system=False,
                        created_at=now,
                        updated_at=now,
                    ),
                    ApiKey(
                        id="key_ops",
                        tenant_id="tenant_1",
                        workspace_id="ws_ops",
                        name="Ops Key",
                        key_prefix="pk_test",
                        key_hash="hash",
                        status="active",
                        created_by="user_alice",
                        created_at=now,
                    ),
                    KnowledgeBase(
                        id="kb_ops",
                        tenant_id="tenant_1",
                        workspace_id="ws_ops",
                        name="Ops KB",
                        description=None,
                        status="active",
                        visibility="workspace_read",
                        retrieval_profile_json="{}",
                        created_by="user_alice",
                        created_at=now,
                        updated_at=now,
                    ),
                    ChatSkill(
                        id="skill_ops",
                        tenant_id="tenant_1",
                        workspace_id="ws_ops",
                        owner_user_id="user_alice",
                        name="Ops Skill",
                        description=None,
                        system_prompt="Answer questions",
                        document_scope_type="explicit",
                        knowledge_base_id="kb_ops",
                        provider_id="provider_ops",
                        model="openai/qwen-plus",
                        request_config_json="{}",
                        conversation_config_json="{}",
                        retrieval_config_json="{}",
                        generation_config_json="{}",
                        is_active=True,
                        visibility="workspace_edit",
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            db.commit()
            db.add(
                ChatSession(
                    id="session_ops",
                    tenant_id="tenant_1",
                    workspace_id="ws_ops",
                    user_id="user_alice",
                    skill_id="skill_ops",
                    active_run_id=None,
                    title="Ops Session",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.commit()
            db.add(
                ChatRun(
                    id="run_ops",
                    tenant_id="tenant_1",
                    workspace_id="ws_ops",
                    user_id="user_alice",
                    session_id="session_ops",
                    document_id=None,
                    version_id=None,
                    skill_id="skill_ops",
                    provider_id="provider_ops",
                    model="openai/qwen-plus",
                    question="What changed?",
                    answer="Done",
                    answer_text="Done",
                    answer_with_marker="Done",
                    status="completed",
                    cancel_requested=False,
                    cancel_reason=None,
                    request_config_json="{}",
                    conversation_config_json="{}",
                    retrieval_config_json="{}",
                    generation_config_json="{}",
                    selected_sections_json="[]",
                    citations_json="[]",
                    execution_context_json="{}",
                    metrics_json="{}",
                    last_error=None,
                    worker_node_code=None,
                    claimed_at=None,
                    heartbeat_at=None,
                    started_at=now,
                    finished_at=now,
                    created_at=now,
                )
            )
            db.commit()

        self.app = FastAPI()
        self.app.include_router(platform_router)
        self.app.dependency_overrides[platform_router_module.get_db] = self._override_get_db
        self.addCleanup(self.app.dependency_overrides.clear)

        self.platform_admin_user = User(
            id="user_platform_admin",
            tenant_id="tenant_1",
            username="platform_admin",
            email="platform-admin@example.com",
            password_hash="ignored",
            is_platform_admin=True,
            is_active=True,
            can_create_workspace=True,
        )
        self.normal_user = User(
            id="user_alice",
            tenant_id="tenant_1",
            username="alice",
            email="alice@example.com",
            password_hash="ignored",
            is_platform_admin=False,
            is_active=True,
            can_create_workspace=False,
        )

    def _override_get_db(self):
        with Session(self.engine) as db:
            yield db

    def _client(self) -> TestClient:
        return TestClient(self.app)

    def _use_platform_admin_override(self) -> None:
        self.app.dependency_overrides[platform_router_module.require_platform_admin_session] = (
            lambda: self.platform_admin_user
        )

    def test_platform_routes_registered_on_main_app(self):
        main_py = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("from app.api.routers import auth, chat, documents, jobs, knowledge_bases, metrics, platform, providers, skills", main_py)
        self.assertIn("app.include_router(platform.router)", main_py)

    @patch(f"{PLATFORM_ROUTER_MODULE_NAME}.require_user")
    def test_non_platform_admin_session_is_forbidden(self, mock_require_user):
        mock_require_user.return_value = self.normal_user

        with self._client() as client:
            response = client.get(
                "/api/v1/platform/users",
                headers={"Authorization": "Bearer session-token"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Platform admin access required")

    def test_api_key_auth_is_forbidden_for_platform_routes(self):
        with self._client() as client:
            response = client.get(
                "/api/v1/platform/users",
                headers={"X-API-Key": "test-api-key"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Platform admin session required")

    def test_api_key_auth_is_forbidden_for_platform_portrait_routes(self):
        with self._client() as client:
            user_response = client.get(
                "/api/v1/platform/users/user_alice/access-portrait",
                headers={"X-API-Key": "test-api-key"},
            )
            workspace_response = client.get(
                "/api/v1/platform/workspaces/ws_ops/access-portrait",
                headers={"X-API-Key": "test-api-key"},
            )

        self.assertEqual(user_response.status_code, 403)
        self.assertEqual(user_response.json()["detail"], "Platform admin session required")
        self.assertEqual(workspace_response.status_code, 403)
        self.assertEqual(workspace_response.json()["detail"], "Platform admin session required")

    def test_user_directory_and_patch_contract(self):
        self._use_platform_admin_override()

        with self._client() as client:
            list_response = client.get("/api/v1/platform/users")
            self.assertEqual(list_response.status_code, 200)
            users = list_response.json()
            alice_summary = next(item for item in users if item["id"] == "user_alice")
            self.assertEqual(alice_summary["tenant_membership_count"], 2)
            self.assertEqual(alice_summary["workspace_membership_count"], 3)

            detail_response = client.get("/api/v1/platform/users/user_alice")
            self.assertEqual(detail_response.status_code, 200)
            detail = detail_response.json()
            self.assertEqual(detail["username"], "alice")
            self.assertEqual(len(detail["tenant_memberships"]), 2)
            self.assertEqual(len(detail["workspace_memberships"]), 3)

            patch_response = client.patch(
                "/api/v1/platform/users/user_alice",
                json={"can_create_workspace": True, "is_platform_admin": True},
            )
            self.assertEqual(patch_response.status_code, 200)
            patched = patch_response.json()
            self.assertTrue(patched["can_create_workspace"])
            self.assertTrue(patched["is_platform_admin"])

        with Session(self.engine) as db:
            logged_in = verify_login(db, "alice", "alice-secret")
            self.assertIsNotNone(logged_in)
            assert logged_in is not None
            self.assertTrue(logged_in.can_create_workspace)
            self.assertTrue(logged_in.is_platform_admin)

    def test_user_disable_patch_blocks_login_by_design(self):
        self._use_platform_admin_override()

        with self._client() as client:
            response = client.patch(
                "/api/v1/platform/users/user_bob",
                json={"is_active": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])

        with Session(self.engine) as db:
            self.assertIsNone(verify_login(db, "bob", "bob-secret"))

    def test_workspace_directory_detail_and_archive_contract(self):
        self._use_platform_admin_override()

        with self._client() as client:
            list_response = client.get("/api/v1/platform/workspaces")
            self.assertEqual(list_response.status_code, 200)
            workspaces = list_response.json()
            ops_workspace = next(item for item in workspaces if item["id"] == "ws_ops")
            self.assertEqual(ops_workspace["founder_user_id"], "user_alice")
            self.assertEqual(ops_workspace["member_count"], 2)
            self.assertEqual(ops_workspace["active_member_count"], 2)

            detail_response = client.get("/api/v1/platform/workspaces/ws_ops")
            self.assertEqual(detail_response.status_code, 200)
            detail = detail_response.json()
            self.assertEqual(detail["tenant_name"], "Tenant One")
            self.assertEqual(len(detail["members"]), 2)

            archive_response = client.post("/api/v1/platform/workspaces/ws_ops/archive")
            self.assertEqual(archive_response.status_code, 200)
            archived = archive_response.json()
            self.assertEqual(archived["status"], "archived")
            self.assertEqual(archived["archived_by"], "user_platform_admin")

    def test_user_access_portrait_contract(self):
        self._use_platform_admin_override()

        with self._client() as client:
            response = client.get("/api/v1/platform/users/user_alice/access-portrait")
            self.assertEqual(response.status_code, 200)
            portrait = response.json()
            self.assertEqual(portrait["user"]["id"], "user_alice")
            self.assertEqual(portrait["effective_portrait"]["resolved_context"]["workspace_id"], "ws_default")
            self.assertEqual(portrait["effective_portrait"]["workspace_membership"]["role"], "admin")
            self.assertTrue(
                portrait["effective_portrait"]["workspace_membership"]["effective_permissions"]["can_manage_members"]
            )
            self.assertFalse(
                portrait["effective_portrait"]["platform_permissions"]["can_access_platform_control_plane"]
            )
            self.assertIn(
                "Platform control-plane access denied because is_platform_admin=false.",
                portrait["effective_portrait"]["explainability"]["denied_reasons"],
            )

            explicit_response = client.get(
                "/api/v1/platform/users/user_alice/access-portrait",
                params={"workspace_id": "ws_ops"},
            )
            self.assertEqual(explicit_response.status_code, 200)
            explicit_portrait = explicit_response.json()
            self.assertEqual(explicit_portrait["effective_portrait"]["resolved_context"]["source"], "explicit")
            self.assertEqual(explicit_portrait["effective_portrait"]["workspace_membership"]["role"], "founder")
            self.assertEqual(
                explicit_portrait["resource_rules"]["providers"]["counts"]["accessible_in_context"],
                2,
            )
            self.assertEqual(
                explicit_portrait["resource_rules"]["knowledge_bases"]["counts"]["workspace_total"],
                1,
            )
            self.assertEqual(
                explicit_portrait["resource_rules"]["sessions_runs"]["counts"]["runs_owned_by_user"],
                1,
            )

    def test_workspace_access_portrait_contract(self):
        self._use_platform_admin_override()

        with self._client() as client:
            response = client.get("/api/v1/platform/workspaces/ws_ops/access-portrait")
            self.assertEqual(response.status_code, 200)
            portrait = response.json()
            self.assertEqual(portrait["workspace"]["id"], "ws_ops")
            self.assertEqual(portrait["tenant"]["id"], "tenant_1")
            self.assertEqual(portrait["founder"]["user_id"], "user_alice")
            self.assertTrue(portrait["membership_summary"]["active_founder_invariant_ok"])
            self.assertEqual(portrait["membership_summary"]["by_role"]["founder"], 1)
            self.assertEqual(portrait["membership_summary"]["by_role"]["member"], 1)
            self.assertEqual(portrait["invite_summary"]["pending"], 1)
            self.assertEqual(portrait["resource_scope"]["providers"]["counts"]["accessible_in_workspace"], 2)
            self.assertEqual(portrait["resource_scope"]["api_keys"]["counts"]["workspace_total"], 1)
            self.assertEqual(portrait["resource_scope"]["skills"]["counts"]["workspace_total"], 1)
            bob_member = next(item for item in portrait["members"] if item["user_id"] == "user_bob")
            self.assertTrue(bob_member["effective_permissions"]["can_run_skills"])
            self.assertFalse(bob_member["effective_permissions"]["can_manage_members"])

    def test_tenant_directory_detail_contract(self):
        self._use_platform_admin_override()

        with self._client() as client:
            list_response = client.get("/api/v1/platform/tenants")
            self.assertEqual(list_response.status_code, 200)
            tenants = list_response.json()
            tenant_one = next(item for item in tenants if item["id"] == "tenant_1")
            self.assertEqual(tenant_one["user_count"], 3)
            self.assertEqual(tenant_one["workspace_count"], 2)

            detail_response = client.get("/api/v1/platform/tenants/tenant_1")
            self.assertEqual(detail_response.status_code, 200)
            detail = detail_response.json()
            self.assertEqual(detail["name"], "Tenant One")
            self.assertEqual(detail["user_count"], 3)
            self.assertEqual(detail["workspace_count"], 2)
            self.assertEqual(len(detail["users"]), 3)
            self.assertEqual(len(detail["workspaces"]), 2)

    def test_create_platform_user_contract(self):
        self._use_platform_admin_override()

        with self._client() as client:
            create_response = client.post(
                "/api/v1/platform/users",
                json={
                    "username": "new_user",
                    "password": "new-secret",
                    "email": "NEW@User.COM",
                    "is_active": True,
                    "can_create_workspace": False,
                    "is_platform_admin": False,
                },
            )
            self.assertEqual(create_response.status_code, 201)
            created = create_response.json()
            self.assertEqual(created["username"], "new_user")
            self.assertEqual(created["email"], "new@user.com")
            self.assertEqual(created["tenant_id"], "tenant_1")
            self.assertEqual(created["tenant_membership_count"], 1)
            self.assertEqual(created["workspace_membership_count"], 1)
            self.assertEqual(len(created["tenant_memberships"]), 1)
            self.assertEqual(len(created["workspace_memberships"]), 1)
            self.assertEqual(created["tenant_memberships"][0]["tenant_id"], "tenant_1")
            self.assertEqual(created["tenant_memberships"][0]["role"], "member")
            self.assertEqual(created["workspace_memberships"][0]["workspace_id"], "ws_default")
            self.assertEqual(created["workspace_memberships"][0]["role"], "member")

        with Session(self.engine) as db:
            logged_in = verify_login(db, "new_user", "new-secret")
            self.assertIsNotNone(logged_in)
            self.assertEqual(logged_in.username, "new_user")
            assert logged_in is not None

            tenant_memberships = db.scalars(
                select(TenantMembership).where(TenantMembership.user_id == logged_in.id)
            ).all()
            workspace_memberships = db.scalars(
                select(WorkspaceMembership).where(WorkspaceMembership.user_id == logged_in.id)
            ).all()
            self.assertEqual(len(tenant_memberships), 1)
            self.assertEqual(tenant_memberships[0].tenant_id, "tenant_1")
            self.assertEqual(len(workspace_memberships), 1)
            self.assertEqual(workspace_memberships[0].workspace_id, "ws_default")

    def test_create_platform_user_inactive_blocks_login(self):
        self._use_platform_admin_override()

        with self._client() as client:
            create_response = client.post(
                "/api/v1/platform/users",
                json={
                    "username": "inactive_bot",
                    "password": "bot-secret",
                    "is_active": False,
                },
            )
            self.assertEqual(create_response.status_code, 201)

        with Session(self.engine) as db:
            self.assertIsNone(verify_login(db, "inactive_bot", "bot-secret"))

    def test_create_platform_user_conflicts(self):
        self._use_platform_admin_override()

        with Session(self.engine) as db:
            user_count_before = db.scalar(select(func.count()).select_from(User))
            tenant_membership_count_before = db.scalar(select(func.count()).select_from(TenantMembership))
            workspace_membership_count_before = db.scalar(select(func.count()).select_from(WorkspaceMembership))

        with self._client() as client:
            res_username = client.post(
                "/api/v1/platform/users",
                json={"username": "alice", "password": "any"},
            )
            self.assertEqual(res_username.status_code, 409)
            self.assertIn("Username already exists", res_username.json()["detail"])

            res_email = client.post(
                "/api/v1/platform/users",
                json={"username": "alice2", "password": "any", "email": "aLiCe@eXample.COM"},
            )
            self.assertEqual(res_email.status_code, 409)
            self.assertIn("Email already exists", res_email.json()["detail"])

        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(User)), user_count_before)
            self.assertEqual(
                db.scalar(select(func.count()).select_from(TenantMembership)),
                tenant_membership_count_before,
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(WorkspaceMembership)),
                workspace_membership_count_before,
            )


if __name__ == "__main__":
    unittest.main()
