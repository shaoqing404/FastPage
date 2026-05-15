import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Radar, Save, Server, Trash2, Wand2 } from 'lucide-react';
import { Link } from 'react-router-dom';

import { CopyOnceModal, EmptyState, ExpertDrawer, Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { authApi } from '../features/auth/api';
import { providersApi } from '../features/providers/api';
import { workspacesApi } from '../features/workspaces/api';
import { resolveStoredWorkspace, resolveStoredWorkspaceMembership, updateStoredWorkspace } from '../lib/api/client';
import { copyTextToClipboard } from '../lib/clipboard';
import type { ApiKey, ModelProvider, WorkspaceListItem } from '../types';
import {
  cn,
  describeProviderAvailability,
  describeProviderOwnership,
  getErrorMessage,
  inferSystemModelLabel,
  resolveWorkspaceDefaultProvider,
} from '../lib/utils';

type ProviderDraft = {
  id?: string;
  provider_type: string;
  name: string;
  base_url: string;
  api_key: string;
  default_model: string;
  supported_models_text: string;
  extra_headers_text: string;
  enabled: boolean;
  is_default: boolean;
  scope: 'tenant' | 'workspace';
  share_mode: 'none' | 'all' | 'selected';
  shared_workspace_ids: string[];
};

const defaultProviderDraft = (): ProviderDraft => ({
  provider_type: 'openai_compatible',
  name: '',
  base_url: '',
  api_key: '',
  default_model: '',
  supported_models_text: '',
  extra_headers_text: '{}',
  enabled: true,
  is_default: false,
  scope: 'tenant',
  share_mode: 'all',
  shared_workspace_ids: [],
});

const parseSupportedModels = (defaultModel: string, raw: string) => {
  const values = raw
    .split(/[\n,]/)
    .map((value) => value.trim())
    .filter(Boolean);
  const normalized: string[] = [];
  for (const candidate of [defaultModel.trim(), ...values]) {
    if (!candidate || normalized.includes(candidate)) continue;
    normalized.push(candidate);
  }
  return normalized;
};

const validateProviderDraft = (draft: ProviderDraft) => {
  if (!draft.name.trim()) return 'Provider name is required.';
  if (!draft.base_url.trim()) return 'Base URL is required.';
  if (!draft.default_model.trim()) return 'Default model is required.';
  if (!draft.id && !draft.api_key.trim()) return 'API key is required when creating a provider.';
  const supportedModels = parseSupportedModels(draft.default_model, draft.supported_models_text);
  if (supportedModels.length === 0) return 'At least one supported model is required.';
  if (draft.scope === 'workspace' && draft.is_default) return 'Workspace providers cannot be marked as tenant default.';
  if (draft.scope === 'workspace' && draft.share_mode !== 'none') return 'Workspace providers cannot be shared.';
  if (draft.scope === 'tenant' && draft.share_mode === 'selected' && draft.shared_workspace_ids.length === 0) {
    return 'Selected-share tenant providers require at least one workspace id.';
  }
  if (draft.extra_headers_text.trim()) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(draft.extra_headers_text);
    } catch {
      return 'Extra headers must be valid JSON.';
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return 'Extra headers must be a JSON object.';
    }
  }
  return null;
};

type CachedApiKeySecret = {
  id: string;
  name: string;
  key_prefix: string;
  api_key: string;
  cached_at: string;
};

const readCachedApiKeySecrets = (): CachedApiKeySecret[] => {
  const raw = localStorage.getItem('cached_api_key_secrets');
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter(
          (value): value is CachedApiKeySecret =>
            Boolean(value) &&
            typeof value === 'object' &&
            typeof value.id === 'string' &&
            typeof value.name === 'string' &&
            typeof value.key_prefix === 'string' &&
            typeof value.api_key === 'string'
        )
      : [];
  } catch {
    return [];
  }
};

const writeCachedApiKeySecrets = (value: CachedApiKeySecret[]) => {
  localStorage.setItem('cached_api_key_secrets', JSON.stringify(value));
};

const EMPTY_API_KEYS: ApiKey[] = [];
const EMPTY_PROVIDERS: ModelProvider[] = [];
const EMPTY_WORKSPACES: WorkspaceListItem[] = [];

export const ControlPlanePage: React.FC = () => {
  const queryClient = useQueryClient();
  const workspaceMembership = resolveStoredWorkspaceMembership();
  const workspace = resolveStoredWorkspace();
  const canManageApiKeys = workspaceMembership?.permissions?.can_manage_api_keys === true;
  const canManageProviders = workspaceMembership?.permissions?.can_manage_providers === true;
  const [apiKeyName, setApiKeyName] = useState('');
  const [latestApiKey, setLatestApiKey] = useState<CachedApiKeySecret | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const [apiKeyError, setApiKeyError] = useState('');
  const [apiKeySuccess, setApiKeySuccess] = useState('');
  const [apiKeyInputAttention, setApiKeyInputAttention] = useState(false);
  const [hiddenApiKeyIds, setHiddenApiKeyIds] = useState<string[]>(() => {
    const raw = localStorage.getItem('hidden_api_key_ids');
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === 'string') : [];
    } catch {
      return [];
    }
  });
  const [cachedApiKeySecrets, setCachedApiKeySecrets] = useState<CachedApiKeySecret[]>(() => readCachedApiKeySecrets());
  const [editingProvider, setEditingProvider] = useState<ProviderDraft>(defaultProviderDraft());
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);
  const [isCreatingProvider, setIsCreatingProvider] = useState(false);
  const [providerError, setProviderError] = useState('');
  const [providerSuccess, setProviderSuccess] = useState('');
  const [expertOpen, setExpertOpen] = useState(false);

  const apiKeysQuery = useQuery({ queryKey: ['api-keys'], queryFn: authApi.listApiKeys, enabled: canManageApiKeys });
  const providersQuery = useQuery({ queryKey: ['providers', 'all'], queryFn: () => providersApi.list('all'), enabled: canManageProviders });
  const providerCatalogQuery = useQuery({ queryKey: ['provider-catalog'], queryFn: providersApi.listCatalog });
  const workspacesQuery = useQuery({ queryKey: ['workspaces'], queryFn: workspacesApi.list, enabled: canManageProviders });
  const apiKeys = apiKeysQuery.data ?? EMPTY_API_KEYS;
  const providers = providersQuery.data ?? EMPTY_PROVIDERS;
  const providerCatalog = providerCatalogQuery.data ?? EMPTY_PROVIDERS;
  const workspaces = workspacesQuery.data ?? EMPTY_WORKSPACES;

  const tenantDefaultProvider = useMemo(() => providers.find((provider) => provider.is_default) || null, [providers]);
  const workspaceDefaultProvider = useMemo(
    () => resolveWorkspaceDefaultProvider(workspace?.default_provider_id ?? null, providerCatalog),
    [providerCatalog, workspace?.default_provider_id],
  );
  const tenantProviders = useMemo(() => providers.filter((provider) => provider.scope === 'tenant'), [providers]);
  const workspaceProviders = useMemo(() => providers.filter((provider) => provider.scope === 'workspace'), [providers]);
  const systemProviders = useMemo(() => providers.filter((provider) => provider.scope === 'system'), [providers]);
  const importedSourceIds = useMemo(
    () => new Set(workspaceProviders.map((provider) => provider.source_provider_id).filter((value): value is string => Boolean(value))),
    [workspaceProviders],
  );
  const shareableWorkspaces = useMemo(
    () => workspaces.filter((item) => item.status === 'active'),
    [workspaces],
  );
  const visibleApiKeys = useMemo(() => apiKeys.filter((key) => !hiddenApiKeyIds.includes(key.id)), [apiKeys, hiddenApiKeyIds]);
  const cachedApiKeysById = useMemo(() => new Map(cachedApiKeySecrets.map((item) => [item.id, item])), [cachedApiKeySecrets]);
  const pageError = [apiKeysQuery.error, providersQuery.error, providerCatalogQuery.error, workspacesQuery.error]
    .filter(Boolean)
    .map((error) => getErrorMessage(error, 'Control Plane data failed to load'))
    .join(' · ');
  const apiKeyMetricValue = canManageApiKeys ? visibleApiKeys.length : 'Restricted';
  const providerMetricValue = canManageProviders ? providers.length : providerCatalog.length;
  const defaultProviderMetricValue = workspaceDefaultProvider?.name || tenantDefaultProvider?.name || 'None';
  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === selectedProviderId) || null,
    [providers, selectedProviderId],
  );
  const selectedProviderReadOnly = selectedProvider?.managed_by_system === true;

  const createApiKeyMutation = useMutation({
    mutationFn: (payload: { name: string }) => authApi.createApiKey(payload),
    onSuccess: (data) => {
      const cachedSecret = {
        id: data.id,
        name: data.name,
        key_prefix: data.key_prefix,
        api_key: data.api_key,
        cached_at: new Date().toISOString(),
      };
      const nextCachedSecrets = [cachedSecret, ...cachedApiKeySecrets.filter((item) => item.id !== data.id)];
      setCachedApiKeySecrets(nextCachedSecrets);
      writeCachedApiKeySecrets(nextCachedSecrets);
      setLatestApiKey(cachedSecret);
      setCopied(false);
      setCopyError('');
      setApiKeyError('');
      setApiKeySuccess('Workspace API key created.');
      setApiKeyName('');
      setApiKeyInputAttention(false);
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
    },
    onError: (error: unknown) => {
      setApiKeySuccess('');
      setApiKeyError(getErrorMessage(error, 'API key creation failed'));
    },
  });

  const revokeApiKeyMutation = useMutation({
    mutationFn: (id: string) => authApi.revokeApiKey(id),
    onSuccess: (_, id) => {
      const nextCachedSecrets = cachedApiKeySecrets.filter((item) => item.id !== id);
      setCachedApiKeySecrets(nextCachedSecrets);
      writeCachedApiKeySecrets(nextCachedSecrets);
      if (latestApiKey?.id === id) {
        setLatestApiKey(null);
      }
      setApiKeyError('');
      setApiKeySuccess('Workspace API key revoked.');
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
    },
    onError: (error: unknown) => {
      setApiKeySuccess('');
      setApiKeyError(getErrorMessage(error, 'API key revoke failed'));
    },
  });

  const saveProviderMutation = useMutation({
    mutationFn: async (draft: ProviderDraft) => {
      const extra_headers = draft.extra_headers_text.trim() ? JSON.parse(draft.extra_headers_text) : {};
      const supported_models = parseSupportedModels(draft.default_model, draft.supported_models_text);
      const shared_workspace_ids = draft.shared_workspace_ids;
      const payload = {
        provider_type: draft.provider_type,
        name: draft.name,
        base_url: draft.base_url,
        default_model: draft.default_model,
        supported_models,
        extra_headers,
        enabled: draft.enabled,
        is_default: draft.is_default,
        scope: draft.scope,
        share_mode: draft.scope === 'workspace' ? 'none' : draft.share_mode,
        shared_workspace_ids,
        ...(draft.api_key ? { api_key: draft.api_key } : {}),
      };
      if (draft.id) return providersApi.update(draft.id, payload);
      return providersApi.create({ ...payload, api_key: draft.api_key });
    },
    onSuccess: (provider) => {
      setProviderError('');
      setProviderSuccess(editingProvider.id ? 'Provider updated.' : 'Provider created.');
      loadProvider(provider);
      setSelectedProviderId(provider.id);
      setIsCreatingProvider(false);
      setExpertOpen(false);
      queryClient.setQueryData<ModelProvider[]>(['providers', 'all'], (current = []) => {
        const existingIndex = current.findIndex((item) => item.id === provider.id);
        if (existingIndex >= 0) {
          const next = [...current];
          next[existingIndex] = provider;
          return next;
        }
        return [provider, ...current];
      });
      queryClient.invalidateQueries({ queryKey: ['providers', 'all'] });
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
    },
    onError: (error: unknown) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Provider save failed'));
    },
  });

  const deleteProviderMutation = useMutation({
    mutationFn: (id: string) => providersApi.delete(id),
    onSuccess: () => {
      setProviderError('');
      setProviderSuccess('Provider deleted.');
      queryClient.invalidateQueries({ queryKey: ['providers', 'all'] });
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
      setSelectedProviderId(null);
      setIsCreatingProvider(false);
      setEditingProvider(defaultProviderDraft());
    },
    onError: (error: unknown) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Provider delete failed'));
    },
  });

  const probeModelsMutation = useMutation({
    mutationFn: (id: string) => providersApi.probeModels(id),
    onSuccess: (provider) => {
      setProviderError('');
      setProviderSuccess(`Model probe completed for ${provider.name}.`);
      loadProvider(provider);
      queryClient.setQueryData<ModelProvider[]>(['providers', 'all'], (current = []) => {
        const existingIndex = current.findIndex((item) => item.id === provider.id);
        if (existingIndex >= 0) {
          const next = [...current];
          next[existingIndex] = provider;
          return next;
        }
        return [provider, ...current];
      });
      queryClient.invalidateQueries({ queryKey: ['providers', 'all'] });
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
    },
    onError: (error: unknown) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Provider model probe failed'));
    },
  });

  const [probeEndpointResults, setProbeEndpointResults] = useState<Record<string, { status: string; latency_ms: number | null; error_redacted: string | null }>>({});
  const [probingEndpoint, setProbingEndpoint] = useState<string | null>(null);
  const handleProbeEndpoint = async (providerId: string, endpointId: string, capability: string) => {
    setProbingEndpoint(endpointId);
    try {
      const results = await providersApi.probeRuntime(providerId, { capability: capability as 'chat' | 'embedding' | 'rerank' });
      const match = results.find((r) => r.capability === capability);
      if (match) {
        setProbeEndpointResults((prev) => ({ ...prev, [endpointId]: { status: match.status, latency_ms: match.latency_ms, error_redacted: match.error_redacted } }));
        setProviderError('');
        setProviderSuccess(`Endpoint probe: ${match.status} (${match.latency_ms ?? '?'}ms)`);
      }
    } catch (err) {
      setProbeEndpointResults((prev) => ({ ...prev, [endpointId]: { status: 'unhealthy', latency_ms: null, error_redacted: getErrorMessage(err, 'Probe failed') } }));
    } finally {
      setProbingEndpoint(null);
    }
  };

  const workspaceDefaultMutation = useMutation({
    mutationFn: (default_provider_id: string | null) => workspacesApi.updateDefaultProvider({ default_provider_id }),
    onSuccess: (updatedWorkspace) => {
      updateStoredWorkspace(updatedWorkspace);
      setProviderError('');
      setProviderSuccess(updatedWorkspace.default_provider_id ? 'Workspace default provider updated.' : 'Workspace default provider cleared.');
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
    },
    onError: (error: unknown) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Workspace default provider update failed'));
    },
  });

  const importProviderMutation = useMutation({
    mutationFn: (providerId: string) => providersApi.importToWorkspace(providerId),
    onSuccess: () => {
      setProviderError('');
      setProviderSuccess('Tenant provider imported into this workspace.');
      queryClient.invalidateQueries({ queryKey: ['providers', 'all'] });
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
    },
    onError: (error: unknown) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Provider import failed'));
    },
  });

  const loadProvider = (provider: ModelProvider) => {
    setSelectedProviderId(provider.id);
    setIsCreatingProvider(false);
    setEditingProvider({
      id: provider.id,
      provider_type: provider.provider_type,
      name: provider.name,
      base_url: provider.base_url,
      api_key: '',
      default_model: provider.default_model,
      supported_models_text: (provider.supported_models || []).join('\n'),
      extra_headers_text: JSON.stringify(provider.extra_headers || {}, null, 2),
      enabled: provider.enabled,
      is_default: provider.is_default,
      scope: provider.scope === 'workspace' ? 'workspace' : 'tenant',
      share_mode: provider.scope === 'workspace' ? 'none' : provider.share_mode,
      shared_workspace_ids: provider.shared_workspace_ids || [],
    });
    setProviderError('');
    setProviderSuccess('');
  };

  const startCreateProvider = () => {
    setSelectedProviderId(null);
    setIsCreatingProvider(true);
    setEditingProvider(defaultProviderDraft());
    setProviderError('');
    setProviderSuccess('');
  };

  const toggleSharedWorkspace = (workspaceId: string) => {
    setEditingProvider((draft) => {
      const nextIds = draft.shared_workspace_ids.includes(workspaceId)
        ? draft.shared_workspace_ids.filter((value) => value !== workspaceId)
        : [...draft.shared_workspace_ids, workspaceId];
      return { ...draft, shared_workspace_ids: nextIds };
    });
  };

  const handleCopyKey = async () => {
    if (!latestApiKey) return;
    try {
      await copyTextToClipboard(latestApiKey.api_key);
      setCopied(true);
      setCopyError('');
    } catch (error) {
      setCopied(false);
      setCopyError(getErrorMessage(error, 'Clipboard access is unavailable in this context. Manually select the key text in the field above and copy it before closing.'));
    }
  };

  const hideApiKey = (keyId: string) => {
    setHiddenApiKeyIds((current) => {
      const next = current.includes(keyId) ? current : [...current, keyId];
      localStorage.setItem('hidden_api_key_ids', JSON.stringify(next));
      return next;
    });
  };

  const nudgeApiKeyNameInput = () => {
    setApiKeyInputAttention(false);
    window.requestAnimationFrame(() => setApiKeyInputAttention(true));
  };

  const openCachedApiKey = (keyId: string) => {
    const cachedSecret = cachedApiKeysById.get(keyId);
    if (!cachedSecret) return;
    setLatestApiKey(cachedSecret);
    setCopied(false);
    setCopyError('');
  };

  const handleProviderSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canManageProviders) {
      setProviderSuccess('');
      setProviderError('The current workspace membership cannot manage providers.');
      return;
    }
    const validationError = validateProviderDraft(editingProvider);
    if (validationError) {
      setProviderSuccess('');
      setProviderError(validationError);
      return;
    }
    setProviderError('');
    saveProviderMutation.mutate(editingProvider);
  };

  return (
    <div className="space-y-8">
      <SectionToolbar title="Provider Hub" description="Manage workspace API keys, shared providers, workspace-owned providers, and execution defaults in one operator-facing surface." />

      {pageError && (
        <InlineAlert tone="danger" title="Control Plane data did not load cleanly">
          {pageError}
        </InlineAlert>
      )}

      {(!canManageApiKeys || !canManageProviders) && (
        <InlineAlert tone="warning" title="Control Plane actions are capability-gated">
          API keys require `can_manage_api_keys`. Provider profiles require `can_manage_providers`. The current page now disables actions the session cannot perform instead of relying on backend 403s.
        </InlineAlert>
      )}

      <InlineAlert tone="default" title="Provider ownership model">
        “Tenant provider” is an internal ownership term. In product-facing flows this should be read as a shared provider that can be made available to one or more workspaces, while workspace providers remain owned by the current workspace only.
      </InlineAlert>

      <div className="grid grid-cols-4 gap-4">
        <KeyMetric label="API keys" value={apiKeyMetricValue} hint={canManageApiKeys ? (hiddenApiKeyIds.length > 0 ? `${hiddenApiKeyIds.length} hidden from view` : 'Workspace-scoped programmatic access') : 'Requires can_manage_api_keys'} />
        <KeyMetric label="Providers" value={providerMetricValue} hint={`${providerCatalog.filter((provider) => provider.bindable_in_current_workspace).length} available in current workspace`} />
        <KeyMetric label="Default provider" value={defaultProviderMetricValue} hint={workspaceDefaultProvider ? 'Workspace default provider' : (tenantDefaultProvider ? 'Tenant-shared default provider' : 'Backend system fallback may resolve')} />
        <KeyMetric label="System default" value={inferSystemModelLabel()} hint="Separate from the configured default provider. Current backend env-derived value is not exposed to this frontend API." />
      </div>

      <div className="provider-workbench">
        <div className="space-y-6">
          <GlassPanel
            title="API access"
            subtitle="Create workspace API keys, copy them once, and jump straight into the documented service contract."
            actions={(
              <Link to="/providers/docs" className="btn-secondary">
                <span>View API docs</span>
              </Link>
            )}
          >
          <div className="space-y-4">
            <form
              className="flex gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (!canManageApiKeys) return;
                if (!apiKeyName.trim()) {
                  nudgeApiKeyNameInput();
                  return;
                }
                createApiKeyMutation.mutate({ name: apiKeyName.trim() });
              }}
            >
              <input
                value={apiKeyName}
                onChange={(event) => {
                  setApiKeyName(event.target.value);
                  if (event.target.value.trim()) setApiKeyInputAttention(false);
                }}
                onAnimationEnd={() => setApiKeyInputAttention(false)}
                className={cn('field flex-1', apiKeyInputAttention && 'field-attention')}
                placeholder="automation-bot"
              />
              <button
                type="submit"
                className="btn-primary"
                onClick={() => {
                  if (!apiKeyName.trim()) nudgeApiKeyNameInput();
                }}
                disabled={!canManageApiKeys}
              >
                <Plus size={16} />
                <span>Create</span>
              </button>
            </form>

            {!canManageApiKeys && (
              <InlineAlert tone="warning" title="API key management is read-only">
                The current workspace membership does not grant `can_manage_api_keys`.
              </InlineAlert>
            )}
            {apiKeyError && <InlineAlert tone="danger" title="API key action failed">{apiKeyError}</InlineAlert>}
            {apiKeySuccess && (
              <InlineAlert
                tone="success"
                title="API key updated"
                action={(
                  <Link to="/providers/docs" className="btn-secondary">
                    <span>Open docs</span>
                  </Link>
                )}
              >
                {apiKeySuccess}
              </InlineAlert>
            )}

            <div className="space-y-3">
              {visibleApiKeys.length > 0 ? (
                visibleApiKeys.map((key) => (
                  <div key={key.id} className="list-row">
                    <div>
                      <p className="font-medium text-slate-900">{key.name}</p>
                      <p className="text-sm text-slate-500">{key.key_prefix}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <StatusBadge tone={key.status === 'active' ? 'success' : 'danger'}>{key.status}</StatusBadge>
                      {cachedApiKeysById.has(key.id) && (
                        <button type="button" className="btn-ghost text-slate-600" onClick={() => openCachedApiKey(key.id)}>
                          Copy again
                        </button>
                      )}
                      {key.status !== 'active' && (
                        <button type="button" className="btn-ghost text-slate-500" onClick={() => hideApiKey(key.id)}>
                          Hide
                        </button>
                      )}
                      <button type="button" className="btn-ghost text-red-600" onClick={() => revokeApiKeyMutation.mutate(key.id)} disabled={!canManageApiKeys}>
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <EmptyState
                  title={canManageApiKeys ? 'No workspace API keys yet' : 'API keys are hidden by capability'}
                  description={
                    canManageApiKeys
                      ? 'Create a workspace-scoped API key here to unblock automation or service integrations.'
                      : 'The current workspace membership cannot list or manage workspace API keys.'
                  }
                />
              )}
            </div>
          </div>
          </GlassPanel>

          <GlassPanel title="Execution defaults" subtitle="Workspace and tenant defaults stay visible without competing with the provider editor.">
            <div className="space-y-4">
              <div className="surface-soft p-4">
                <p className="metric-label">Resolution order</p>
                <ol className="mt-3 space-y-2 text-sm text-slate-700">
                  <li>1. Skill-bound provider</li>
                  <li>2. Runtime test override</li>
                  <li>3. Workspace default provider</li>
                  <li>4. Tenant default provider</li>
                  <li>5. Backend system default provider</li>
                </ol>
              </div>
              <div className="surface-soft p-4">
                <p className="metric-label">Workspace default binding</p>
                <div className="mt-3 space-y-3">
                  <select
                    className="field"
                    value={workspace?.default_provider_id || ''}
                    onChange={(event) => workspaceDefaultMutation.mutate(event.target.value || null)}
                    disabled={!canManageProviders || workspaceDefaultMutation.isPending}
                  >
                    <option value="">No workspace default provider</option>
                    {providerCatalog
                      .filter((provider) => provider.is_workspace_default_candidate)
                      .map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.name} ({provider.scope})
                        </option>
                      ))}
                  </select>
                  <p className="text-sm text-slate-500">
                    Current workspace default: {workspaceDefaultProvider ? `${workspaceDefaultProvider.name} · ${workspaceDefaultProvider.default_model}` : 'Not configured'}
                  </p>
                </div>
              </div>
              <div className="surface-soft p-4">
                <p className="metric-label">Tenant default provider</p>
                <p className="mt-2 text-sm font-medium text-slate-900">{tenantDefaultProvider ? `${tenantDefaultProvider.name} · ${tenantDefaultProvider.default_model}` : 'Not configured'}</p>
                <p className="mt-1 text-sm text-slate-500">
                  {tenantDefaultProvider
                    ? 'If neither the skill nor runtime override binds a provider and no workspace default is set, this tenant default is used next.'
                    : 'If no tenant default provider is configured, resolution falls through to backend system fallback.'}
                </p>
              </div>
              <div className="surface-soft p-4">
                <p className="metric-label">Backend system default</p>
                <p className="mt-2 text-sm font-medium text-slate-900">Current LLM base URL and inferred model are not exposed in the existing frontend API.</p>
                <p className="mt-1 text-sm text-slate-500">
                  The workbench surfaces fallback behavior, but it does not pretend to expose hidden backend environment values.
                </p>
              </div>
            </div>
          </GlassPanel>

          <GlassPanel
            title="Provider library"
            subtitle="Select one provider to edit on the right. Create starts a new draft instead of pushing the editor above the list."
            actions={(
              <button type="button" className="btn-primary" onClick={startCreateProvider} disabled={!canManageProviders}>
                <Plus size={16} />
                <span>Create provider</span>
              </button>
            )}
          >
            {canManageProviders ? (
              <div className="space-y-6">
                {[
                  { title: 'Shared providers', providers: tenantProviders, showImport: true },
                  { title: 'Workspace-owned providers', providers: workspaceProviders, showImport: false },
                  { title: 'System fallback', providers: systemProviders, showImport: false },
                ].map((section) => (
                  <div key={section.title} className="space-y-3">
                    <p className="text-sm font-medium uppercase tracking-[0.18em] text-slate-500">{section.title}</p>
                    <div className="space-y-3">
                      {section.providers.length > 0 ? (
                        section.providers.map((provider) => (
                          <div
                            key={provider.id}
                            className={cn('provider-library-item', selectedProviderId === provider.id && 'provider-library-item-active')}
                          >
                            <button type="button" className="flex min-w-0 flex-1 items-start justify-between gap-4 text-left" onClick={() => loadProvider(provider)}>
                              <div className="space-y-2">
                                <div className="flex items-center gap-2">
                                  <Server size={16} className="text-slate-400" />
                                  <p className="font-medium text-slate-900">{provider.name}</p>
                                </div>
                                <p className="text-sm text-slate-500">
                                  {provider.provider_type} · {provider.default_model}
                                </p>
                                <p className="text-sm text-slate-400">
                                  {describeProviderOwnership(provider)} · {describeProviderAvailability(provider)}
                                </p>
                              </div>
                              <div className="flex flex-col items-end gap-2 text-right">
                                <StatusBadge tone={provider.enabled ? 'success' : 'danger'}>{provider.enabled ? 'enabled' : 'disabled'}</StatusBadge>
                                {provider.scope === 'tenant' && provider.is_default && <p className="text-sm text-blue-600">tenant default</p>}
                                {provider.scope === 'workspace' && workspace?.default_provider_id === provider.id && <p className="text-sm text-blue-600">workspace default</p>}
                              </div>
                            </button>
                            {section.showImport && provider.available_in_current_workspace && !importedSourceIds.has(provider.id) && (
                              <button
                                type="button"
                                className="btn-secondary shrink-0"
                                onClick={() => importProviderMutation.mutate(provider.id)}
                                disabled={importProviderMutation.isPending}
                              >
                                <span>Import to workspace</span>
                              </button>
                            )}
                          </div>
                        ))
                      ) : (
                        <EmptyState title={`No ${section.title.toLowerCase()} yet`} description="Nothing is configured in this section yet." />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title="Provider profiles are hidden by capability"
                description="The current workspace membership cannot list or manage provider profiles in this workspace."
              />
            )}
          </GlassPanel>
        </div>

        <GlassPanel
          title={selectedProvider ? selectedProvider.name : editingProvider.id ? 'Provider editor' : 'Provider details'}
          subtitle={selectedProvider
            ? 'Edit the currently selected provider profile.'
            : 'Select a provider from the library or create a new one to begin editing.'}
          actions={(
            <div className="flex items-center gap-2">
              {editingProvider.id && (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => probeModelsMutation.mutate(editingProvider.id!)}
                  disabled={probeModelsMutation.isPending || !canManageProviders || selectedProviderReadOnly}
                >
                  <Radar size={16} />
                  <span>{probeModelsMutation.isPending ? 'Probing…' : 'Probe models'}</span>
                </button>
              )}
              <button type="button" className="btn-secondary" onClick={() => setExpertOpen(true)} disabled={!canManageProviders || selectedProviderReadOnly}>
                <Wand2 size={16} />
                <span>Expert headers</span>
              </button>
            </div>
          )}
        >
          <form className="space-y-5" onSubmit={handleProviderSubmit}>
            {providerError && <InlineAlert tone="danger" title="Provider save failed">{providerError}</InlineAlert>}
            {providerSuccess && <InlineAlert tone="success" title="Provider saved">{providerSuccess}</InlineAlert>}
            {!canManageProviders && (
              <InlineAlert tone="warning" title="Provider management is read-only">
                The current workspace membership does not grant `can_manage_providers`.
              </InlineAlert>
            )}
            {selectedProviderReadOnly && (
              <InlineAlert tone="default" title="System fallback is read-only">
                This provider is synced from backend environment settings. It stays visible for troubleshooting and fallback explanation, but it cannot be edited, shared, imported, or set as a user-facing saved default here.
              </InlineAlert>
            )}

            {!selectedProvider && !isCreatingProvider ? (
              <EmptyState
                title={canManageProviders ? 'Select a provider or create a new one' : 'Provider editing is unavailable'}
                description={
                  canManageProviders
                    ? 'Pick a provider from the library to edit it, or start a new provider draft from the left column.'
                    : 'This session can view defaults and API access, but it cannot create or edit provider profiles.'
                }
              />
            ) : (
              <>
                {!selectedProvider && isCreatingProvider && (
                  <InlineAlert tone="default" title="New provider draft">
                    This draft is not saved yet. It will appear in the provider library only after you create it.
                  </InlineAlert>
                )}

                <div className="grid grid-cols-2 gap-5">
                  <Field label="Provider name" required>
                    <input value={editingProvider.name} onChange={(event) => setEditingProvider((draft) => ({ ...draft, name: event.target.value }))} className="field" disabled={!canManageProviders || selectedProviderReadOnly} required />
                  </Field>
                  <Field label="Ownership scope" hint="Tenant providers can be shared to workspaces. Workspace providers belong only to the current workspace.">
                    <select
                      value={editingProvider.scope}
                      onChange={(event) =>
                        setEditingProvider((draft) => ({
                          ...draft,
                          scope: event.target.value as 'tenant' | 'workspace',
                          share_mode: event.target.value === 'workspace' ? 'none' : draft.share_mode === 'none' ? 'all' : draft.share_mode,
                          is_default: event.target.value === 'workspace' ? false : draft.is_default,
                        }))
                      }
                      className="field"
                      disabled={!canManageProviders || Boolean(editingProvider.id) || selectedProviderReadOnly}
                    >
                      <option value="tenant">tenant</option>
                      <option value="workspace">workspace</option>
                    </select>
                  </Field>
                  <Field label="Provider type">
                    <select value={editingProvider.provider_type} onChange={(event) => setEditingProvider((draft) => ({ ...draft, provider_type: event.target.value }))} className="field" disabled={!canManageProviders || selectedProviderReadOnly}>
                      <option value="openai_compatible">openai_compatible</option>
                      <option value="dashscope">dashscope</option>
                      <option value="deepseek">deepseek</option>
                    </select>
                  </Field>
                  <div className="col-span-2">
                    <Field label="Base URL" required>
                      <input value={editingProvider.base_url} onChange={(event) => setEditingProvider((draft) => ({ ...draft, base_url: event.target.value }))} className="field" disabled={!canManageProviders || selectedProviderReadOnly} required />
                    </Field>
                  </div>
                  <Field label="Default model" required hint="This seeds provider-aware model inputs in Skills and Chat.">
                    <input value={editingProvider.default_model} onChange={(event) => setEditingProvider((draft) => ({ ...draft, default_model: event.target.value }))} className="field" disabled={!canManageProviders || selectedProviderReadOnly} required />
                  </Field>
                  <Field label="Supported models" hint="One per line or comma-separated. The default model is always included.">
                    <textarea
                      value={editingProvider.supported_models_text}
                      onChange={(event) => setEditingProvider((draft) => ({ ...draft, supported_models_text: event.target.value }))}
                      className="field min-h-[118px]"
                      disabled={!canManageProviders || selectedProviderReadOnly}
                      placeholder="deepseek-chat&#10;deepseek-reasoner"
                    />
                  </Field>
                  <Field label="API key" hint={editingProvider.id ? 'Leave empty to keep the existing secret.' : 'Stored securely after creation.'}>
                    <input
                      value={editingProvider.api_key}
                      onChange={(event) => setEditingProvider((draft) => ({ ...draft, api_key: event.target.value }))}
                      className="field"
                      disabled={!canManageProviders || selectedProviderReadOnly}
                      placeholder={editingProvider.id ? 'Leave blank to keep existing key' : 'Paste provider key'}
                    />
                  </Field>
                  {editingProvider.scope === 'tenant' && (
                    <>
                      <Field label="Availability" hint="Shared providers can be made available to every workspace or only selected workspaces.">
                        <select
                          value={editingProvider.share_mode}
                          onChange={(event) => setEditingProvider((draft) => ({ ...draft, share_mode: event.target.value as 'none' | 'all' | 'selected' }))}
                          className="field"
                          disabled={!canManageProviders || selectedProviderReadOnly}
                        >
                          <option value="all">all workspaces</option>
                          <option value="selected">selected workspaces</option>
                          <option value="none">not shared</option>
                        </select>
                      </Field>
                      <Field label="Shared workspaces" hint="When availability is set to selected workspaces, choose the workspaces that may bind this provider.">
                        <div className="space-y-3">
                          <div className="rounded-[24px] border border-white/75 bg-white/58 p-4">
                            {editingProvider.share_mode !== 'selected' ? (
                              <p className="text-sm text-slate-500">Switch availability to selected workspaces to pick where this shared provider appears.</p>
                            ) : shareableWorkspaces.length === 0 ? (
                              <p className="text-sm text-slate-500">No accessible active workspaces are available to select from this session.</p>
                            ) : (
                              <div className="space-y-3">
                                {shareableWorkspaces.map((item) => (
                                  <label key={item.id} className="flex items-start gap-3 text-sm text-slate-700">
                                    <input
                                      type="checkbox"
                                      checked={editingProvider.shared_workspace_ids.includes(item.id)}
                                      onChange={() => toggleSharedWorkspace(item.id)}
                                      disabled={!canManageProviders || selectedProviderReadOnly || editingProvider.share_mode !== 'selected'}
                                    />
                                    <span>
                                      <span className="font-medium text-slate-900">{item.name}</span>
                                      <span className="block text-xs text-slate-500">
                                        {item.slug}
                                        {item.is_current ? ' · current workspace' : ''}
                                      </span>
                                    </span>
                                  </label>
                                ))}
                              </div>
                            )}
                          </div>
                          <p className="text-xs text-slate-500">Only workspaces visible to the current session are listed here.</p>
                        </div>
                      </Field>
                    </>
                  )}
                </div>

                <div className="flex gap-6 rounded-[24px] border border-white/75 bg-white/58 p-4">
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={editingProvider.enabled} onChange={(event) => setEditingProvider((draft) => ({ ...draft, enabled: event.target.checked }))} disabled={!canManageProviders || selectedProviderReadOnly} />
                    <span>Enabled</span>
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={editingProvider.is_default} onChange={(event) => setEditingProvider((draft) => ({ ...draft, is_default: event.target.checked }))} disabled={!canManageProviders || selectedProviderReadOnly} />
                    <span>Tenant default provider</span>
                  </label>
                </div>

                {editingProvider.scope === 'tenant' && (
                  <InlineAlert tone="default" title="Shared provider lifecycle">
                    Sharing keeps this provider tenant-owned. Importing creates an independent workspace-owned copy that no longer updates automatically with the shared source.
                  </InlineAlert>
                )}

                {editingProvider.id && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <Server size={16} className="text-slate-500" />
                      <span className="text-sm font-semibold text-slate-700">Capability Endpoints</span>
                    </div>
                    {selectedProvider?.endpoints && selectedProvider.endpoints.length > 0 ? (
                      <div className="space-y-2">
                        {selectedProvider.endpoints.map((ep) => {
                          const probeState = probeEndpointResults[ep.id];
                          const healthColor = ep.health_status === 'healthy' ? 'bg-emerald-500' : ep.health_status === 'unhealthy' ? 'bg-red-500' : 'bg-slate-300';
                          const currentHealth = probeState?.status === 'healthy' ? 'bg-emerald-500' : probeState?.status === 'unhealthy' ? 'bg-red-500' : healthColor;
                          return (
                            <div key={ep.id} className="flex items-center gap-3 rounded-[16px] border border-slate-200 bg-white/70 p-3 text-sm">
                              <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 uppercase">
                                {ep.capability}
                              </span>
                              <span className="text-slate-500 flex-1 truncate">{ep.model}</span>
                              <span className={cn('h-2 w-2 rounded-full shrink-0', currentHealth)} title={ep.health_status} />
                              {ep.last_probe_latency_ms != null && <span className="text-xs text-slate-400">{ep.last_probe_latency_ms}ms</span>}
                              <button
                                type="button"
                                className="btn-secondary text-xs py-1 px-2"
                                disabled={probingEndpoint === ep.id || !canManageProviders}
                                onClick={() => handleProbeEndpoint(editingProvider.id!, ep.id, ep.capability)}
                              >
                                <Radar size={12} />
                                <span>{probingEndpoint === ep.id ? '...' : 'Test'}</span>
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">No capability endpoints configured. Save this provider or run a model probe to auto-populate endpoints.</p>
                    )}
                    {probeEndpointResults && Object.values(probeEndpointResults).some((r) => r.error_redacted) && (
                      <p className="text-xs text-red-600">{Object.values(probeEndpointResults).find((r) => r.error_redacted)?.error_redacted}</p>
                    )}
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-3">
                  <button type="submit" className="btn-primary" disabled={saveProviderMutation.isPending || !canManageProviders || selectedProviderReadOnly}>
                    <Save size={16} />
                    <span>{saveProviderMutation.isPending ? 'Saving…' : editingProvider.id ? 'Update provider' : 'Create provider'}</span>
                  </button>
                  {editingProvider.id && (
                    <button type="button" className="btn-ghost text-red-600" onClick={() => deleteProviderMutation.mutate(editingProvider.id!)} disabled={!canManageProviders || selectedProviderReadOnly}>
                      <Trash2 size={16} />
                      <span>Delete</span>
                    </button>
                  )}
                  <button type="button" className="btn-secondary" onClick={startCreateProvider}>
                    New draft
                  </button>
                </div>
              </>
            )}
          </form>
        </GlassPanel>
      </div>

      <CopyOnceModal
        open={Boolean(latestApiKey)}
        title="Copy API key"
        subtitle="This raw key is available in this browser cache so you can copy it again later on the same machine."
        value={latestApiKey?.api_key || ''}
        copied={copied}
        copyError={copyError}
        footerNote="This browser keeps a local cached copy for operator convenience. Clear browser storage or revoke the key if that is no longer acceptable."
        onCopy={handleCopyKey}
        onClose={() => {
          setLatestApiKey(null);
          setCopyError('');
        }}
        meta={
          latestApiKey && (
            <div className="space-y-1">
              <p className="font-medium text-slate-900">{latestApiKey.name}</p>
              <p>{latestApiKey.key_prefix}</p>
            </div>
          )
        }
      />

      <ExpertDrawer open={expertOpen} onClose={() => setExpertOpen(false)} title="Provider expert headers" description="Use this only when a provider requires custom headers beyond the standard API key and base URL.">
        <Field label="Extra headers JSON">
          <textarea
            value={editingProvider.extra_headers_text}
            onChange={(event) => setEditingProvider((draft) => ({ ...draft, extra_headers_text: event.target.value }))}
            className="field min-h-[220px] font-mono text-xs"
            disabled={!canManageProviders || selectedProviderReadOnly}
          />
        </Field>
      </ExpertDrawer>
    </div>
  );
};
