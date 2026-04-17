import { apiClient } from '../../lib/api/client';
import type {
  PlatformTenantDetail,
  PlatformTenantListItem,
  PlatformUserAccessPortrait,
  PlatformUserDetail,
  PlatformUserListItem,
  PlatformUserUpdateInput,
  PlatformWorkspaceAccessPortrait,
  PlatformWorkspaceDetail,
  PlatformWorkspaceListItem,
  ResetPasswordResponse,
} from '../../types';

export const platformApi = {
  listUsers: async (): Promise<PlatformUserListItem[]> => {
    const { data } = await apiClient.get<PlatformUserListItem[]>('/platform/users');
    return data;
  },
  getUser: async (userId: string): Promise<PlatformUserDetail> => {
    const { data } = await apiClient.get<PlatformUserDetail>(`/platform/users/${userId}`);
    return data;
  },
  getUserAccessPortrait: async (
    userId: string,
    params?: { tenant_id?: string; workspace_id?: string },
  ): Promise<PlatformUserAccessPortrait> => {
    const { data } = await apiClient.get<PlatformUserAccessPortrait>(`/platform/users/${userId}/access-portrait`, { params });
    return data;
  },
  patchUser: async (userId: string, payload: PlatformUserUpdateInput): Promise<PlatformUserDetail> => {
    const { data } = await apiClient.patch<PlatformUserDetail>(`/platform/users/${userId}`, payload);
    return data;
  },
  resetUserPassword: async (userId: string): Promise<ResetPasswordResponse> => {
    const { data } = await apiClient.post<ResetPasswordResponse>(`/platform/users/${userId}/reset-password`);
    return data;
  },
  listWorkspaces: async (): Promise<PlatformWorkspaceListItem[]> => {
    const { data } = await apiClient.get<PlatformWorkspaceListItem[]>('/platform/workspaces');
    return data;
  },
  getWorkspace: async (workspaceId: string): Promise<PlatformWorkspaceDetail> => {
    const { data } = await apiClient.get<PlatformWorkspaceDetail>(`/platform/workspaces/${workspaceId}`);
    return data;
  },
  getWorkspaceAccessPortrait: async (workspaceId: string): Promise<PlatformWorkspaceAccessPortrait> => {
    const { data } = await apiClient.get<PlatformWorkspaceAccessPortrait>(`/platform/workspaces/${workspaceId}/access-portrait`);
    return data;
  },
  archiveWorkspace: async (workspaceId: string): Promise<PlatformWorkspaceDetail> => {
    const { data } = await apiClient.post<PlatformWorkspaceDetail>(`/platform/workspaces/${workspaceId}/archive`);
    return data;
  },
  listTenants: async (): Promise<PlatformTenantListItem[]> => {
    const { data } = await apiClient.get<PlatformTenantListItem[]>('/platform/tenants');
    return data;
  },
  getTenant: async (tenantId: string): Promise<PlatformTenantDetail> => {
    const { data } = await apiClient.get<PlatformTenantDetail>(`/platform/tenants/${tenantId}`);
    return data;
  },
};
