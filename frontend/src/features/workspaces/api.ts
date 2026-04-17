import axios from 'axios';
import { apiClient, resolveActiveWorkspaceId, API_BASE_URL } from '../../lib/api/client';
import type {
  AuthTokenResponse,
  InviteClaimRequest,
  InvitePreviewResponse,
  Workspace,
  WorkspaceCreateInput,
  WorkspaceInvite,
  WorkspaceInviteAcceptResponse,
  WorkspaceListItem,
  WorkspaceInviteRole,
  WorkspaceMember,
  WorkspaceMembershipRole,
  WorkspaceMembershipStatus,
  WorkspacePermissions,
} from '../../types';

const workspacePath = (workspaceId = resolveActiveWorkspaceId()) => `/workspaces/${workspaceId}`;

export interface WorkspaceMemberCreateInput {
  user_id: string;
  role?: WorkspaceMembershipRole;
  permissions_override?: WorkspacePermissions | null;
}

export interface WorkspaceMemberUpdateInput {
  role?: WorkspaceMembershipRole;
  status?: WorkspaceMembershipStatus;
  permissions_override?: WorkspacePermissions | null;
}

export interface WorkspaceInviteCreateInput {
  email: string;
  role?: WorkspaceInviteRole;
  permissions_override?: WorkspacePermissions | null;
  expires_at?: string | null;
}

export interface WorkspaceUpdateInput {
  name?: string;
  slug?: string;
}

export const workspacesApi = {
  list: async (): Promise<WorkspaceListItem[]> => {
    const { data } = await apiClient.get<WorkspaceListItem[]>('/workspaces');
    return data;
  },
  create: async (payload: WorkspaceCreateInput): Promise<AuthTokenResponse> => {
    const { data } = await apiClient.post<AuthTokenResponse>('/workspaces', payload);
    return data;
  },
  updateWorkspace: async (payload: WorkspaceUpdateInput, workspaceId?: string): Promise<Workspace> => {
    const { data } = await apiClient.patch<Workspace>(workspacePath(workspaceId), payload);
    return data;
  },
  listMembers: async (workspaceId?: string): Promise<WorkspaceMember[]> => {
    const { data } = await apiClient.get<WorkspaceMember[]>(`${workspacePath(workspaceId)}/members`);
    return data;
  },
  createMember: async (payload: WorkspaceMemberCreateInput, workspaceId?: string): Promise<WorkspaceMember> => {
    const { data } = await apiClient.post<WorkspaceMember>(`${workspacePath(workspaceId)}/members`, payload);
    return data;
  },
  updateMember: async (membershipId: string, payload: WorkspaceMemberUpdateInput, workspaceId?: string): Promise<WorkspaceMember> => {
    const { data } = await apiClient.patch<WorkspaceMember>(`${workspacePath(workspaceId)}/members/${membershipId}`, payload);
    return data;
  },
  removeMember: async (membershipId: string, workspaceId?: string): Promise<void> => {
    await apiClient.delete(`${workspacePath(workspaceId)}/members/${membershipId}`);
  },
  transferFounder: async (target_user_id: string, workspaceId?: string) => {
    const { data } = await apiClient.post<{
      workspace_id: string;
      founder_membership: WorkspaceMember;
      previous_founder_membership: WorkspaceMember;
    }>(`${workspacePath(workspaceId)}/founder-transfer`, { target_user_id });
    return data;
  },
  archive: async (workspaceId?: string): Promise<Workspace> => {
    const { data } = await apiClient.post<Workspace>(`${workspacePath(workspaceId)}/archive`);
    return data;
  },
  listInvites: async (workspaceId?: string): Promise<WorkspaceInvite[]> => {
    const { data } = await apiClient.get<WorkspaceInvite[]>(`${workspacePath(workspaceId)}/invites`);
    return data;
  },
  createInvite: async (payload: WorkspaceInviteCreateInput, workspaceId?: string): Promise<WorkspaceInvite> => {
    const { data } = await apiClient.post<WorkspaceInvite>(`${workspacePath(workspaceId)}/invites`, payload);
    return data;
  },
  revokeInvite: async (inviteId: string, workspaceId?: string): Promise<WorkspaceInvite> => {
    const { data } = await apiClient.post<WorkspaceInvite>(`${workspacePath(workspaceId)}/invites/${inviteId}/revoke`);
    return data;
  },
  acceptInvite: async (inviteId: string): Promise<WorkspaceInviteAcceptResponse> => {
    const { data } = await apiClient.post<WorkspaceInviteAcceptResponse>(`/workspace-invites/${inviteId}/accept`);
    return data;
  },
  // Public endpoints (no auth required)
  previewInvite: async (inviteId: string): Promise<InvitePreviewResponse> => {
    const { data } = await axios.get<InvitePreviewResponse>(`${API_BASE_URL}/workspace-invites/${inviteId}/preview`);
    return data;
  },
  claimInvite: async (inviteId: string, payload: InviteClaimRequest): Promise<WorkspaceInviteAcceptResponse> => {
    const { data } = await axios.post<WorkspaceInviteAcceptResponse>(`${API_BASE_URL}/workspace-invites/${inviteId}/claim`, payload);
    return data;
  },
};
