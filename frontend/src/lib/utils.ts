import axios from 'axios';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

import type { ModelProvider } from '../types';

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export const formatDateTime = (value?: string | null) => {
  if (!value) return 'N/A';
  return new Date(value).toLocaleString();
};

export const formatRelativeTime = (value?: string | null) => {
  if (!value) return 'N/A';
  const then = new Date(value).getTime();
  const deltaMs = Date.now() - then;
  const minutes = Math.round(deltaMs / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
};

export const formatPageRange = (start?: number | null, end?: number | null) => {
  if (typeof start !== 'number' && typeof end !== 'number') return 'N/A';
  if (typeof start === 'number' && typeof end === 'number') {
    return start === end ? `p. ${start}` : `p. ${start}-${end}`;
  }
  return `p. ${start ?? end}`;
};

export const resolveProviderName = (providerId: string | null | undefined, providers: ModelProvider[]) => {
  if (!providerId) return 'System resolved';
  return providers.find((provider) => provider.id === providerId)?.name || providerId;
};

export const resolveProviderById = (providerId: string | null | undefined, providers: ModelProvider[]) =>
  providers.find((provider) => provider.id === providerId) || null;

export const resolveWorkspaceDefaultProvider = (
  workspaceDefaultProviderId: string | null | undefined,
  providers: ModelProvider[],
) => resolveProviderById(workspaceDefaultProviderId, providers);

export const describeProviderScope = (provider: ModelProvider | null | undefined) => {
  if (!provider) return 'No provider bound';
  if (provider.scope === 'workspace') return 'Workspace provider';
  if (provider.scope === 'tenant') return 'Tenant provider';
  return 'System fallback';
};

export const describeProviderOwnership = (provider: ModelProvider | null | undefined) => {
  if (!provider) return 'No provider';
  if (provider.scope === 'workspace') {
    return provider.source_provider_name ? `Workspace copy of ${provider.source_provider_name}` : 'Workspace-owned provider';
  }
  if (provider.scope === 'tenant') {
    return 'Shared provider';
  }
  return 'System fallback';
};

export const describeProviderAvailability = (provider: ModelProvider | null | undefined) => {
  if (!provider) return 'Not available';
  if (provider.scope === 'workspace') return 'Workspace-only';
  if (provider.scope === 'system') return 'Backend-only fallback';
  if (provider.share_mode === 'all') return 'Shared to all workspaces';
  if (provider.share_mode === 'selected') {
    return provider.shared_workspace_ids.length > 0
      ? `Shared to ${provider.shared_workspace_ids.length} selected workspace${provider.shared_workspace_ids.length === 1 ? '' : 's'}`
      : 'Selected workspace share';
  }
  return 'Not shared';
};

export const getProviderModelOptions = (provider: ModelProvider | null | undefined) => {
  if (!provider) return [];
  return Array.from(
    new Set(
      [provider.default_model, ...(provider.supported_models || [])]
        .map((candidate) => candidate?.trim())
        .filter((candidate): candidate is string => Boolean(candidate)),
    ),
  );
};

export const normalizeProviderModel = (providerType: string | null | undefined, model: string | null | undefined) => {
  const normalized = model?.trim();
  if (!normalized) return '';
  if (providerType === 'openai_compatible' && !normalized.startsWith('openai/')) {
    return `openai/${normalized}`;
  }
  return normalized;
};

export const providerSupportsModel = (provider: ModelProvider | null | undefined, model: string | null | undefined) => {
  if (!provider) return true;
  const normalizedModel = normalizeProviderModel(provider.provider_type, model);
  if (!normalizedModel) return false;
  const candidates = getProviderModelOptions(provider);
  return candidates
    .map((candidate) => normalizeProviderModel(provider.provider_type, candidate))
    .includes(normalizedModel);
};

export const resolveProviderModelOption = (provider: ModelProvider | null | undefined, model: string | null | undefined) => {
  if (!provider || !model?.trim()) return null;
  const normalizedModel = normalizeProviderModel(provider.provider_type, model);
  return (
    getProviderModelOptions(provider).find(
      (candidate) => normalizeProviderModel(provider.provider_type, candidate) === normalizedModel,
    ) || null
  );
};

export const inferSystemModelLabel = () => 'Not exposed by backend API';

export const getErrorMessage = (error: unknown, fallback: string) => {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    if (typeof data === 'object' && data && 'detail' in data && typeof data.detail === 'string') {
      return data.detail;
    }
    if (typeof data === 'object' && data && 'detail' in data && Array.isArray(data.detail)) {
      const messages = data.detail
        .map((item: unknown) => {
          if (typeof item === 'string') return item;
          if (typeof item === 'object' && item) {
            const maybeItem = item as { loc?: unknown; msg?: unknown };
            const location = Array.isArray(maybeItem.loc) ? maybeItem.loc.join('.') : null;
            const message = typeof maybeItem.msg === 'string' ? maybeItem.msg : null;
            if (location && message) return `${location}: ${message}`;
            if (message) return message;
          }
          return null;
        })
        .filter((value: string | null): value is string => Boolean(value));
      if (messages.length > 0) return messages.join('; ');
    }
    return error.message || fallback;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
};

export const humanizeSkillRunError = (message: string | null | undefined) => {
  const normalized = message?.trim();
  if (!normalized) return '';
  const lowered = normalized.toLowerCase();

  const knownMessages: Array<[string, string]> = [
    ['llm provider not provided', '模型提供方未正确解析。当前运行拿到了模型名，但没有可用的 provider 类型。请检查技能绑定的 provider、系统默认 provider，以及模型名格式是否匹配。'],
    ['fatal model configuration error', '模型配置无效，当前 provider 无法识别或调用这个模型。请检查已绑定 provider、默认模型和模型名格式是否匹配。'],
    ['model_not_found', '模型不存在或当前 provider 不支持这个模型。请检查模型名和 provider 配置。'],
    ['unknown model', '模型不存在或当前 provider 不支持这个模型。请检查模型名和 provider 配置。'],
    ['unsupported model', '当前 provider 不支持这个模型。请检查模型名和 provider 的支持列表。'],
    ['no model resolved for this skill', '当前技能没有解析出可运行的模型。请先绑定可用 provider，或选择一个有效模型。'],
    ['skill has no target document', '当前技能没有可查询的目标文档。请先绑定知识库或文档。'],
    ['document is not ready for querying yet', '目标文档尚未完成索引，暂时不能运行。请等待文档状态变为可查询后再试。'],
    ['llm completion failed after', '模型调用失败。请检查 provider 连通性、API key、模型名和上游服务状态。'],
  ];

  const matched = knownMessages.find(([pattern]) => lowered.includes(pattern));
  if (!matched) return normalized;
  return `${matched[1]}\n原始错误: ${normalized}`;
};
