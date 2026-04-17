from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PlatformTenantMembershipOut(BaseModel):
    id: str
    tenant_id: str
    tenant_name: str
    role: str
    status: str
    created_at: datetime
    updated_at: datetime


class PlatformWorkspaceMembershipOut(BaseModel):
    id: str
    workspace_id: str
    workspace_name: str
    workspace_slug: str
    tenant_id: str
    tenant_name: str
    role: str
    status: str
    created_at: datetime
    updated_at: datetime


class PlatformUserListItemOut(BaseModel):
    id: str
    tenant_id: str
    username: str
    email: str | None
    is_active: bool
    can_create_workspace: bool
    is_platform_admin: bool
    tenant_membership_count: int
    workspace_membership_count: int
    created_at: datetime
    updated_at: datetime


class PlatformUserDetailOut(PlatformUserListItemOut):
    tenant_memberships: list[PlatformTenantMembershipOut]
    workspace_memberships: list[PlatformWorkspaceMembershipOut]


class PlatformUserUpdateRequest(BaseModel):
    is_active: bool | None = None
    can_create_workspace: bool | None = None
    is_platform_admin: bool | None = None


class PlatformUserCreateRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    is_active: bool = True
    can_create_workspace: bool = False
    is_platform_admin: bool = False


class PlatformWorkspaceMemberOverviewOut(BaseModel):
    id: str
    user_id: str
    username: str
    email: str | None
    role: str
    status: str
    created_at: datetime
    updated_at: datetime


class PlatformWorkspaceListItemOut(BaseModel):
    id: str
    tenant_id: str
    tenant_name: str
    name: str
    slug: str
    status: str
    is_default: bool
    archived_at: datetime | None
    archived_by: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    founder_user_id: str | None
    founder_username: str | None
    founder_email: str | None
    member_count: int
    active_member_count: int


class PlatformWorkspaceDetailOut(PlatformWorkspaceListItemOut):
    members: list[PlatformWorkspaceMemberOverviewOut]


class PlatformTenantListItemOut(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    user_count: int
    workspace_count: int


class PlatformTenantUserOverviewOut(BaseModel):
    id: str
    user_id: str
    username: str
    email: str | None
    role: str
    status: str
    created_at: datetime
    updated_at: datetime


class PlatformTenantWorkspaceOverviewOut(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    is_default: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlatformTenantDetailOut(PlatformTenantListItemOut):
    users: list[PlatformTenantUserOverviewOut]
    workspaces: list[PlatformTenantWorkspaceOverviewOut]


class PlatformUserFlagsOut(BaseModel):
    is_active: bool
    can_create_workspace: bool
    is_platform_admin: bool
    must_change_password: bool


class PlatformRequestedContextOut(BaseModel):
    tenant_id: str | None
    workspace_id: str | None


class PlatformResolvedContextOut(BaseModel):
    tenant_id: str | None
    workspace_id: str | None
    source: str


class PlatformEffectiveTenantMembershipOut(BaseModel):
    id: str | None
    tenant_id: str | None
    role: str | None
    status: str | None


class PlatformEffectiveWorkspaceMembershipOut(BaseModel):
    id: str | None
    workspace_id: str | None
    user_id: str | None
    role: str | None
    status: str | None
    permissions_override: dict[str, bool]
    effective_permissions: dict[str, bool]


class PlatformEffectivePermissionsOut(BaseModel):
    can_access_platform_control_plane: bool
    can_create_workspace: bool


class PlatformExplainabilityOut(BaseModel):
    allowed_reasons: list[str]
    denied_reasons: list[str]


class PlatformResourceRuleOut(BaseModel):
    scope: str
    explanation: str
    counts: dict[str, int]


class PlatformUserAccessPortraitUserOut(BaseModel):
    id: str
    username: str
    email: str | None
    flags: PlatformUserFlagsOut
    compat_tenant_id: str | None


class PlatformUserRawMembershipsOut(BaseModel):
    tenant_memberships: list[PlatformTenantMembershipOut]
    workspace_memberships: list[PlatformWorkspaceMembershipOut]


class PlatformUserEffectivePortraitOut(BaseModel):
    requested_context: PlatformRequestedContextOut
    resolved_context: PlatformResolvedContextOut | None
    tenant_membership: PlatformEffectiveTenantMembershipOut
    workspace_membership: PlatformEffectiveWorkspaceMembershipOut
    platform_permissions: PlatformEffectivePermissionsOut
    explainability: PlatformExplainabilityOut


class PlatformUserAccessPortraitOut(BaseModel):
    user: PlatformUserAccessPortraitUserOut
    raw_memberships: PlatformUserRawMembershipsOut
    effective_portrait: PlatformUserEffectivePortraitOut
    resource_rules: dict[str, PlatformResourceRuleOut]


class PlatformWorkspaceIdentityOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str
    status: str
    is_default: bool


class PlatformTenantIdentityOut(BaseModel):
    id: str
    name: str
    status: str


class PlatformWorkspaceFounderOut(BaseModel):
    membership_id: str | None
    user_id: str | None
    username: str | None
    email: str | None


class PlatformWorkspaceMembershipSummaryOut(BaseModel):
    total: int
    active: int
    by_role: dict[str, int]
    active_founder_invariant_ok: bool


class PlatformWorkspacePortraitMemberOut(BaseModel):
    id: str
    user_id: str
    username: str
    email: str | None
    role: str
    status: str
    permissions_override: dict[str, bool]
    effective_permissions: dict[str, bool]
    created_at: datetime
    updated_at: datetime


class PlatformWorkspaceInviteSummaryOut(BaseModel):
    pending: int
    accepted: int
    expired: int
    revoked: int


class PlatformWorkspaceArchiveStateOut(BaseModel):
    status: str
    archived_at: datetime | None
    archived_by: str | None


class PlatformWorkspaceAccessPortraitOut(BaseModel):
    workspace: PlatformWorkspaceIdentityOut
    tenant: PlatformTenantIdentityOut
    founder: PlatformWorkspaceFounderOut
    membership_summary: PlatformWorkspaceMembershipSummaryOut
    members: list[PlatformWorkspacePortraitMemberOut]
    invite_summary: PlatformWorkspaceInviteSummaryOut
    resource_scope: dict[str, PlatformResourceRuleOut]
    archive_state: PlatformWorkspaceArchiveStateOut
