import { apiClient, resolveActiveWorkspaceId } from '../../lib/api/client';
import type {
  ComplianceAdHocRunPayload,
  ComplianceCheck,
  ComplianceCheckMutationPayload,
  ComplianceCheckRunPayload,
  ComplianceCheckUpdateInput,
  ComplianceRun,
  ComplianceRunListParams,
} from './types';
import { normalizeComplianceCheck, normalizeComplianceRun } from './normalizers';

const checksPath = () => `/workspaces/${resolveActiveWorkspaceId()}/compliance-checks`;
const runsPath = () => `/workspaces/${resolveActiveWorkspaceId()}/compliance-runs`;

const normalizeRunListParams = (params?: ComplianceRunListParams) => {
  if (!params) return undefined;

  return {
    ...params,
    created_after: params.created_after instanceof Date ? params.created_after.toISOString() : params.created_after,
    created_before: params.created_before instanceof Date ? params.created_before.toISOString() : params.created_before,
  };
};

export const complianceApi = {
  checks: {
    list: async (): Promise<ComplianceCheck[]> => {
      const { data } = await apiClient.get<unknown[]>(checksPath());
      return data.map(normalizeComplianceCheck);
    },
    get: async (checkId: string): Promise<ComplianceCheck> => {
      const { data } = await apiClient.get<unknown>(`${checksPath()}/${checkId}`);
      return normalizeComplianceCheck(data);
    },
    create: async (payload: ComplianceCheckMutationPayload): Promise<ComplianceCheck> => {
      const { data } = await apiClient.post<unknown>(checksPath(), payload);
      return normalizeComplianceCheck(data);
    },
    update: async (checkId: string, payload: ComplianceCheckUpdateInput): Promise<ComplianceCheck> => {
      const { data } = await apiClient.patch<unknown>(`${checksPath()}/${checkId}`, payload);
      return normalizeComplianceCheck(data);
    },
    delete: async (checkId: string): Promise<void> => {
      await apiClient.delete(`${checksPath()}/${checkId}`);
    },
  },
  runs: {
    list: async (params?: ComplianceRunListParams): Promise<ComplianceRun[]> => {
      const { data } = await apiClient.get<unknown[]>(runsPath(), { params: normalizeRunListParams(params) });
      return data.map(normalizeComplianceRun);
    },
    get: async (runId: string): Promise<ComplianceRun> => {
      const { data } = await apiClient.get<unknown>(`${runsPath()}/${runId}`);
      return normalizeComplianceRun(data);
    },
    create: async (payload: ComplianceAdHocRunPayload): Promise<ComplianceRun> => {
      const { data } = await apiClient.post<unknown>(runsPath(), payload);
      return normalizeComplianceRun(data);
    },
    createAdHoc: async (payload: ComplianceAdHocRunPayload): Promise<ComplianceRun> => {
      const { data } = await apiClient.post<unknown>(runsPath(), payload);
      return normalizeComplianceRun(data);
    },
    fromCheck: async (checkId: string, payload: ComplianceCheckRunPayload): Promise<ComplianceRun> => {
      const { data } = await apiClient.post<unknown>(`${checksPath()}/${checkId}/runs`, payload);
      return normalizeComplianceRun(data);
    },
  },
};
