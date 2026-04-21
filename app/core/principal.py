from dataclasses import dataclass

from app.models import ApiKey, User


@dataclass
class Principal:
    kind: str
    tenant_id: str
    workspace_id: str
    tenant_membership_role: str
    tenant_membership_status: str
    workspace_membership_role: str
    workspace_membership_status: str
    workspace_permissions: dict[str, bool]
    user: User
    api_key: ApiKey | None = None
    workspace_membership_id: str | None = None

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def membership_role(self) -> str:
        # Compatibility alias retained for callers that still expect one active role.
        return self.workspace_membership_role

    def has_workspace_capability(self, capability_key: str) -> bool:
        return self.workspace_permissions.get(capability_key, False)
