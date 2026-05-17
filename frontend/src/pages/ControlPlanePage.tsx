import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  Database,
  KeyRound,
  ListRestart,
  Plus,
  Radar,
  Save,
  Server,
  SlidersHorizontal,
  Trash2,
  WandSparkles,
} from 'lucide-react';
import { Link, Navigate, useLocation } from 'react-router-dom';

import { CopyOnceModal, EmptyState, Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge, SurfaceModal } from '../components/ui/workbench';
import { authApi } from '../features/auth/api';
import { providersApi } from '../features/providers/api';
import type { ProviderEndpointPayload } from '../features/providers/api';
import { workspacesApi } from '../features/workspaces/api';
import { resolveStoredWorkspace, resolveStoredWorkspaceMembership, updateStoredWorkspace } from '../lib/api/client';
import { copyTextToClipboard } from '../lib/clipboard';
import {
  cn,
  describeProviderAvailability,
  describeProviderOwnership,
  getErrorMessage,
  inferSystemModelLabel,
  resolveWorkspaceDefaultProvider,
} from '../lib/utils';
import type { ApiKey, ModelProvider, ModelProviderEndpoint, ProbeRuntimeResult, WorkspaceListItem } from '../types';

type ProviderCapability = 'chat' | 'embedding' | 'rerank';
type AuthMode = 'no_auth' | 'api_key';

type AbilityDefinition = {
  slug: 'llm' | 'embedding' | 'rerank';
  capability: ProviderCapability;
  title: string;
  cardTitle: string;
  description: string;
  modelLabel: string;
  adapter: ProviderEndpointPayload['adapter'];
  icon: React.ElementType;
  defaults: Record<string, unknown>;
};

type ProviderDraft = {
  id?: string;
  endpoint_id?: string;
  capability: ProviderCapability;
  provider_type: string;
  name: string;
  base_url: string;
  auth_mode: AuthMode;
  api_key: string;
  model: string;
  supported_models_text: string;
  enabled: boolean;
  is_default: boolean;
  scope: 'tenant' | 'workspace';
  share_mode: 'none' | 'all' | 'selected';
  shared_workspace_ids: string[];
  config: Record<string, unknown>;
};

type CachedApiKeySecret = {
  id: string;
  name: string;
  key_prefix: string;
  api_key: string;
  cached_at: string;
};

const ABILITIES: AbilityDefinition[] = [
  {
    slug: 'llm',
    capability: 'chat',
    title: 'LLM Provider Templates',
    cardTitle: 'LLM Providers',
    description: 'Manage chat and final-answer model templates for skills.',
    modelLabel: 'Default chat model',
    adapter: 'openai_chat',
    icon: Server,
    defaults: {
      temperature: 0.2,
      context_window_tokens: 131072,
      max_output_tokens: null,
      top_p: null,
      top_k: null,
    },
  },
  {
    slug: 'embedding',
    capability: 'embedding',
    title: 'Embedding Provider Templates',
    cardTitle: 'Embedding Providers',
    description: 'Manage vector-space templates and workspace embedding profile fields.',
    modelLabel: 'Embedding model',
    adapter: 'openai_embedding',
    icon: Database,
    defaults: {
      context_window_tokens: 16384,
      dimensions: 2048,
      embedding_profile: {
        canonical_model_key: '',
        dimensions: 2048,
        context_window_tokens: 16384,
        distance_metric: 'cosine',
        normalization: 'provider_default',
      },
    },
  },
  {
    slug: 'rerank',
    capability: 'rerank',
    title: 'Rerank Provider Templates',
    cardTitle: 'Rerank Providers',
    description: 'Manage rerank templates for retrieval ordering.',
    modelLabel: 'Rerank model',
    adapter: 'generic_rerank',
    icon: ListRestart,
    defaults: {
      top_n: 512,
    },
  },
];

const EMPTY_API_KEYS: ApiKey[] = [];
const EMPTY_PROVIDERS: ModelProvider[] = [];
const EMPTY_WORKSPACES: WorkspaceListItem[] = [];

const abilityBySlug = (slug: string | null) => ABILITIES.find((ability) => ability.slug === slug) || null;

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

const endpointForAbility = (provider: ModelProvider, ability: AbilityDefinition): ModelProviderEndpoint | null => {
  const endpoint = provider.endpoints.find((item) => item.capability === ability.capability);
  if (endpoint) return endpoint;
  if (ability.capability !== 'chat') return null;
  return {
    id: `${provider.id}:provider-default`,
    provider_id: provider.id,
    capability: 'chat',
    adapter: 'openai_chat',
    base_url: provider.base_url,
    model: provider.default_model,
    extra_headers: {},
    config: { ...ability.defaults },
    enabled: provider.enabled,
    is_default: true,
    health_status: 'unknown',
    last_probe_at: null,
    last_probe_latency_ms: null,
    last_probe_error: null,
    created_at: provider.created_at,
    updated_at: provider.updated_at,
  };
};

const configAuthMode = (config: Record<string, unknown> | undefined): AuthMode => (config?.auth_mode === 'no_auth' ? 'no_auth' : 'api_key');

const withAbilityDefaults = (ability: AbilityDefinition, config?: Record<string, unknown>) => {
  const merged = {
    ...ability.defaults,
    ...(config || {}),
  };
  if (ability.capability === 'embedding') {
    const profile = {
      ...((ability.defaults.embedding_profile as Record<string, unknown>) || {}),
      ...(((config || {}).embedding_profile as Record<string, unknown>) || {}),
    };
    merged.embedding_profile = profile;
  }
  return merged;
};

const defaultDraft = (ability: AbilityDefinition): ProviderDraft => ({
  capability: ability.capability,
  provider_type: 'openai_compatible',
  name: '',
  base_url: '',
  auth_mode: 'api_key',
  api_key: '',
  model: '',
  supported_models_text: '',
  enabled: true,
  is_default: false,
  scope: 'tenant',
  share_mode: 'all',
  shared_workspace_ids: [],
  config: withAbilityDefaults(ability),
});

const draftFromProvider = (provider: ModelProvider, ability: AbilityDefinition): ProviderDraft => {
  const endpoint = endpointForAbility(provider, ability);
  const config = withAbilityDefaults(ability, endpoint?.config);
  return {
    id: provider.id,
    endpoint_id: endpoint?.id.includes(':provider-default') ? undefined : endpoint?.id,
    capability: ability.capability,
    provider_type: provider.provider_type,
    name: provider.name,
    base_url: endpoint?.base_url || provider.base_url,
    auth_mode: configAuthMode(config),
    api_key: '',
    model: endpoint?.model || provider.default_model,
    supported_models_text: provider.supported_models.filter((model) => model !== provider.default_model).join('\n'),
    enabled: provider.enabled && (endpoint?.enabled ?? true),
    is_default: provider.is_default,
    scope: provider.scope === 'workspace' ? 'workspace' : 'tenant',
    share_mode: provider.scope === 'workspace' ? 'none' : provider.share_mode,
    shared_workspace_ids: provider.shared_workspace_ids || [],
    config,
  };
};

const endpointPayloadForDraft = (ability: AbilityDefinition, draft: ProviderDraft): ProviderEndpointPayload => {
  const payload: ProviderEndpointPayload = {
    ...(draft.endpoint_id ? { id: draft.endpoint_id } : {}),
    capability: ability.capability,
    adapter: ability.capability === 'rerank' ? ((draft.config.adapter as ProviderEndpointPayload['adapter']) || ability.adapter) : ability.adapter,
    base_url: draft.base_url.trim(),
    model: draft.model.trim(),
    enabled: draft.enabled,
    is_default: true,
    extra_headers: {},
    config: {
      ...draft.config,
      auth_mode: draft.auth_mode,
    },
  };
  if (draft.auth_mode === 'no_auth') payload.api_key = '';
  if (draft.auth_mode === 'api_key' && draft.api_key.trim()) payload.api_key = draft.api_key.trim();
  return payload;
};

const providerPayloadForDraft = (ability: AbilityDefinition, draft: ProviderDraft) => {
  const payload = {
    provider_type: draft.provider_type,
    name: draft.name.trim(),
    base_url: draft.base_url.trim(),
    default_model: draft.model.trim(),
    supported_models: parseSupportedModels(draft.model, draft.supported_models_text),
    extra_headers: {},
    enabled: draft.enabled,
    is_default: ability.capability === 'chat' && draft.scope === 'tenant' ? draft.is_default : false,
    scope: draft.scope,
    share_mode: draft.scope === 'workspace' ? 'none' : draft.share_mode,
    shared_workspace_ids: draft.scope === 'tenant' ? draft.shared_workspace_ids : [],
    endpoints: [endpointPayloadForDraft(ability, draft)],
  };
  if (draft.auth_mode === 'no_auth') return { ...payload, api_key: '' };
  if (draft.api_key.trim()) return { ...payload, api_key: draft.api_key.trim() };
  return payload;
};

const validateDraft = (draft: ProviderDraft) => {
  if (!draft.name.trim()) return 'Name is required.';
  if (!draft.base_url.trim()) return 'Base URL is required.';
  if (!draft.model.trim()) return 'Model is required.';
  if (draft.scope === 'workspace' && draft.is_default) return 'Workspace templates cannot be tenant default.';
  if (draft.scope === 'workspace' && draft.share_mode !== 'none') return 'Workspace templates cannot be shared.';
  if (draft.scope === 'tenant' && draft.share_mode === 'selected' && draft.shared_workspace_ids.length === 0) {
    return 'Selected workspace sharing requires at least one workspace.';
  }
  return null;
};

const formatHostPath = (url: string) => {
  try {
    const parsed = new URL(url);
    return `${parsed.host}${parsed.pathname === '/' ? '' : parsed.pathname}`;
  } catch {
    return url || '-';
  }
};

const lastTestLabel = (endpoint: ModelProviderEndpoint | null) => {
  if (!endpoint?.last_probe_at) return 'Never';
  return new Date(endpoint.last_probe_at).toLocaleString();
};

export const ControlPlanePage: React.FC = () => {
  const queryClient = useQueryClient();
  const location = useLocation();
  const view = location.pathname.replace(/\/+$/, '').split('/').pop() || '';
  const ability = abilityBySlug(view);
  const isApiKeysView = view === 'api-keys';
  const isHomeView = location.pathname.replace(/\/+$/, '') === '/providers';

  const [workspace, setWorkspace] = useState(resolveStoredWorkspace());
  const workspaceMembership = resolveStoredWorkspaceMembership();
  const canManageApiKeys = workspaceMembership?.permissions?.can_manage_api_keys === true;
  const canManageProviders = workspaceMembership?.permissions?.can_manage_providers === true;

  const [apiKeyName, setApiKeyName] = useState('');
  const [apiKeyError, setApiKeyError] = useState('');
  const [apiKeySuccess, setApiKeySuccess] = useState('');
  const [apiKeyInputAttention, setApiKeyInputAttention] = useState(false);
  const [latestApiKey, setLatestApiKey] = useState<CachedApiKeySecret | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const [hiddenApiKeyIds, setHiddenApiKeyIds] = useState<string[]>([]);
  const [cachedApiKeys, setCachedApiKeys] = useState<CachedApiKeySecret[]>(readCachedApiKeySecrets);

  const [editingDraft, setEditingDraft] = useState<ProviderDraft | null>(null);
  const [developerOpen, setDeveloperOpen] = useState(false);
  const [providerError, setProviderError] = useState('');
  const [providerSuccess, setProviderSuccess] = useState('');
  const [probeResults, setProbeResults] = useState<Record<string, ProbeRuntimeResult>>({});
  const [testingId, setTestingId] = useState<string | null>(null);

  const apiKeysQuery = useQuery({ queryKey: ['api-keys'], queryFn: authApi.listApiKeys, enabled: canManageApiKeys || isApiKeysView || isHomeView });
  const providersQuery = useQuery({ queryKey: ['providers', 'all'], queryFn: () => providersApi.list('all'), enabled: canManageProviders || Boolean(ability) || isHomeView });
  const providerCatalogQuery = useQuery({ queryKey: ['provider-catalog'], queryFn: providersApi.listCatalog, enabled: Boolean(ability) || isHomeView });
  const workspacesQuery = useQuery({ queryKey: ['workspaces'], queryFn: workspacesApi.list, enabled: canManageProviders });

  const apiKeys = apiKeysQuery.data ?? EMPTY_API_KEYS;
  const providers = providersQuery.data ?? EMPTY_PROVIDERS;
  const providerCatalog = providerCatalogQuery.data ?? EMPTY_PROVIDERS;
  const workspaces = workspacesQuery.data ?? EMPTY_WORKSPACES;
  const visibleApiKeys = apiKeys.filter((key) => !hiddenApiKeyIds.includes(key.id));
  const cachedApiKeysById = useMemo(() => new Map(cachedApiKeys.map((key) => [key.id, key])), [cachedApiKeys]);
  const shareableWorkspaces = useMemo(() => workspaces.filter((item) => item.membership_status === 'active'), [workspaces]);
  const importedSourceIds = useMemo(
    () => new Set(providers.map((provider) => provider.source_provider_id).filter((value): value is string => Boolean(value))),
    [providers]
  );
  const workspaceDefaultProvider = useMemo(
    () => resolveWorkspaceDefaultProvider(workspace?.default_provider_id ?? null, providerCatalog),
    [providerCatalog, workspace?.default_provider_id]
  );
  const tenantDefaultProvider = useMemo(() => providers.find((provider) => provider.is_default) || null, [providers]);

  const pageError = [apiKeysQuery.error, providersQuery.error, providerCatalogQuery.error, workspacesQuery.error]
    .map((error) => (error ? getErrorMessage(error, '') : ''))
    .find(Boolean);

  const createApiKeyMutation = useMutation({
    mutationFn: authApi.createApiKey,
    onSuccess: (created) => {
      const cached: CachedApiKeySecret = {
        id: created.id,
        name: created.name,
        key_prefix: created.key_prefix,
        api_key: created.api_key,
        cached_at: new Date().toISOString(),
      };
      const next = [cached, ...cachedApiKeys.filter((item) => item.id !== created.id)];
      setCachedApiKeys(next);
      writeCachedApiKeySecrets(next);
      setLatestApiKey(cached);
      setApiKeyName('');
      setApiKeyError('');
      setApiKeySuccess('API key created. Copy the raw key before closing the dialog.');
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
    },
    onError: (error) => {
      setApiKeySuccess('');
      setApiKeyError(getErrorMessage(error, 'API key create failed'));
    },
  });

  const revokeApiKeyMutation = useMutation({
    mutationFn: authApi.revokeApiKey,
    onSuccess: () => {
      setApiKeyError('');
      setApiKeySuccess('API key revoked.');
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
    },
    onError: (error) => {
      setApiKeySuccess('');
      setApiKeyError(getErrorMessage(error, 'API key revoke failed'));
    },
  });

  const saveProviderMutation = useMutation({
    mutationFn: async (draft: ProviderDraft) => {
      const matchedAbility = ABILITIES.find((item) => item.capability === draft.capability);
      if (!matchedAbility) throw new Error('Unknown capability');
      const payload = providerPayloadForDraft(matchedAbility, draft);
      if (draft.id) return providersApi.update(draft.id, payload);
      return providersApi.create({ ...payload, api_key: 'api_key' in payload ? payload.api_key || '' : '' });
    },
    onSuccess: (provider) => {
      setProviderError('');
      setProviderSuccess('Template saved.');
      setEditingDraft(null);
      queryClient.setQueryData<ModelProvider[]>(['providers', 'all'], (current = []) => {
        const exists = current.some((item) => item.id === provider.id);
        return exists ? current.map((item) => (item.id === provider.id ? provider : item)) : [provider, ...current];
      });
      queryClient.invalidateQueries({ queryKey: ['providers', 'all'] });
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
    },
    onError: (error) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Provider save failed'));
    },
  });

  const deleteProviderMutation = useMutation({
    mutationFn: (id: string) => providersApi.delete(id),
    onSuccess: () => {
      setProviderError('');
      setProviderSuccess('Template deleted.');
      setEditingDraft(null);
      queryClient.invalidateQueries({ queryKey: ['providers', 'all'] });
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
    },
    onError: (error) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Provider delete failed'));
    },
  });

  const importProviderMutation = useMutation({
    mutationFn: (providerId: string) => providersApi.importToWorkspace(providerId),
    onSuccess: () => {
      setProviderError('');
      setProviderSuccess('Shared template imported into this workspace.');
      queryClient.invalidateQueries({ queryKey: ['providers', 'all'] });
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
    },
    onError: (error) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Provider import failed'));
    },
  });

  const probeModelsMutation = useMutation({
    mutationFn: (id: string) => providersApi.probeModels(id),
    onSuccess: (provider) => {
      setProviderError('');
      setProviderSuccess(`Model list refreshed for ${provider.name}.`);
      queryClient.setQueryData<ModelProvider[]>(['providers', 'all'], (current = []) => current.map((item) => (item.id === provider.id ? provider : item)));
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
      if (ability) setEditingDraft(draftFromProvider(provider, ability));
    },
    onError: (error) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Model probe failed'));
    },
  });

  const workspaceDefaultMutation = useMutation({
    mutationFn: (default_provider_id: string | null) => workspacesApi.updateDefaultProvider({ default_provider_id }),
    onSuccess: (updatedWorkspace) => {
      updateStoredWorkspace(updatedWorkspace);
      setWorkspace(updatedWorkspace);
      setProviderError('');
      setProviderSuccess(updatedWorkspace.default_provider_id ? 'Workspace default provider updated.' : 'Workspace default provider cleared.');
      queryClient.invalidateQueries({ queryKey: ['provider-catalog'] });
    },
    onError: (error) => {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Workspace default provider update failed'));
    },
  });

  const nudgeApiKeyNameInput = () => {
    setApiKeyInputAttention(false);
    window.requestAnimationFrame(() => setApiKeyInputAttention(true));
  };

  const handleCopyKey = async () => {
    if (!latestApiKey) return;
    try {
      await copyTextToClipboard(latestApiKey.api_key);
      setCopied(true);
      setCopyError('');
    } catch (error) {
      setCopied(false);
      setCopyError(getErrorMessage(error, 'Clipboard access is unavailable.'));
    }
  };

  const openCachedApiKey = (keyId: string) => {
    const cachedSecret = cachedApiKeysById.get(keyId);
    if (!cachedSecret) return;
    setLatestApiKey(cachedSecret);
    setCopied(false);
    setCopyError('');
  };

  const hideApiKey = (keyId: string) => setHiddenApiKeyIds((current) => (current.includes(keyId) ? current : [...current, keyId]));

  const startCreate = (target: AbilityDefinition) => {
    setDeveloperOpen(false);
    setProviderError('');
    setProviderSuccess('');
    setEditingDraft(defaultDraft(target));
  };

  const startEdit = (provider: ModelProvider, target: AbilityDefinition) => {
    setDeveloperOpen(false);
    setProviderError('');
    setProviderSuccess('');
    setEditingDraft(draftFromProvider(provider, target));
  };

  const updateDraftConfig = (patch: Record<string, unknown>) => {
    setEditingDraft((draft) => (draft ? { ...draft, config: { ...draft.config, ...patch } } : draft));
  };

  const updateEmbeddingProfile = (patch: Record<string, unknown>) => {
    setEditingDraft((draft) => {
      if (!draft) return draft;
      const current = (draft.config.embedding_profile as Record<string, unknown>) || {};
      return { ...draft, config: { ...draft.config, embedding_profile: { ...current, ...patch } } };
    });
  };

  const toggleSharedWorkspace = (workspaceId: string) => {
    setEditingDraft((draft) => {
      if (!draft) return draft;
      const exists = draft.shared_workspace_ids.includes(workspaceId);
      return {
        ...draft,
        shared_workspace_ids: exists ? draft.shared_workspace_ids.filter((id) => id !== workspaceId) : [...draft.shared_workspace_ids, workspaceId],
      };
    });
  };

  const handleProviderSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editingDraft) return;
    if (!canManageProviders) {
      setProviderSuccess('');
      setProviderError('The current workspace membership cannot manage providers.');
      return;
    }
    const validationError = validateDraft(editingDraft);
    if (validationError) {
      setProviderSuccess('');
      setProviderError(validationError);
      return;
    }
    saveProviderMutation.mutate(editingDraft);
  };

  const handleTestSaved = async (provider: ModelProvider, target: AbilityDefinition) => {
    const endpoint = endpointForAbility(provider, target);
    setTestingId(endpoint?.id || provider.id);
    try {
      const result = endpoint?.id && !endpoint.id.includes(':provider-default')
        ? await providersApi.probeRuntime(provider.id, { endpoint_id: endpoint.id })
        : await providersApi.probeRuntime(provider.id, { capability: target.capability });
      const match = result.find((item) => item.capability === target.capability) || result[0];
      if (match) {
        setProbeResults((current) => ({ ...current, [endpoint?.id || provider.id]: match }));
        setProviderSuccess(`Probe completed: ${match.status}${match.latency_ms != null ? ` (${match.latency_ms}ms)` : ''}.`);
      }
      queryClient.invalidateQueries({ queryKey: ['providers', 'all'] });
    } catch (error) {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Runtime probe failed'));
    } finally {
      setTestingId(null);
    }
  };

  const handleTestDraft = async () => {
    if (!editingDraft || !ability) return;
    const validationError = validateDraft(editingDraft);
    if (validationError) {
      setProviderSuccess('');
      setProviderError(validationError);
      return;
    }
    setTestingId('draft');
    try {
      const result = await providersApi.probeRuntimeDraft({
        provider_type: editingDraft.provider_type as 'openai_compatible' | 'dashscope' | 'deepseek',
        base_url: editingDraft.base_url,
        api_key: editingDraft.auth_mode === 'api_key' ? editingDraft.api_key : '',
        endpoints: [endpointPayloadForDraft(ability, editingDraft)],
        capability: ability.capability,
      });
      const match = result[0];
      if (match) {
        setProviderSuccess(`Draft probe completed: ${match.status}${match.latency_ms != null ? ` (${match.latency_ms}ms)` : ''}.`);
        if (ability.capability === 'embedding' && match.dimensions != null && Number(editingDraft.config.dimensions) !== match.dimensions) {
          setProviderError(`Probe returned ${match.dimensions} dimensions, but this template is configured for ${editingDraft.config.dimensions}. Please update dimensions before saving.`);
        } else {
          setProviderError('');
        }
      }
    } catch (error) {
      setProviderSuccess('');
      setProviderError(getErrorMessage(error, 'Draft runtime probe failed'));
    } finally {
      setTestingId(null);
    }
  };

  if (!isHomeView && !isApiKeysView && !ability && view !== 'docs') {
    return <Navigate to="/providers" replace />;
  }

  const renderAlerts = () => (
    <>
      {pageError && <InlineAlert tone="danger" title="Provider Center data did not load cleanly">{pageError}</InlineAlert>}
      {providerError && <InlineAlert tone="danger" title="Provider action failed">{providerError}</InlineAlert>}
      {providerSuccess && <InlineAlert tone="success" title="Provider updated">{providerSuccess}</InlineAlert>}
      {(!canManageApiKeys || !canManageProviders) && (
        <InlineAlert tone="warning" title="Actions are capability-gated">
          API key management requires `can_manage_api_keys`; provider templates require `can_manage_providers`.
        </InlineAlert>
      )}
    </>
  );

  const renderHome = () => {
    const cards = [
      {
        to: '/providers/api-keys',
        title: 'API Keys',
        description: 'Workspace programmatic access keys.',
        count: canManageApiKeys ? visibleApiKeys.length : 'Hidden',
        icon: KeyRound,
        hint: 'Separate from model provider credentials',
      },
      ...ABILITIES.map((item) => ({
        to: `/providers/${item.slug}`,
        title: item.cardTitle,
        description: item.description,
        count: providers.filter((provider) => endpointForAbility(provider, item)).length,
        icon: item.icon,
        hint: item.capability === 'chat' ? workspaceDefaultProvider?.name || tenantDefaultProvider?.name || 'No default selected' : 'Capability templates',
      })),
    ];

    return (
      <div className="space-y-8">
        <SectionToolbar
          title="Provider Center"
          description="Configure model capabilities as reusable templates, then let workspace and SkillChat consumers bind them explicitly."
          actions={<Link to="/providers/docs" className="btn-secondary">API docs</Link>}
        />
        {renderAlerts()}
        <div className="grid gap-4 lg:grid-cols-4">
          {cards.map((card) => {
            const Icon = card.icon;
            return (
              <Link key={card.to} to={card.to} className="group rounded-[8px] border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md">
                <div className="flex items-start justify-between gap-4">
                  <div className="rounded-[8px] border border-slate-200 bg-slate-50 p-2 text-slate-700">
                    <Icon size={20} />
                  </div>
                  <span className="text-2xl font-semibold text-slate-900">{card.count}</span>
                </div>
                <div className="mt-5 space-y-2">
                  <p className="text-base font-semibold text-slate-950">{card.title}</p>
                  <p className="min-h-[40px] text-sm leading-5 text-slate-600">{card.description}</p>
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">{card.hint}</p>
                </div>
              </Link>
            );
          })}
        </div>
        <div className="grid gap-4 lg:grid-cols-4">
          <KeyMetric label="Workspace default LLM" value={workspaceDefaultProvider?.name || 'None'} hint={workspaceDefaultProvider?.default_model || 'Falls back to tenant or backend default'} />
          <KeyMetric label="Tenant default LLM" value={tenantDefaultProvider?.name || 'None'} hint={tenantDefaultProvider?.default_model || 'Not configured'} />
          <KeyMetric label="System fallback" value={inferSystemModelLabel()} hint="Backend env value is not fully exposed here" />
          <KeyMetric label="Bindable templates" value={providerCatalog.filter((provider) => provider.bindable_in_current_workspace).length} hint="Visible to this workspace" />
        </div>
      </div>
    );
  };

  const renderApiKeys = () => (
    <div className="space-y-6">
      <SectionToolbar
        title="API Key Configuration"
        description="Create and revoke workspace API keys without mixing them with model provider credentials."
        actions={<Link to="/providers" className="btn-secondary"><ArrowLeft size={16} />Back</Link>}
      />
      {renderAlerts()}
      <GlassPanel
        title="Workspace API keys"
        subtitle="Raw keys are shown once by the backend. This browser keeps local copies only for keys created here."
        actions={<Link to="/providers/docs" className="btn-secondary">View API docs</Link>}
      >
        <div className="space-y-5">
          <form
            className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]"
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
              className={cn('field', apiKeyInputAttention && 'field-attention')}
              placeholder="automation-bot"
            />
            <button type="submit" className="btn-primary justify-center" disabled={!canManageApiKeys || createApiKeyMutation.isPending}>
              <Plus size={16} />
              <span>Create key</span>
            </button>
          </form>

          {apiKeyError && <InlineAlert tone="danger" title="API key action failed">{apiKeyError}</InlineAlert>}
          {apiKeySuccess && <InlineAlert tone="success" title="API key updated">{apiKeySuccess}</InlineAlert>}
          {!canManageApiKeys && <InlineAlert tone="warning" title="Read-only">The current workspace membership cannot manage API keys.</InlineAlert>}

          <div className="overflow-hidden rounded-[8px] border border-slate-200 bg-white">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-[0.12em] text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-semibold">Name</th>
                  <th className="px-4 py-3 font-semibold">Prefix</th>
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 font-semibold">Created</th>
                  <th className="px-4 py-3 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visibleApiKeys.map((key) => (
                  <tr key={key.id} className="align-middle">
                    <td className="px-4 py-3 font-medium text-slate-900">{key.name}</td>
                    <td className="px-4 py-3 text-slate-600">{key.key_prefix}</td>
                    <td className="px-4 py-3"><StatusBadge tone={key.status === 'active' ? 'success' : 'danger'}>{key.status}</StatusBadge></td>
                    <td className="px-4 py-3 text-slate-500">{new Date(key.created_at).toLocaleString()}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        {cachedApiKeysById.has(key.id) && (
                          <button type="button" className="btn-secondary" onClick={() => openCachedApiKey(key.id)}>Copy</button>
                        )}
                        {key.status !== 'active' && (
                          <button type="button" className="btn-ghost text-slate-500" onClick={() => hideApiKey(key.id)}>Hide</button>
                        )}
                        <button type="button" className="btn-ghost text-red-600" onClick={() => revokeApiKeyMutation.mutate(key.id)} disabled={!canManageApiKeys || revokeApiKeyMutation.isPending}>
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {visibleApiKeys.length === 0 && (
              <EmptyState
                title={canManageApiKeys ? 'No workspace API keys yet' : 'API keys are hidden by capability'}
                description={canManageApiKeys ? 'Create a key to enable service integrations.' : 'This session cannot list workspace API keys.'}
              />
            )}
          </div>
        </div>
      </GlassPanel>
    </div>
  );

  const renderAbility = (target: AbilityDefinition) => {
    const rows = providers
      .map((provider) => ({ provider, endpoint: endpointForAbility(provider, target) }))
      .filter((row) => row.endpoint);
    const Icon = target.icon;

    return (
      <div className="space-y-6">
        <SectionToolbar
          title={target.title}
          description={target.description}
          actions={(
            <>
              <Link to="/providers" className="btn-secondary"><ArrowLeft size={16} />Back</Link>
              <button type="button" className="btn-primary" onClick={() => startCreate(target)} disabled={!canManageProviders}>
                <Plus size={16} />
                <span>Create template</span>
              </button>
            </>
          )}
        />
        {renderAlerts()}

        {target.capability === 'chat' && (
          <GlassPanel title="Workspace LLM default" subtitle="This is still the current runtime default chain; capability pages are management views, not multi-provider runtime merging.">
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto]">
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
                      {provider.name} ({provider.scope}) · {provider.default_model}
                    </option>
                  ))}
              </select>
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <CheckCircle2 size={16} className="text-emerald-600" />
                <span>{workspaceDefaultProvider ? `${workspaceDefaultProvider.name} is active` : 'Tenant/system fallback will resolve'}</span>
              </div>
            </div>
          </GlassPanel>
        )}

        <GlassPanel
          title={`${target.cardTitle} table`}
          subtitle="Each row is one provider-backed capability template. Edit details in the modal so the table remains scannable."
        >
          <div className="overflow-x-auto rounded-[8px] border border-slate-200 bg-white">
            <table className="w-full min-w-[1080px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-[0.12em] text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-semibold">Name</th>
                  <th className="px-4 py-3 font-semibold">Scope</th>
                  <th className="px-4 py-3 font-semibold">Base URL</th>
                  <th className="px-4 py-3 font-semibold">Model</th>
                  <th className="px-4 py-3 font-semibold">Auth</th>
                  <th className="px-4 py-3 font-semibold">Defaults</th>
                  <th className="px-4 py-3 font-semibold">Health</th>
                  <th className="px-4 py-3 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map(({ provider, endpoint }) => {
                  const probe = probeResults[endpoint!.id];
                  const config = withAbilityDefaults(target, endpoint!.config);
                  const health = probe?.status || endpoint!.health_status || 'unknown';
                  const canImport = provider.scope === 'tenant' && provider.available_in_current_workspace && !importedSourceIds.has(provider.id);
                  return (
                    <tr key={`${provider.id}-${endpoint!.id}`} className="align-top">
                      <td className="px-4 py-4">
                        <div className="flex items-start gap-3">
                          <div className="mt-0.5 rounded-[8px] border border-slate-200 bg-slate-50 p-2 text-slate-600">
                            <Icon size={16} />
                          </div>
                          <div>
                            <p className="font-medium text-slate-950">{provider.name}</p>
                            <p className="mt-1 text-xs text-slate-500">{provider.provider_type}</p>
                            {provider.managed_by_system && <p className="mt-1 text-xs text-slate-400">system managed</p>}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <p className="text-slate-700">{describeProviderOwnership(provider)}</p>
                        <p className="mt-1 text-xs text-slate-500">{describeProviderAvailability(provider)}</p>
                      </td>
                      <td className="px-4 py-4 text-slate-600" title={endpoint!.base_url}>{formatHostPath(endpoint!.base_url)}</td>
                      <td className="px-4 py-4">
                        <p className="font-medium text-slate-900">{endpoint!.model}</p>
                        {provider.supported_models.length > 1 && <p className="mt-1 text-xs text-slate-500">{provider.supported_models.length} probed models</p>}
                      </td>
                      <td className="px-4 py-4">
                        <StatusBadge tone={configAuthMode(config) === 'no_auth' ? 'default' : 'accent'}>
                          {configAuthMode(config) === 'no_auth' ? 'No auth' : 'API key'}
                        </StatusBadge>
                      </td>
                      <td className="px-4 py-4 text-slate-600">
                        {target.capability === 'chat' && <span>temp {String(config.temperature)} · ctx {String(config.context_window_tokens)}</span>}
                        {target.capability === 'embedding' && <span>{String(config.dimensions)} dims · ctx {String(config.context_window_tokens)}</span>}
                        {target.capability === 'rerank' && <span>top_n {String(config.top_n)}</span>}
                      </td>
                      <td className="px-4 py-4">
                        <StatusBadge tone={health === 'healthy' ? 'success' : health === 'unhealthy' ? 'danger' : 'default'}>{health}</StatusBadge>
                        <p className="mt-1 text-xs text-slate-500">{probe?.latency_ms ?? endpoint!.last_probe_latency_ms ?? '-'}ms · {lastTestLabel(endpoint)}</p>
                        {(probe?.dimensions || probe?.sample_count) && (
                          <p className="mt-1 text-xs text-slate-500">{probe.dimensions ? `${probe.dimensions} dims` : `${probe.sample_count} samples`}</p>
                        )}
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex justify-end gap-2">
                          <button type="button" className="btn-secondary" onClick={() => handleTestSaved(provider, target)} disabled={!canManageProviders || testingId === endpoint!.id}>
                            <Radar size={14} />
                            <span>{testingId === endpoint!.id ? 'Testing' : 'Test'}</span>
                          </button>
                          {canImport && (
                            <button type="button" className="btn-secondary" onClick={() => importProviderMutation.mutate(provider.id)} disabled={importProviderMutation.isPending}>
                              Import
                            </button>
                          )}
                          <button type="button" className="btn-secondary" onClick={() => startEdit(provider, target)} disabled={!canManageProviders}>
                            Edit
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {rows.length === 0 && (
              <EmptyState
                title={`No ${target.cardTitle.toLowerCase()} yet`}
                description="Create a template to make this model capability available to workspace consumers."
                action={<button type="button" className="btn-primary" onClick={() => startCreate(target)} disabled={!canManageProviders}>Create template</button>}
              />
            )}
          </div>
        </GlassPanel>

        {renderProviderModal(target)}
      </div>
    );
  };

  const renderDeveloperFields = (target: AbilityDefinition, draft: ProviderDraft) => {
    if (!developerOpen) return null;
    const embeddingProfile = (draft.config.embedding_profile as Record<string, unknown>) || {};
    return (
      <div className="space-y-4 rounded-[8px] border border-slate-200 bg-slate-50 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <SlidersHorizontal size={16} />
          <span>Developer options</span>
        </div>
        {target.capability === 'chat' && (
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Temperature">
              <input className="field" type="number" step="0.1" value={String(draft.config.temperature ?? '')} onChange={(event) => updateDraftConfig({ temperature: Number(event.target.value) })} />
            </Field>
            <Field label="Context window tokens" hint="Model total context window. This is not OpenAI max_tokens.">
              <input className="field" type="number" min="1" value={String(draft.config.context_window_tokens ?? '')} onChange={(event) => updateDraftConfig({ context_window_tokens: Number(event.target.value) })} />
            </Field>
            <Field label="Max output tokens">
              <input className="field" type="number" min="1" value={String(draft.config.max_output_tokens ?? '')} onChange={(event) => updateDraftConfig({ max_output_tokens: event.target.value ? Number(event.target.value) : null })} />
            </Field>
            <Field label="Top P">
              <input className="field" type="number" step="0.01" value={String(draft.config.top_p ?? '')} onChange={(event) => updateDraftConfig({ top_p: event.target.value ? Number(event.target.value) : null })} />
            </Field>
            <Field label="Top K">
              <input className="field" type="number" min="1" value={String(draft.config.top_k ?? '')} onChange={(event) => updateDraftConfig({ top_k: event.target.value ? Number(event.target.value) : null })} />
            </Field>
          </div>
        )}
        {target.capability === 'embedding' && (
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Context window tokens">
              <input className="field" type="number" min="1" value={String(draft.config.context_window_tokens ?? '')} onChange={(event) => {
                const value = Number(event.target.value);
                updateDraftConfig({ context_window_tokens: value });
                updateEmbeddingProfile({ context_window_tokens: value });
              }} />
            </Field>
            <Field label="Dimensions" hint="4096 requires confirming Elasticsearch mapping/version support. Probe mismatch blocks save.">
              <input className="field" type="number" min="1" value={String(draft.config.dimensions ?? '')} onChange={(event) => {
                const value = Number(event.target.value);
                updateDraftConfig({ dimensions: value });
                updateEmbeddingProfile({ dimensions: value });
              }} />
            </Field>
            <Field label="Canonical model key">
              <input className="field" value={String(embeddingProfile.canonical_model_key || draft.model)} onChange={(event) => updateEmbeddingProfile({ canonical_model_key: event.target.value })} />
            </Field>
            <Field label="Distance metric">
              <select className="field" value={String(embeddingProfile.distance_metric || 'cosine')} onChange={(event) => updateEmbeddingProfile({ distance_metric: event.target.value })}>
                <option value="cosine">cosine</option>
                <option value="dot_product">dot_product</option>
                <option value="l2">l2</option>
              </select>
            </Field>
            <Field label="Normalization">
              <select className="field" value={String(embeddingProfile.normalization || 'provider_default')} onChange={(event) => updateEmbeddingProfile({ normalization: event.target.value })}>
                <option value="provider_default">provider_default</option>
                <option value="normalized">normalized</option>
                <option value="raw">raw</option>
              </select>
            </Field>
          </div>
        )}
        {target.capability === 'rerank' && (
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Top N">
              <input className="field" type="number" min="1" value={String(draft.config.top_n ?? '')} onChange={(event) => updateDraftConfig({ top_n: Number(event.target.value) })} />
            </Field>
            <Field label="Adapter">
              <select className="field" value={String(draft.config.adapter || target.adapter)} onChange={(event) => updateDraftConfig({ adapter: event.target.value })}>
                <option value="generic_rerank">generic_rerank</option>
                <option value="dashscope_rerank">dashscope_rerank</option>
              </select>
            </Field>
          </div>
        )}
        <Field label="Provider config JSON" hint="Stored on endpoint config_json for later SkillChat/runtime agents.">
          <textarea className="field min-h-[120px] font-mono text-xs" readOnly value={JSON.stringify(draft.config, null, 2)} />
        </Field>
      </div>
    );
  };

  const renderProviderModal = (target: AbilityDefinition) => {
    const draft = editingDraft?.capability === target.capability ? editingDraft : null;
    const selectedProvider = draft?.id ? providers.find((provider) => provider.id === draft.id) || null : null;
    const modelOptions = selectedProvider?.supported_models || parseSupportedModels(draft?.model || '', draft?.supported_models_text || '');
    const readOnly = selectedProvider?.managed_by_system === true;
    return (
      <SurfaceModal
        open={Boolean(draft)}
        title={draft?.id ? `Edit ${target.cardTitle.slice(0, -1)}` : `Create ${target.cardTitle.slice(0, -1)}`}
        subtitle="Provider-owned connection fields stay here; SkillChat will later copy and override its own runtime parameters."
        onClose={() => setEditingDraft(null)}
        className="max-w-4xl"
        bodyClassName="max-h-[78vh]"
        actions={(
          <button type="button" className="btn-secondary" onClick={() => setDeveloperOpen((value) => !value)}>
            <WandSparkles size={16} />
            <span>{developerOpen ? 'Hide developer' : 'Developer options'}</span>
          </button>
        )}
      >
        {draft && (
          <form className="space-y-5" onSubmit={handleProviderSubmit}>
            {readOnly && <InlineAlert tone="default" title="System-managed template">This provider is synced from backend environment settings and cannot be edited here.</InlineAlert>}
            {providerError && <InlineAlert tone="danger" title="Provider action failed">{providerError}</InlineAlert>}
            {providerSuccess && <InlineAlert tone="success" title="Provider updated">{providerSuccess}</InlineAlert>}
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Name" required>
                <input className="field" value={draft.name} onChange={(event) => setEditingDraft({ ...draft, name: event.target.value })} disabled={readOnly} />
              </Field>
              <Field label="Provider type">
                <select className="field" value={draft.provider_type} onChange={(event) => setEditingDraft({ ...draft, provider_type: event.target.value })} disabled={readOnly}>
                  <option value="openai_compatible">openai_compatible</option>
                  <option value="dashscope">dashscope</option>
                  <option value="deepseek">deepseek</option>
                </select>
              </Field>
              <Field label="Scope" hint="Shared templates are tenant-owned. Workspace templates belong only to the current workspace.">
                <select
                  className="field"
                  value={draft.scope}
                  onChange={(event) =>
                    setEditingDraft({
                      ...draft,
                      scope: event.target.value as 'tenant' | 'workspace',
                      share_mode: event.target.value === 'workspace' ? 'none' : draft.share_mode === 'none' ? 'all' : draft.share_mode,
                      is_default: event.target.value === 'workspace' ? false : draft.is_default,
                    })
                  }
                  disabled={readOnly || Boolean(draft.id)}
                >
                  <option value="tenant">Shared tenant template</option>
                  <option value="workspace">Workspace template</option>
                </select>
              </Field>
              <Field label="Auth mode" hint="No auth sends no Authorization header. API key can be saved empty for not-yet-configured templates.">
                <select className="field" value={draft.auth_mode} onChange={(event) => setEditingDraft({ ...draft, auth_mode: event.target.value as AuthMode })} disabled={readOnly}>
                  <option value="api_key">API key</option>
                  <option value="no_auth">No auth</option>
                </select>
              </Field>
              <div className="md:col-span-2">
                <Field label="Base URL" required>
                  <input className="field" value={draft.base_url} onChange={(event) => setEditingDraft({ ...draft, base_url: event.target.value })} disabled={readOnly} />
                </Field>
              </div>
              <Field label={target.modelLabel} required hint="Probe can populate the list; otherwise manual input is accepted. SkillChat will choose from this template list later.">
                <>
                  <input className="field" list={`models-${target.slug}`} value={draft.model} onChange={(event) => setEditingDraft({ ...draft, model: event.target.value })} disabled={readOnly} />
                  <datalist id={`models-${target.slug}`}>
                    {modelOptions.map((model) => <option key={model} value={model} />)}
                  </datalist>
                </>
              </Field>
              <Field label="Supported models" hint="One per line or comma-separated. The selected model is always included.">
                <textarea className="field min-h-[96px]" value={draft.supported_models_text} onChange={(event) => setEditingDraft({ ...draft, supported_models_text: event.target.value })} disabled={readOnly} />
              </Field>
              {draft.auth_mode === 'api_key' && (
                <Field label="API key" hint={draft.id ? 'Leave empty to keep an existing key. Enter a new key to rotate.' : 'May be empty while the template is incomplete.'}>
                  <input className="field" value={draft.api_key} onChange={(event) => setEditingDraft({ ...draft, api_key: event.target.value })} disabled={readOnly} placeholder={draft.id ? 'Keep saved key' : 'Paste API key or leave empty'} />
                </Field>
              )}
              {draft.scope === 'tenant' && (
                <>
                  <Field label="Workspace availability">
                    <select className="field" value={draft.share_mode} onChange={(event) => setEditingDraft({ ...draft, share_mode: event.target.value as ProviderDraft['share_mode'] })} disabled={readOnly}>
                      <option value="all">All workspaces</option>
                      <option value="selected">Selected workspaces</option>
                      <option value="none">Not shared</option>
                    </select>
                  </Field>
                  <Field label="Selected workspaces">
                    <div className="rounded-[8px] border border-slate-200 bg-white p-3">
                      {draft.share_mode !== 'selected' ? (
                        <p className="text-sm text-slate-500">Switch availability to selected workspaces to choose a list.</p>
                      ) : shareableWorkspaces.length === 0 ? (
                        <p className="text-sm text-slate-500">No active workspaces are visible to this session.</p>
                      ) : (
                        <div className="grid gap-2 md:grid-cols-2">
                          {shareableWorkspaces.map((item) => (
                            <label key={item.id} className="flex items-start gap-2 text-sm text-slate-700">
                              <input type="checkbox" checked={draft.shared_workspace_ids.includes(item.id)} onChange={() => toggleSharedWorkspace(item.id)} disabled={readOnly} />
                              <span>
                                <span className="font-medium text-slate-900">{item.name}</span>
                                <span className="block text-xs text-slate-500">{item.slug}{item.is_current ? ' · current' : ''}</span>
                              </span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                  </Field>
                </>
              )}
            </div>

            <div className="flex flex-wrap gap-6 rounded-[8px] border border-slate-200 bg-white p-3">
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={draft.enabled} onChange={(event) => setEditingDraft({ ...draft, enabled: event.target.checked })} disabled={readOnly} />
                <span>Enabled</span>
              </label>
              {target.capability === 'chat' && draft.scope === 'tenant' && (
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={draft.is_default} onChange={(event) => setEditingDraft({ ...draft, is_default: event.target.checked })} disabled={readOnly} />
                  <span>Tenant default LLM</span>
                </label>
              )}
            </div>

            {renderDeveloperFields(target, draft)}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                {draft.id && (
                  <button type="button" className="btn-secondary" onClick={() => probeModelsMutation.mutate(draft.id!)} disabled={readOnly || probeModelsMutation.isPending}>
                    <Activity size={16} />
                    <span>{probeModelsMutation.isPending ? 'Probing models' : 'Probe model list'}</span>
                  </button>
                )}
                <button type="button" className="btn-secondary" onClick={handleTestDraft} disabled={readOnly || testingId === 'draft'}>
                  <Radar size={16} />
                  <span>{testingId === 'draft' ? 'Testing' : 'Test connection'}</span>
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                {draft.id && !readOnly && (
                  <button type="button" className="btn-ghost text-red-600" onClick={() => deleteProviderMutation.mutate(draft.id!)} disabled={deleteProviderMutation.isPending}>
                    <Trash2 size={16} />
                    <span>Delete</span>
                  </button>
                )}
                <button type="submit" className="btn-primary" disabled={readOnly || saveProviderMutation.isPending || !canManageProviders}>
                  <Save size={16} />
                  <span>{saveProviderMutation.isPending ? 'Saving' : 'Save template'}</span>
                </button>
              </div>
            </div>
          </form>
        )}
      </SurfaceModal>
    );
  };

  return (
    <div className="space-y-8">
      {isHomeView && renderHome()}
      {isApiKeysView && renderApiKeys()}
      {ability && renderAbility(ability)}

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
    </div>
  );
};
