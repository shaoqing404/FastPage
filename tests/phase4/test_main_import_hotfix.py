import importlib
import os
import sys
import unittest
import types
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TASK_QUEUE_BACKEND", "local")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
multipart_module = types.ModuleType("multipart")
multipart_module.__version__ = "0.0-test"
multipart_submodule = types.ModuleType("multipart.multipart")
multipart_submodule.parse_options_header = MagicMock()
sys.modules.setdefault("multipart", multipart_module)
sys.modules.setdefault("multipart.multipart", multipart_submodule)

from sqlalchemy import false

from app.core.principal import Principal
from app.models import Document, User


class TestMainImportHotfix(unittest.TestCase):
    def test_import_app_main_succeeds(self):
        main_module = importlib.import_module("app.main")
        self.assertIsNotNone(main_module.app)

    def test_document_list_uses_workspace_visibility_helper(self):
        documents_module = importlib.import_module("app.api.routers.documents")
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        principal = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_default",
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role="member",
            workspace_membership_status="active",
            workspace_permissions={},
            user=User(id="user_1"),
        )
        with patch.object(documents_module, "get_workspace_visibility_filter", return_value=false()) as mock_get_workspace_visibility_filter:
            result = documents_module.list_documents(db=db, principal=principal)

            self.assertEqual(result, [])
            mock_get_workspace_visibility_filter.assert_called_once_with(db, principal, Document)

    def test_document_list_owner_me_adds_owner_filter(self):
        documents_module = importlib.import_module("app.api.routers.documents")
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        principal = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_default",
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role="member",
            workspace_membership_status="active",
            workspace_permissions={},
            user=User(id="user_1"),
        )
        with patch.object(
            documents_module,
            "get_workspace_visibility_filter",
            return_value=Document.workspace_id == principal.workspace_id,
        ):
            result = documents_module.list_documents(owner_me=True, db=db, principal=principal)

            self.assertEqual(result, [])
            statement = db.scalars.call_args.args[0]
            self.assertIn("documents.owner_user_id", str(statement))
            self.assertIn("documents.workspace_id", str(statement))


if __name__ == "__main__":
    unittest.main()
