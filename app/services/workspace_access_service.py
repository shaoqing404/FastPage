import json
from collections.abc import Mapping

from fastapi import HTTPException, status

from app.core.principal import Principal
from app.models import ChatSkill, KnowledgeBase

WORKSPACE_CAPABILITY_KEYS: tuple[str, ...] = (
    "can_view_workspace",
    "can_edit_workspace_metadata",
    "can_manage_members",
    "can_manage_invites",
    "can_transfer_founder",
    "can_archive_workspace",
    "can_manage_api_keys",
    "can_manage_providers",
    "can_manage_knowledge_bases",
    "can_manage_skills",
    "can_run_skills",
    "can_view_runs",
)

RESOURCE_VISIBILITY_VALUES: tuple[str, ...] = (
    "private",
    "workspace_read",
    "workspace_edit",
)

FOUNDER_ONLY_CAPABILITY_KEYS = frozenset(
    {
        "can_transfer_founder",
        "can_archive_workspace",
    }
)

WORKSPACE_ROLE_CAPABILITY_MATRIX: dict[str, dict[str, bool]] = {
    "founder": {
        "can_view_workspace": True,
        "can_edit_workspace_metadata": True,
        "can_manage_members": True,
        "can_manage_invites": True,
        "can_transfer_founder": True,
        "can_archive_workspace": True,
        "can_manage_api_keys": True,
        "can_manage_providers": True,
        "can_manage_knowledge_bases": True,
        "can_manage_skills": True,
        "can_run_skills": True,
        "can_view_runs": True,
    },
    "admin": {
        "can_view_workspace": True,
        "can_edit_workspace_metadata": True,
        "can_manage_members": True,
        "can_manage_invites": True,
        "can_transfer_founder": False,
        "can_archive_workspace": False,
        "can_manage_api_keys": True,
        "can_manage_providers": True,
        "can_manage_knowledge_bases": True,
        "can_manage_skills": True,
        "can_run_skills": True,
        "can_view_runs": True,
    },
    "member": {
        "can_view_workspace": True,
        "can_edit_workspace_metadata": False,
        "can_manage_members": False,
        "can_manage_invites": False,
        "can_transfer_founder": False,
        "can_archive_workspace": False,
        "can_manage_api_keys": True,
        "can_manage_providers": False,
        "can_manage_knowledge_bases": True,
        "can_manage_skills": True,
        "can_run_skills": True,
        "can_view_runs": True,
    },
    "guest": {
        "can_view_workspace": True,
        "can_edit_workspace_metadata": False,
        "can_manage_members": False,
        "can_manage_invites": False,
        "can_transfer_founder": False,
        "can_archive_workspace": False,
        "can_manage_api_keys": False,
        "can_manage_providers": False,
        "can_manage_knowledge_bases": False,
        "can_manage_skills": False,
        "can_run_skills": True,
        "can_view_runs": True,
    },
}


def get_workspace_role_capabilities(role: str) -> dict[str, bool]:
    defaults = WORKSPACE_ROLE_CAPABILITY_MATRIX.get(role)
    if defaults is None:
        return {key: False for key in WORKSPACE_CAPABILITY_KEYS}
    return dict(defaults)


def parse_workspace_permissions_override(
    permissions_override_json: str | Mapping[str, object] | None,
) -> dict[str, bool]:
    if permissions_override_json in (None, ""):
        return {}

    payload: object = permissions_override_json
    if isinstance(permissions_override_json, str):
        try:
            payload = json.loads(permissions_override_json)
        except json.JSONDecodeError:
            return {}

    if not isinstance(payload, Mapping):
        return {}

    parsed: dict[str, bool] = {}
    for key in WORKSPACE_CAPABILITY_KEYS:
        value = payload.get(key)
        if isinstance(value, bool):
            parsed[key] = value
    return parsed


def validate_workspace_permissions_override(
    permissions_override: Mapping[str, object] | None,
    *,
    role: str,
) -> dict[str, bool]:
    if permissions_override is None:
        return {}
    if not isinstance(permissions_override, Mapping):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="permissions_override must be an object")

    unknown_keys = sorted(key for key in permissions_override if key not in WORKSPACE_CAPABILITY_KEYS)
    if unknown_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown workspace capability override keys: {', '.join(unknown_keys)}",
        )

    parsed: dict[str, bool] = {}
    for key, value in permissions_override.items():
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"permissions_override.{key} must be a boolean",
            )
        if key in FOUNDER_ONLY_CAPABILITY_KEYS and value and role != "founder":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"permissions_override.{key} is founder-only",
            )
        parsed[key] = value

    return parsed


def dump_workspace_permissions_override_json(
    permissions_override: Mapping[str, object] | None,
    *,
    role: str,
) -> str:
    validated = validate_workspace_permissions_override(permissions_override, role=role)
    return json.dumps(validated, ensure_ascii=False, sort_keys=True)


def resolve_workspace_capabilities(
    role: str,
    permissions_override_json: str | Mapping[str, object] | None,
) -> dict[str, bool]:
    capabilities = get_workspace_role_capabilities(role)
    overrides = parse_workspace_permissions_override(permissions_override_json)

    for key, value in overrides.items():
        if key in FOUNDER_ONLY_CAPABILITY_KEYS and value and not capabilities.get(key, False):
            continue
        capabilities[key] = value

    return capabilities


def require_workspace_capability(
    principal: Principal,
    capability_key: str,
    *,
    detail: str | None = None,
) -> None:
    if principal.has_workspace_capability(capability_key):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail or f"Missing workspace capability: {capability_key}",
    )


def _is_workspace_resource_admin(principal: Principal) -> bool:
    return principal.workspace_membership_role in {"founder", "admin"}


def _workspace_matches(principal: Principal, workspace_id: str | None) -> bool:
    return workspace_id is not None and principal.workspace_id == workspace_id


def _effective_visibility(raw_visibility: str | None) -> str:
    if raw_visibility in RESOURCE_VISIBILITY_VALUES:
        return raw_visibility
    return "private"


def can_read_knowledge_base(principal: Principal, knowledge_base: KnowledgeBase) -> bool:
    if not _workspace_matches(principal, knowledge_base.workspace_id):
        return False
    if _is_workspace_resource_admin(principal) or principal.user_id == knowledge_base.created_by:
        return True
    return _effective_visibility(knowledge_base.visibility) in {"workspace_read", "workspace_edit"}


def can_edit_knowledge_base(principal: Principal, knowledge_base: KnowledgeBase) -> bool:
    if not _workspace_matches(principal, knowledge_base.workspace_id):
        return False
    if _is_workspace_resource_admin(principal) or principal.user_id == knowledge_base.created_by:
        return True
    if not principal.has_workspace_capability("can_manage_knowledge_bases"):
        return False
    return _effective_visibility(knowledge_base.visibility) == "workspace_edit"


def can_read_skill(principal: Principal, skill: ChatSkill) -> bool:
    if not _workspace_matches(principal, skill.workspace_id):
        return False
    if _is_workspace_resource_admin(principal) or principal.user_id == skill.owner_user_id:
        return True
    return _effective_visibility(skill.visibility) in {"workspace_read", "workspace_edit"}


def can_edit_skill(principal: Principal, skill: ChatSkill) -> bool:
    if not _workspace_matches(principal, skill.workspace_id):
        return False
    if _is_workspace_resource_admin(principal) or principal.user_id == skill.owner_user_id:
        return True
    if not principal.has_workspace_capability("can_manage_skills"):
        return False
    return _effective_visibility(skill.visibility) == "workspace_edit"


def assert_can_read_knowledge_base(principal: Principal, knowledge_base: KnowledgeBase) -> None:
    if can_read_knowledge_base(principal, knowledge_base):
        return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")


def assert_can_edit_knowledge_base(principal: Principal, knowledge_base: KnowledgeBase) -> None:
    if can_edit_knowledge_base(principal, knowledge_base):
        return
    if not can_read_knowledge_base(principal, knowledge_base):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Knowledge base is not editable")


def assert_can_read_skill(principal: Principal, skill: ChatSkill) -> None:
    if can_read_skill(principal, skill):
        return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")


def assert_can_edit_skill(principal: Principal, skill: ChatSkill) -> None:
    if can_edit_skill(principal, skill):
        return
    if not can_read_skill(principal, skill):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Skill is not editable")
