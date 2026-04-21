import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus, Save, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { SkillLibraryCard } from '../components/skills/SkillLibraryCard';
import type { KnowledgeBaseSummary, SkillConsoleItem } from '../components/skills/types';
import { EmptyState, Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar } from '../components/ui/workbench';
import { providersApi } from '../features/providers/api';
import { skillsApi } from '../features/skills/api';
import { apiClient, resolveStoredWorkspace } from '../lib/api/client';
import { getErrorMessage, resolveProviderById, resolveWorkspaceDefaultProvider } from '../lib/utils';
import type { SkillMutationPayload } from '../features/skills/api';

type StoredUserContext = {
  workspace_id?: string | null;
};

const readCurrentWorkspaceId = () => {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem('user');
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredUserContext;
    return typeof parsed.workspace_id === 'string' && parsed.workspace_id ? parsed.workspace_id : null;
  } catch {
    return null;
  }
};

const listSkills = async (): Promise<SkillConsoleItem[]> => skillsApi.list() as Promise<SkillConsoleItem[]>;

const listKnowledgeBases = async (workspaceId: string): Promise<KnowledgeBaseSummary[]> => {
  const { data } = await apiClient.get<KnowledgeBaseSummary[]>(`/workspaces/${workspaceId}/knowledge-bases`);
  return data;
};

export const SkillsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [isCreateMode, setIsCreateMode] = useState(false);
  const [createError, setCreateError] = useState('');
  const [formState, setFormState] = useState({
    name: '',
    description: '',
  });

  const skillsQuery = useQuery({ queryKey: ['skills'], queryFn: listSkills });
  const providersQuery = useQuery({ queryKey: ['provider-catalog'], queryFn: providersApi.listCatalog });

  const workspaceId = useMemo(() => {
    return readCurrentWorkspaceId() || skillsQuery.data?.find((skill) => skill.workspace_id)?.workspace_id || null;
  }, [skillsQuery.data]);

  const knowledgeBasesQuery = useQuery({
    queryKey: ['knowledge-bases', workspaceId],
    queryFn: () => listKnowledgeBases(workspaceId!),
    enabled: Boolean(workspaceId),
  });

  const skills = useMemo(() => skillsQuery.data || [], [skillsQuery.data]);
  const providers = useMemo(() => providersQuery.data || [], [providersQuery.data]);
  const knowledgeBases = useMemo(() => knowledgeBasesQuery.data || [], [knowledgeBasesQuery.data]);
  const storedWorkspace = resolveStoredWorkspace();
  const workspaceDefaultProvider = useMemo(
    () => resolveWorkspaceDefaultProvider(storedWorkspace?.default_provider_id ?? null, providers),
    [providers, storedWorkspace?.default_provider_id],
  );
  const tenantDefaultProvider = useMemo(() => providers.find((provider) => provider.is_default) || null, [providers]);

  const knowledgeBasesById = useMemo(() => new Map(knowledgeBases.map((kb) => [kb.id, kb])), [knowledgeBases]);

  const primaryError =
    skillsQuery.error || knowledgeBasesQuery.error || providersQuery.error
      ? [skillsQuery.error, knowledgeBasesQuery.error, providersQuery.error]
          .filter(Boolean)
          .map((error) => getErrorMessage(error, 'Failed to load page data'))
          .join(' · ')
      : '';

  const activeSkillCount = skills.filter((skill) => skill.is_active !== false).length;
  const kbBackedSkillCount = skills.filter((skill) => Boolean(skill.knowledge_base_id)).length;
  const legacyShimSkillCount = skills.length - kbBackedSkillCount;

  const createMutation = useMutation({
    mutationFn: async (payload: SkillMutationPayload) => skillsApi.create(payload),
    onSuccess: (skill) => {
      setCreateError('');
      setIsCreateMode(false);
      setFormState({ name: '', description: '' });
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      navigate(`/skills/${skill.id}`);
    },
    onError: (error: unknown) => {
      setCreateError(getErrorMessage(error, 'Skill create failed'));
    },
  });

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const name = formState.name.trim();
    if (!name) {
      setCreateError('Skill name is required');
      return;
    }

    const defaultProvider = workspaceDefaultProvider || tenantDefaultProvider || null;
    const modelToSave = defaultProvider?.default_model;

    if (!defaultProvider || !modelToSave) {
      setCreateError('No workspace-available provider is configured. Set a workspace default provider or import/share a provider first.');
      return;
    }

    createMutation.mutate({
      name,
      description: formState.description.trim() ? formState.description.trim() : null,
      system_prompt: 'You are a helpful assistant. Please search my knowledge base to answer questions.',
      knowledge_base_id: null,
      provider_id: defaultProvider.id,
      model: modelToSave,
      document_ids: [],
      request_config: {},
      conversation_config: {},
      retrieval_config: {},
      generation_config: {},
    });
  };

  const handleCreateModeToggle = () => {
    if (isCreateMode) {
      setIsCreateMode(false);
      setFormState({ name: '', description: '' });
      setCreateError('');
    } else {
      setIsCreateMode(true);
    }
  };

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Skills Library"
        description="Select a Skill to enter its console, where you can modify its Knowledge Base, Model, System Prompt, and test it via chat."
        actions={
          <button type="button" className="btn-primary" onClick={handleCreateModeToggle} disabled={!workspaceId}>
            {isCreateMode ? <X size={16} /> : <Plus size={16} />}
            <span>{isCreateMode ? 'Cancel Creation' : 'Create Skill'}</span>
          </button>
        }
      />

      {primaryError && (
        <InlineAlert tone="danger" title="Skills page failed to load">
          {primaryError}
        </InlineAlert>
      )}

      {/* Top Metrics Cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KeyMetric label="Total Skills" value={skills.length} hint="Current workspace inventory" />
        <KeyMetric label="Active" value={activeSkillCount} hint="Available for use" />
        <KeyMetric label="Knowledge Base Backed" value={kbBackedSkillCount} hint="Modern architecture" />
        <KeyMetric label="Legacy Manual Selection" value={legacyShimSkillCount} hint="Deprecated architecture" />
      </div>

      {/* Inline Create Form overlay (only visible when isCreateMode is true) */}
      {isCreateMode && (
        <GlassPanel title="Create New Skill" subtitle="Give your skill a name to begin. New skills bind to a workspace-available provider immediately instead of relying on backend fallback guesses.">
          <form className="space-y-6" onSubmit={handleCreateSubmit}>
            {createError && <InlineAlert tone="danger" title="Creation Failed">{createError}</InlineAlert>}
            <InlineAlert tone="default" title="Initial provider binding">
              {workspaceDefaultProvider
                ? `This skill will start with workspace default provider ${workspaceDefaultProvider.name} and model ${workspaceDefaultProvider.default_model}.`
                : tenantDefaultProvider
                  ? `No workspace default is set, so creation will use tenant default provider ${tenantDefaultProvider.name}.`
                  : 'No workspace or tenant default provider is available yet.'}
            </InlineAlert>
            
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="space-y-4">
                <Field label="Skill Name" required>
                  <input
                    className="field"
                    autoFocus
                    value={formState.name}
                    onChange={(e) => setFormState({ ...formState, name: e.target.value })}
                    placeholder="e.g. Operations Expert"
                  />
                </Field>
              </div>
              <div className="space-y-4 flex flex-col justify-end">
                <div className="pt-4">
                  <button type="submit" className="btn-primary w-full" disabled={createMutation.isPending}>
                    {createMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                    <span>{createMutation.isPending ? 'Creating…' : 'Create & Configure'}</span>
                  </button>
                </div>
              </div>
            </div>
          </form>
        </GlassPanel>
      )}

      {/* Main Grid View */}
      {skillsQuery.isLoading ? (
        <div className="flex items-center justify-center py-32 opacity-70">
          <Loader2 size={32} className="animate-spin text-blue-500" />
          <span className="ml-4 text-slate-500 font-medium">Loading Skills…</span>
        </div>
      ) : skills.length === 0 && !isCreateMode ? (
        <EmptyState
          title="No Skills yet"
          description="Create a Skill to connect an AI personality structure with a Knowledge Base."
          action={
            <button type="button" className="btn-primary" onClick={handleCreateModeToggle}>
              <Plus size={16} />
              <span>Create Skill</span>
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-6">
          {skills.map((skill) => {
            const kb = skill.knowledge_base_id ? knowledgeBasesById.get(skill.knowledge_base_id) || null : null;
            const provider = resolveProviderById(skill.provider_id, providers);
            const providerLabel = provider?.name || workspaceDefaultProvider?.name || tenantDefaultProvider?.name || 'Legacy unbound skill';
            return (
              <SkillLibraryCard
                key={skill.id}
                skill={skill}
                knowledgeBase={kb}
                providerLabel={providerLabel}
                selected={false}
                onSelect={() => navigate(`/skills/${skill.id}`)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
};
