import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Radar, Save, Server, Trash2, Wand2 } from 'lucide-react';

import { CopyOnceModal, EmptyState, ExpertDrawer, Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { authApi } from '../features/auth/api';
import { providersApi } from '../features/providers/api';
import { resolveStoredWorkspaceMembership } from '../lib/api/client';
import type { ApiKey, ModelProvider } from '../types';
import { cn, getErrorMessage, inferSystemModelLabel } from '../lib/utils';

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

export const ControlPlanePage: React.FC = () => {
  const queryClient = useQueryClient();
  const workspaceMembership = resolveStoredWorkspaceMembership();
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
  const [providerError, setProviderError] = useState('');
  const [providerSuccess, setProviderSuccess] = useState('');
  const [expertOpen, setExpertOpen] = useState(false);

  const apiKeysQuery = useQuery({ queryKey: ['api-keys'], queryFn: authApi.listApiKeys, enabled: canManageApiKeys });
  const providersQuery = useQuery({ queryKey: ['providers'], queryFn: providersApi.list, enabled: canManageProviders });
  const apiKeys = apiKeysQuery.data ?? EMPTY_API_KEYS;
  const providers = providersQuery.data ?? EMPTY_PROVIDERS;

  const tenantDefaultProvider = useMemo(() => providers.find((provider) => provider.is_default) || null, [providers]);
  const visibleApiKeys = useMemo(() => apiKeys.filter((key) => !hiddenApiKeyIds.includes(key.id)), [apiKeys, hiddenApiKeyIds]);
  const cachedApiKeysById = useMemo(() => new Map(cachedApiKeySecrets.map((item) => [item.id, item])), [cachedApiKeySecrets]);
  const pageError = [apiKeysQuery.error, providersQuery.error]
    .filter(Boolean)
    .map((error) => getErrorMessage(error, 'Control Plane data failed to load'))
    .join(' · ');
  const apiKeyMetricValue = canManageApiKeys ? visibleApiKeys.length : 'Restricted';
  const providerMetricValue = canManageProviders ? providers.length : 'Restricted';
  const defaultProviderMetricValue = canManageProviders ? tenantDefaultProvider?.name || 'None' : 'Restricted';

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
      const payload = {
        provider_type: draft.provider_type,
        name: draft.name,
        base_url: draft.base_url,
        default_model: draft.default_model,
        supported_models,
        extra_headers,
        enabled: draft.enabled,
        is_default: draft.is_default,
        ...(draft.api_key ? { api_key: draft.api_key } : {}),
      };
      if (draft.id) return providersApi.update(draft.id, payload);
      return providersApi.create({ ...payload, api_key: draft.api_key });
    },
    onSuccess: (provider) => {
      setProviderError('');
      setProviderSuccess(editingProvider.id ? 'Provider updated.' : 'Provider created.');
      setEditingProvider(defaultProviderDraft());
      setExpertOpen(false);
      queryClient.setQueryData<ModelProvider[]>(['providers'], (current = []) => {
        const existingIndex = current.findIndex((item) => item.id === provider.id);
        if (existingIndex >= 0) {
          const next = [...current];
          next[existingIndex] = provider;
          return next;
        }
        return [provider, ...current];
      });
      queryClient.invalidateQueries({ queryKey: ['providers'] });
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
      queryClient.invalidateQueries({ queryKey: ['providers'] });
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
      queryClient.setQueryData<ModelProvider[]>(['providers'], (current = []) => {
        const existingIndex = current.findIndex((item) => item.id === provider.id);
        if (existingIndex >= 0) {
          const next = [...current];
          next[existingIndex] = provider;
          return next;
        }
        return [provider, ...current];
      });
      queryClient.invalidateQueries({ queryKey: ['providers'] });
    },
    onError: (error: unknown) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Provider model probe failed'));
    },
  });

  const loadProvider = (provider: ModelProvider) => {
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
    });
    setProviderError('');
    setProviderSuccess('');
  };

  const handleCopyKey = async () => {
    if (!latestApiKey) return;
    try {
      await navigator.clipboard.writeText(latestApiKey.api_key);
      setCopied(true);
      setCopyError('');
    } catch {
      setCopied(false);
      setCopyError('Clipboard access is unavailable in this context. Manually select the key text in the field above and copy it before closing.');
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
      <SectionToolbar title="Control Plane" description="Manage workspace API keys, provider profiles, and execution defaults in one operator-facing surface." />

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

      <div className="grid grid-cols-4 gap-4">
        <KeyMetric label="API keys" value={apiKeyMetricValue} hint={canManageApiKeys ? (hiddenApiKeyIds.length > 0 ? `${hiddenApiKeyIds.length} hidden from view` : 'Workspace-scoped programmatic access') : 'Requires can_manage_api_keys'} />
        <KeyMetric label="Providers" value={providerMetricValue} hint={canManageProviders ? `${providers.filter((provider) => provider.enabled).length} enabled` : 'Requires can_manage_providers'} />
        <KeyMetric label="Default provider" value={defaultProviderMetricValue} hint={canManageProviders ? (tenantDefaultProvider?.default_model || 'Backend system default may resolve') : 'Capability-gated'} />
        <KeyMetric label="System default" value={inferSystemModelLabel()} hint="Separate from the configured default provider. Current backend env-derived value is not exposed to this frontend API." />
      </div>

      <div className="grid grid-cols-[0.92fr_1.08fr] gap-6">
        <GlassPanel title="API keys" subtitle="Create, copy once, and revoke workspace-level API keys.">
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
            {apiKeySuccess && <InlineAlert tone="success" title="API key updated">{apiKeySuccess}</InlineAlert>}

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

        <div className="space-y-6">
          <GlassPanel
            title="Provider profiles"
            subtitle="Provider-aware model entry now lives here instead of a static global model list."
            actions={
              <div className="flex items-center gap-2">
                {editingProvider.id && (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => probeModelsMutation.mutate(editingProvider.id!)}
                    disabled={probeModelsMutation.isPending || !canManageProviders}
                  >
                    <Radar size={16} />
                    <span>{probeModelsMutation.isPending ? 'Probing…' : 'Probe models'}</span>
                  </button>
                )}
                <button type="button" className="btn-secondary" onClick={() => setExpertOpen(true)} disabled={!canManageProviders}>
                  <Wand2 size={16} />
                  <span>Expert headers</span>
                </button>
              </div>
            }
          >
            <form className="space-y-5" onSubmit={handleProviderSubmit}>
              {providerError && <InlineAlert tone="danger" title="Provider save failed">{providerError}</InlineAlert>}
              {providerSuccess && <InlineAlert tone="success" title="Provider saved">{providerSuccess}</InlineAlert>}
              {!canManageProviders && (
                <InlineAlert tone="warning" title="Provider management is read-only">
                  The current workspace membership does not grant `can_manage_providers`.
                </InlineAlert>
              )}

              <div className="grid grid-cols-2 gap-5">
                <Field label="Provider name" required>
                  <input value={editingProvider.name} onChange={(event) => setEditingProvider((draft) => ({ ...draft, name: event.target.value }))} className="field" disabled={!canManageProviders} required />
                </Field>
                <Field label="Provider type">
                  <select value={editingProvider.provider_type} onChange={(event) => setEditingProvider((draft) => ({ ...draft, provider_type: event.target.value }))} className="field" disabled={!canManageProviders}>
                    <option value="openai_compatible">openai_compatible</option>
                    <option value="dashscope">dashscope</option>
                    <option value="deepseek">deepseek</option>
                  </select>
                </Field>
                <div className="col-span-2">
                  <Field label="Base URL" required>
                    <input value={editingProvider.base_url} onChange={(event) => setEditingProvider((draft) => ({ ...draft, base_url: event.target.value }))} className="field" disabled={!canManageProviders} required />
                  </Field>
                </div>
                <Field label="Default model" required hint="This seeds provider-aware model inputs in Skills and Chat.">
                  <input value={editingProvider.default_model} onChange={(event) => setEditingProvider((draft) => ({ ...draft, default_model: event.target.value }))} className="field" disabled={!canManageProviders} required />
                </Field>
                <Field label="Supported models" hint="One per line or comma-separated. The default model is always included.">
                  <textarea
                    value={editingProvider.supported_models_text}
                    onChange={(event) => setEditingProvider((draft) => ({ ...draft, supported_models_text: event.target.value }))}
                    className="field min-h-[118px]"
                    disabled={!canManageProviders}
                    placeholder="deepseek-chat&#10;deepseek-reasoner"
                  />
                </Field>
                <Field label="API key" hint={editingProvider.id ? 'Leave empty to keep the existing secret.' : 'Stored securely after creation.'}>
                  <input
                    value={editingProvider.api_key}
                    onChange={(event) => setEditingProvider((draft) => ({ ...draft, api_key: event.target.value }))}
                    className="field"
                    disabled={!canManageProviders}
                    placeholder={editingProvider.id ? 'Leave blank to keep existing key' : 'Paste provider key'}
                  />
                </Field>
              </div>

              <div className="flex gap-6 rounded-[24px] border border-white/75 bg-white/58 p-4">
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={editingProvider.enabled} onChange={(event) => setEditingProvider((draft) => ({ ...draft, enabled: event.target.checked }))} disabled={!canManageProviders} />
                  <span>Enabled</span>
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={editingProvider.is_default} onChange={(event) => setEditingProvider((draft) => ({ ...draft, is_default: event.target.checked }))} disabled={!canManageProviders} />
                  <span>Default provider</span>
                </label>
              </div>

              <div className="flex items-center gap-3">
                <button type="submit" className="btn-primary" disabled={saveProviderMutation.isPending || !canManageProviders}>
                  <Save size={16} />
                  <span>{saveProviderMutation.isPending ? 'Saving…' : editingProvider.id ? 'Update provider' : 'Create provider'}</span>
                </button>
                {editingProvider.id && (
                  <button type="button" className="btn-ghost text-red-600" onClick={() => deleteProviderMutation.mutate(editingProvider.id!)} disabled={!canManageProviders}>
                    <Trash2 size={16} />
                    <span>Delete</span>
                  </button>
                )}
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    setEditingProvider(defaultProviderDraft());
                    setProviderError('');
                    setProviderSuccess('');
                  }}
                >
                  Reset
                </button>
              </div>
            </form>
          </GlassPanel>

          <GlassPanel title="System default execution" subtitle="Resolution order is visible even though backend env settings are not yet exposed via a dedicated API.">
            <div className="space-y-4">
              <div className="surface-soft p-4">
                <p className="metric-label">Resolution order</p>
                <ol className="mt-3 space-y-2 text-sm text-slate-700">
                  <li>1. Skill-bound provider</li>
                  <li>2. Request provider override</li>
                  <li>3. Configured default provider</li>
                  <li>4. Backend system default provider</li>
                </ol>
              </div>
              <div className="surface-soft p-4">
                <p className="metric-label">Configured default provider</p>
                <p className="mt-2 text-sm font-medium text-slate-900">{tenantDefaultProvider ? `${tenantDefaultProvider.name} · ${tenantDefaultProvider.default_model}` : 'Not configured'}</p>
                <p className="mt-1 text-sm text-slate-500">
                  {tenantDefaultProvider
                    ? 'If neither skill nor request binds a provider, this configured default is used first.'
                    : 'If no default provider is configured, the backend system default provider resolves the request.'}
                </p>
              </div>
              <div className="surface-soft p-4">
                <p className="metric-label">Backend system default</p>
                <p className="mt-2 text-sm font-medium text-slate-900">Current LLM base URL and inferred model are not exposed in the existing frontend API.</p>
                <p className="mt-1 text-sm text-slate-500">
                  The workbench still surfaces the fallback behavior so provider/model resolution is no longer invisible to operators.
                </p>
              </div>
            </div>
          </GlassPanel>
        </div>
      </div>

      <GlassPanel title="Configured providers" subtitle="Select a provider to edit its connection profile and default model.">
        {canManageProviders ? (
          <div className="grid grid-cols-2 gap-4">
            {providers.length > 0 ? (
              providers.map((provider) => (
                <button type="button" key={provider.id} onClick={() => loadProvider(provider)} className="list-row w-full text-left">
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <Server size={16} className="text-slate-400" />
                      <p className="font-medium text-slate-900">{provider.name}</p>
                    </div>
                    <p className="text-sm text-slate-500">
                      {provider.provider_type} · {provider.default_model}
                    </p>
                    <p className="text-sm text-slate-400">
                      {(provider.supported_models || [provider.default_model]).slice(0, 3).join(' · ')}
                      {(provider.supported_models || []).length > 3 ? ` +${provider.supported_models.length - 3}` : ''}
                    </p>
                  </div>
                  <div className="text-right">
                    <StatusBadge tone={provider.enabled ? 'success' : 'danger'}>{provider.enabled ? 'enabled' : 'disabled'}</StatusBadge>
                    {provider.is_default && <p className="mt-2 text-sm text-blue-600">default provider</p>}
                  </div>
                </button>
              ))
            ) : (
              <EmptyState
                title="No provider profiles yet"
                description="Create the first provider profile here to replace the old implicit tenant-wide configuration model."
              />
            )}
          </div>
        ) : (
          <EmptyState
            title="Provider profiles are hidden by capability"
            description="The current workspace membership cannot list or manage provider profiles in this workspace."
          />
        )}
      </GlassPanel>

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
          />
        </Field>
      </ExpertDrawer>
    </div>
  );
};
