import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import or_, select
from app.core.principal import Principal
from app.models import Document, ParseJob, ChatRun
from app.services.workspace_scope_service import get_workspace_visibility_filter

class TestWorkspaceScopeService(unittest.TestCase):
    def setUp(self):
        self.principal_default = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_default",
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role="founder",
            workspace_membership_status="active",
            workspace_permissions={},
            user=MagicMock(),
        )
        self.principal_non_default = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_non_default",
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role="founder",
            workspace_membership_status="active",
            workspace_permissions={},
            user=MagicMock(),
        )

    @patch("app.services.workspace_scope_service.is_default_workspace")
    def test_default_workspace_allows_null(self, mock_is_default):
        db = MagicMock()
        mock_is_default.return_value = True

        for model in (Document, ParseJob, ChatRun):
            filter_expr = get_workspace_visibility_filter(db, self.principal_default, model)
            expr_str = str(filter_expr.compile(compile_kwargs={"literal_binds": True}))
            self.assertIn("IS NULL", expr_str.upper())
            self.assertIn("workspace_id =", expr_str)

    @patch("app.services.workspace_scope_service.is_default_workspace")
    def test_non_default_workspace_rejects_null(self, mock_is_default):
        db = MagicMock()
        mock_is_default.return_value = False

        for model in (Document, ParseJob, ChatRun):
            filter_expr = get_workspace_visibility_filter(db, self.principal_non_default, model)
            expr_str = str(filter_expr.compile(compile_kwargs={"literal_binds": True}))
            self.assertNotIn("IS NULL", expr_str.upper())
            self.assertIn("workspace_id =", expr_str)

if __name__ == "__main__":
    unittest.main()
