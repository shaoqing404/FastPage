import React, { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Play, Sparkles } from 'lucide-react';

import { complianceApi } from '../../features/compliance';
import type { ComplianceCheck, ComplianceRun, KnowledgeBase, ModelProvider } from '../../types';
import { getErrorMessage, resolveProviderName } from '../../lib/utils';
import { EmptyState, Field, GlassPanel, InlineAlert, StatusBadge } from '../ui/workbench';

type LaunchMode = 'adhoc' | 'check';

type ComplianceLaunchPanelProps = {
  knowledgeBases: KnowledgeBase[];
  checks: ComplianceCheck[];
  providers: ModelProvider[];
  onRunCreated: (run: ComplianceRun) => void;
};

const DEFAULT_FACTS_JSON = '{\n  \n}';

const parseFactsInput = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed) as unknown;
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('Facts must be a JSON object');
  }
  return parsed as Record<string, unknown>;
};

export const ComplianceLaunchPanel: React.FC<ComplianceLaunchPanelProps> = ({ knowledgeBases, checks, providers, onRunCreated }) => {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<LaunchMode>('adhoc');

  const [adhocKnowledgeBaseId, setAdhocKnowledgeBaseId] = useState('');
  const [adhocQuestion, setAdhocQuestion] = useState('');
  const [adhocFacts, setAdhocFacts] = useState(DEFAULT_FACTS_JSON);
  const [adhocInstructions, setAdhocInstructions] = useState('');
  const [adhocProviderId, setAdhocProviderId] = useState('');
  const [adhocModel, setAdhocModel] = useState('');
  const [adhocError, setAdhocError] = useState('');

  const [selectedCheckId, setSelectedCheckId] = useState('');
  const [checkQuestion, setCheckQuestion] = useState('');
  const [checkFacts, setCheckFacts] = useState(DEFAULT_FACTS_JSON);
  const [checkInstructions, setCheckInstructions] = useState('');
  const [checkProviderId, setCheckProviderId] = useState('');
  const [checkModel, setCheckModel] = useState('');
  const [checkError, setCheckError] = useState('');

  const effectiveAdhocKnowledgeBaseId = adhocKnowledgeBaseId || knowledgeBases[0]?.id || '';
  const effectiveSelectedCheckId = selectedCheckId || checks[0]?.id || '';

  const selectedCheck = useMemo(() => checks.find((check) => check.id === effectiveSelectedCheckId) || null, [checks, effectiveSelectedCheckId]);
  const selectedCheckKnowledgeBase = useMemo(
    () => knowledgeBases.find((knowledgeBase) => knowledgeBase.id === selectedCheck?.target.knowledge_base_id) || null,
    [knowledgeBases, selectedCheck],
  );

  const selectedAdhocProvider = providers.find((provider) => provider.id === adhocProviderId) || null;
  const selectedCheckProvider = providers.find((provider) => provider.id === checkProviderId) || null;

  const commonSuccess = (run: ComplianceRun) => {
    queryClient.invalidateQueries({ queryKey: ['compliance-runs'] });
    onRunCreated(run);
  };

  const adhocMutation = useMutation({
    mutationFn: async () => {
      const question = adhocQuestion.trim();
      if (!question) throw new Error('Question is required');
      if (!effectiveAdhocKnowledgeBaseId) throw new Error('Knowledge Base is required');

      return complianceApi.runs.createAdHoc({
        execution_mode: 'async',
        input: {
          question,
          facts: parseFactsInput(adhocFacts),
        },
        target: {
          mode: 'knowledge_base',
          knowledge_base_id: effectiveAdhocKnowledgeBaseId,
        },
        ...(adhocInstructions.trim() ? { instructions: adhocInstructions.trim() } : {}),
        ...(adhocProviderId ? { provider_id: adhocProviderId } : {}),
        ...(adhocModel.trim() ? { model: adhocModel.trim() } : {}),
      });
    },
    onMutate: () => setAdhocError(''),
    onSuccess: commonSuccess,
    onError: (error: unknown) => setAdhocError(getErrorMessage(error, 'Ad hoc compliance run failed')),
  });

  const fromCheckMutation = useMutation({
    mutationFn: async () => {
      const question = checkQuestion.trim();
      if (!effectiveSelectedCheckId) throw new Error('Saved check is required');
      if (!question) throw new Error('Question is required');

      return complianceApi.runs.fromCheck(effectiveSelectedCheckId, {
        execution_mode: 'async',
        input: {
          question,
          facts: parseFactsInput(checkFacts),
        },
        ...(checkInstructions.trim() ? { instructions: checkInstructions.trim() } : {}),
        ...(checkProviderId ? { provider_id: checkProviderId } : {}),
        ...(checkModel.trim() ? { model: checkModel.trim() } : {}),
      });
    },
    onMutate: () => setCheckError(''),
    onSuccess: commonSuccess,
    onError: (error: unknown) => setCheckError(getErrorMessage(error, 'Saved check run failed')),
  });

  return (
    <div className="space-y-6">
      <GlassPanel title="Launch run" subtitle="Start an ad hoc compliance question or execute a saved check definition.">
        <div className="space-y-5">
          <div className="segmented">
            <button
              type="button"
              className={`segmented-item ${mode === 'adhoc' ? 'segmented-item-active' : ''}`}
              onClick={() => setMode('adhoc')}
            >
              Ad hoc run
            </button>
            <button
              type="button"
              className={`segmented-item ${mode === 'check' ? 'segmented-item-active' : ''}`}
              onClick={() => setMode('check')}
            >
              From saved check
            </button>
          </div>

          {mode === 'adhoc' ? (
            knowledgeBases.length === 0 ? (
              <EmptyState
                title="No Knowledge Bases available"
                description="Create or populate a Knowledge Base first. Ad hoc compliance runs need an explicit Knowledge Base target."
              />
            ) : (
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  adhocMutation.mutate();
                }}
              >
                {adhocError && (
                  <InlineAlert tone="danger" title="Ad hoc run failed">
                    {adhocError}
                  </InlineAlert>
                )}

                <Field label="Knowledge Base" required>
                  <select className="field" value={effectiveAdhocKnowledgeBaseId} onChange={(event) => setAdhocKnowledgeBaseId(event.target.value)}>
                    {knowledgeBases.map((knowledgeBase) => (
                      <option key={knowledgeBase.id} value={knowledgeBase.id}>
                        {knowledgeBase.name}
                      </option>
                    ))}
                  </select>
                </Field>

                <Field label="Question" required hint="Ask the concrete compliance question to evaluate against the selected Knowledge Base.">
                  <textarea
                    className="field min-h-[110px] resize-y"
                    value={adhocQuestion}
                    onChange={(event) => setAdhocQuestion(event.target.value)}
                    placeholder="Can this operation proceed under the stated conditions?"
                  />
                </Field>

                <Field label="Facts JSON" hint="Optional structured facts passed to the backend alongside the question.">
                  <textarea
                    className="field min-h-[132px] resize-y font-mono text-[13px]"
                    value={adhocFacts}
                    onChange={(event) => setAdhocFacts(event.target.value)}
                  />
                </Field>

                <Field label="Instructions override" hint="Optional operator guidance for this one-off run.">
                  <textarea
                    className="field min-h-[96px] resize-y"
                    value={adhocInstructions}
                    onChange={(event) => setAdhocInstructions(event.target.value)}
                    placeholder="Focus on contradictions and explicit evidence only."
                  />
                </Field>

                <div className="grid gap-4 md:grid-cols-2">
                  <Field label="Provider override">
                    <select className="field" value={adhocProviderId} onChange={(event) => setAdhocProviderId(event.target.value)}>
                      <option value="">Workspace default</option>
                      {providers.map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.name}
                        </option>
                      ))}
                    </select>
                  </Field>

                  <Field label="Model override" hint={selectedAdhocProvider ? `Default: ${selectedAdhocProvider.default_model}` : 'Leave blank to use provider default'}>
                    <input
                      className="field"
                      value={adhocModel}
                      onChange={(event) => setAdhocModel(event.target.value)}
                      placeholder={selectedAdhocProvider?.default_model || 'Provider default'}
                    />
                  </Field>
                </div>

                <button type="submit" className="btn-primary" disabled={adhocMutation.isPending}>
                  {adhocMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                  <span>{adhocMutation.isPending ? 'Launching…' : 'Launch ad hoc run'}</span>
                </button>
              </form>
            )
          ) : checks.length === 0 ? (
            <EmptyState title="No saved checks yet" description="Saved checks are listed here once they exist. You can still launch ad hoc runs from this page." />
          ) : (
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                fromCheckMutation.mutate();
              }}
            >
              {checkError && (
                <InlineAlert tone="danger" title="Saved check run failed">
                  {checkError}
                </InlineAlert>
              )}

              <Field label="Saved check" required>
                <select className="field" value={effectiveSelectedCheckId} onChange={(event) => setSelectedCheckId(event.target.value)}>
                  {checks.map((check) => (
                    <option key={check.id} value={check.id}>
                      {check.name}
                    </option>
                  ))}
                </select>
              </Field>

              {selectedCheck && (
                <div className="surface-soft space-y-3 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone={selectedCheck.status === 'active' ? 'success' : 'warning'}>{selectedCheck.status}</StatusBadge>
                    {selectedCheckKnowledgeBase && (
                      <span className="rounded-full border border-slate-200 bg-white/75 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                        {selectedCheckKnowledgeBase.name}
                      </span>
                    )}
                  </div>
                  <p className="text-sm font-medium text-slate-900">{selectedCheck.name}</p>
                  <p className="text-sm text-slate-500">{selectedCheck.description || selectedCheck.query_template}</p>
                </div>
              )}

              <Field label="Question" required hint="Provide the concrete case or scenario for this saved check.">
                <textarea
                  className="field min-h-[110px] resize-y"
                  value={checkQuestion}
                  onChange={(event) => setCheckQuestion(event.target.value)}
                  placeholder="Does the planned procedure comply with the cited manuals?"
                />
              </Field>

              <Field label="Facts JSON" hint="Optional structured facts passed together with the saved check execution.">
                <textarea
                  className="field min-h-[132px] resize-y font-mono text-[13px]"
                  value={checkFacts}
                  onChange={(event) => setCheckFacts(event.target.value)}
                />
              </Field>

              <Field label="Instructions override" hint="Optional per-run override on top of the saved check definition.">
                <textarea
                  className="field min-h-[96px] resize-y"
                  value={checkInstructions}
                  onChange={(event) => setCheckInstructions(event.target.value)}
                  placeholder="Prefer direct conflicts over inferred interpretation."
                />
              </Field>

              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Provider override">
                  <select className="field" value={checkProviderId} onChange={(event) => setCheckProviderId(event.target.value)}>
                    <option value="">Workspace default</option>
                    {providers.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name}
                      </option>
                    ))}
                  </select>
                </Field>

                <Field label="Model override" hint={selectedCheckProvider ? `Default: ${selectedCheckProvider.default_model}` : 'Leave blank to use provider default'}>
                  <input
                    className="field"
                    value={checkModel}
                    onChange={(event) => setCheckModel(event.target.value)}
                    placeholder={selectedCheckProvider?.default_model || 'Provider default'}
                  />
                </Field>
              </div>

              <button type="submit" className="btn-primary" disabled={fromCheckMutation.isPending}>
                {fromCheckMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                <span>{fromCheckMutation.isPending ? 'Launching…' : 'Run saved check'}</span>
              </button>
            </form>
          )}
        </div>
      </GlassPanel>

      <GlassPanel title="Execution source" subtitle="Quick operator context for the current launch surface.">
        <div className="space-y-4">
          <div className="surface-soft space-y-2 p-4">
            <div className="flex items-center gap-2 text-slate-900">
              <Sparkles size={16} className="text-blue-600" />
              <p className="text-sm font-medium">Provider resolution</p>
            </div>
            <p className="text-sm text-slate-500">
              {mode === 'adhoc'
                ? resolveProviderName(adhocProviderId || null, providers)
                : resolveProviderName(checkProviderId || null, providers)}
            </p>
          </div>

          <div className="surface-soft space-y-2 p-4">
            <p className="text-sm font-medium text-slate-900">Current target</p>
            <p className="text-sm text-slate-500">
              {mode === 'adhoc'
                ? knowledgeBases.find((knowledgeBase) => knowledgeBase.id === effectiveAdhocKnowledgeBaseId)?.name || 'Select a Knowledge Base'
                : selectedCheckKnowledgeBase?.name || 'Select a saved check'}
            </p>
          </div>

          <div className="surface-soft space-y-2 p-4">
            <p className="text-sm font-medium text-slate-900">Run style</p>
            <p className="text-sm text-slate-500">
              {mode === 'adhoc'
                ? 'Direct one-off run bound to a Knowledge Base.'
                : 'Run the current question through a saved compliance check definition.'}
            </p>
          </div>
        </div>
      </GlassPanel>
    </div>
  );
};
