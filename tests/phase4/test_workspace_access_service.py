import unittest
from app.core.principal import Principal
from app.models import User, KnowledgeBase, ChatSkill
from app.services.workspace_access_service import (
    get_workspace_role_capabilities,
    resolve_workspace_capabilities,
    can_read_knowledge_base,
    can_edit_knowledge_base,
    can_read_skill,
    can_edit_skill,
    validate_workspace_permissions_override,
)
from fastapi import HTTPException

class TestWorkspaceAccessService(unittest.TestCase):
    def setUp(self):
        self.user = User(id="user_123")
        self.other_user = User(id="user_456")

    def create_principal(self, role: str, workspace_id: str = "ws_1", perms: dict = None, user: User = None) -> Principal:
        _perms = perms if perms is not None else get_workspace_role_capabilities(role)
        return Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id=workspace_id,
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role=role,
            workspace_membership_status="active",
            workspace_permissions=_perms,
            user=user or self.user,
        )

    def test_capability_matrix_resolution(self):
        caps = get_workspace_role_capabilities("admin")
        self.assertTrue(caps.get("can_edit_workspace_metadata"))
        self.assertFalse(caps.get("can_transfer_founder"))
        
        caps = get_workspace_role_capabilities("member")
        self.assertFalse(caps.get("can_manage_members"))
        self.assertTrue(caps.get("can_manage_skills"))
        
    def test_founder_only_capability_cannot_be_overridden_by_others(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_workspace_permissions_override({"can_transfer_founder": True}, role="admin")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("founder-only", ctx.exception.detail)

        caps = resolve_workspace_capabilities("admin", '{"can_transfer_founder": true}')
        self.assertFalse(caps.get("can_transfer_founder"))
        
        caps_founder = resolve_workspace_capabilities("founder", '{"can_manage_invites": false}')
        self.assertTrue(caps_founder.get("can_transfer_founder"))
        self.assertFalse(caps_founder.get("can_manage_invites"))

    def test_private_visibility_reads_and_edits(self):
        kb = KnowledgeBase(workspace_id="ws_1", created_by="user_123", visibility="private")
        
        p_creator_member = self.create_principal("member", "ws_1")
        self.assertTrue(can_read_knowledge_base(p_creator_member, kb))
        self.assertTrue(can_edit_knowledge_base(p_creator_member, kb))

        p_other_member = self.create_principal("member", "ws_1", user=self.other_user)
        self.assertFalse(can_read_knowledge_base(p_other_member, kb))
        self.assertFalse(can_edit_knowledge_base(p_other_member, kb))

        p_admin = self.create_principal("admin", "ws_1", user=self.other_user)
        self.assertTrue(can_read_knowledge_base(p_admin, kb))
        self.assertTrue(can_edit_knowledge_base(p_admin, kb))

    def test_workspace_read_edit_visibility(self):
        kb_read = KnowledgeBase(workspace_id="ws_1", created_by="user_123", visibility="workspace_read")
        kb_edit = KnowledgeBase(workspace_id="ws_1", created_by="user_123", visibility="workspace_edit")

        p_other_member = self.create_principal("member", "ws_1", user=self.other_user)
        
        self.assertTrue(can_read_knowledge_base(p_other_member, kb_read))
        self.assertFalse(can_edit_knowledge_base(p_other_member, kb_read))

        self.assertTrue(can_read_knowledge_base(p_other_member, kb_edit))
        self.assertTrue(can_edit_knowledge_base(p_other_member, kb_edit))

    def test_workspace_edit_does_not_elevate_guest_without_capability(self):
        skill_edit = ChatSkill(workspace_id="ws_1", owner_user_id="user_123", visibility="workspace_edit")
        
        p_guest = self.create_principal("guest", "ws_1", user=self.other_user)
        self.assertTrue(can_read_skill(p_guest, skill_edit))
        self.assertFalse(can_edit_skill(p_guest, skill_edit))

        p_member = self.create_principal("member", "ws_1", user=self.other_user)
        self.assertTrue(can_read_skill(p_member, skill_edit))
        self.assertTrue(can_edit_skill(p_member, skill_edit))

if __name__ == "__main__":
    unittest.main()
