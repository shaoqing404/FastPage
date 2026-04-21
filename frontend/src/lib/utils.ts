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
