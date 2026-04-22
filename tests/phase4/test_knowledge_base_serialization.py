import unittest

from app.models import Document, KnowledgeBase, KnowledgeBaseDocument
from app.services.knowledge_base_service import serialize_knowledge_base


class TestKnowledgeBaseSerialization(unittest.TestCase):
    def test_serialize_knowledge_base_includes_membership_document_metadata(self):
        knowledge_base = KnowledgeBase(
            id="kb_1",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            name="Ops KB",
            description=None,
            status="active",
            visibility="private",
            retrieval_profile_json="{}",
            created_by="user_1",
        )
        document = Document(
            id="doc_1",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            owner_user_id="user_1",
            display_name="runbook.pdf",
            source_filename="runbook.pdf",
            active_version_id="ver_1",
            status="uploaded",
        )
        knowledge_base.documents = [
            KnowledgeBaseDocument(
                knowledge_base_id="kb_1",
                document_id="doc_1",
                pinned_version_id=None,
                enabled=True,
                label=None,
                sort_order=0,
                document=document,
            )
        ]

        payload = serialize_knowledge_base(knowledge_base)

        self.assertEqual(payload["documents"][0]["document_display_name"], "runbook.pdf")
        self.assertEqual(payload["documents"][0]["document_source_filename"], "runbook.pdf")
        self.assertEqual(payload["documents"][0]["document_status"], "uploaded")


if __name__ == "__main__":
    unittest.main()
