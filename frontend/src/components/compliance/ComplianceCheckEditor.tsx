import React, { useMemo } from 'react';
import { AlertTriangle, CheckCircle2, Database, Loader2, Save, ShieldCheck, Trash2, Wand2 } from 'lucide-react';
import { Link } from 'react-router-dom';

import type { ComplianceCheck } from '../../features/compliance/types';
import type { KnowledgeBase } from '../../features/knowledge-bases/types';
import { cn, formatDateTime } from '../../lib/utils';
import type { ComplianceCheckDraft } from './types';
import { DEFAULT_COMPLIANCE_VERDICTS } from './types';
import { EmptyState, Field, InlineAlert, StatusBadge } from '../ui/workbench';

const formatVerdictLabel = (value: string) =>
  value
    .split('_')
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');

const getStatusTone = (status: string): 'success' | 'warning' | 'default' => {
  if (status === 'active') return 'success';
  if (status === 'disabled') return 'warning';
  return 'default';
};

const isDefaultVerdict = (value: string): value is (typeof DEFAULT_COMPLIANCE_VERDICTS)[number] =>
  DEFAULT_COMPLIANCE_VERDICTS.includes(value as (typeof DEFAULT_COMPLIANCE_VERDICTS)[number]);

interface ComplianceCheckEditorProps {
  draft: ComplianceCheckDraft;
  knowledgeBases: KnowledgeBase[];
  selectedCheck: ComplianceCheck | null;
  mode: 'create' | 'edit';
  isDirty: boolean;
  saveBlocked: boolean;
  savePending: boolean;
  deletePending: boolean;
  error: string;
  savedMessage: string;
  onChange: (draft: ComplianceCheckDraft) => void;
  onSave: () => void;
  onReset: () => void;
  onDelete: () => void;
}

export const ComplianceCheckEditor: React.FC<ComplianceCheckEditorProps> = ({
  draft,
  knowledgeBases,
  selectedCheck,
  mode,
  isDirty,
  saveBlocked,
  savePending,
  deletePending,
  error,
  savedMessage,
  onChange,
  onSave,
  onReset,
  onDelete,
}) => {
  const selectedKnowledgeBase = useMemo(
    () => knowledgeBases.find((knowledgeBase) => knowledgeBase.id === draft.knowledge_base_id) || null,
    [draft.knowledge_base_id, knowledgeBases],
  );
  const customVerdicts = useMemo(
    () => draft.allowed_values.filter((verdict) => !isDefaultVerdict(verdict)),
    [draft.allowed_values],
  );

  if (knowledgeBases.length === 0) {
    return (
      <EmptyState
        title="Create a Knowledge Base first"
        description="Compliance Checks must target a Knowledge Base. Add one on the Knowledge Bases page before creating checks here."
        action={
          <Link to="/knowledge-bases" className="btn-primary">
            <Database size={16} />
            <span>Open Knowledge Bases</span>
          </Link>
        }
      />
    );
  }

  const toggleVerdict = (verdict: (typeof DEFAULT_COMPLIANCE_VERDICTS)[number]) => {
    const alreadySelected = draft.allowed_values.includes(verdict);
    if (alreadySelected && draft.allowed_values.length === 1) {
      return;
    }

    const nextKnownVerdicts = DEFAULT_COMPLIANCE_VERDICTS.filter((candidate) =>
      candidate === verdict ? !alreadySelected : draft.allowed_values.includes(candidate),
    );
    const nextAllowedValues = [...nextKnownVerdicts, ...customVerdicts];

    onChange({
      ...draft,
      allowed_values: nextAllowedValues,
      default_on_gap: nextAllowedValues.includes(draft.default_on_gap) ? draft.default_on_gap : nextAllowedValues[0],
    });
  };

  const toggleOutput = (field: keyof Pick<
    ComplianceCheckDraft,
    'include_summary' | 'include_answer' | 'include_evidence' | 'include_gaps' | 'include_conflicts'
  >) => {
    onChange({ ...draft, [field]: !draft[field] });
  };

  return (
    <div className="space-y-6">
      {error && (
        <InlineAlert tone="danger" title="Compliance Check failed to save">
          {error}
        </InlineAlert>
      )}

      {savedMessage && !error && (
        <InlineAlert tone="success" title="Saved">
          {savedMessage}
        </InlineAlert>
      )}

      {mode === 'create' && (
        <InlineAlert tone="warning" title="Draft mode">
          This check is still a draft. Save it once the Knowledge Base, query, and decision policy are ready.
        </InlineAlert>
      )}

      <div className="grid grid-cols-4 gap-4">
        <div className="surface-soft p-4">
          <p className="metric-label">Console state</p>
          <p className="mt-2 text-sm font-medium text-slate-900">{mode === 'create' ? 'New draft' : isDirty ? 'Unsaved changes' : 'Saved definition'}</p>
        </div>
        <div className="surface-soft p-4">
          <p className="metric-label">Status</p>
          <div className="mt-3">
            <StatusBadge tone={getStatusTone(draft.status)}>
              {draft.status === 'active' ? 'Enabled' : draft.status === 'disabled' ? 'Disabled' : draft.status}
            </StatusBadge>
          </div>
        </div>
        <div className="surface-soft p-4">
          <p className="metric-label">Knowledge Base</p>
          <p className="mt-2 text-sm font-medium text-slate-900">{selectedKnowledgeBase?.name || 'Choose a Knowledge Base'}</p>
        </div>
        <div className="surface-soft p-4">
          <p className="metric-label">Default on gap</p>
          <p className="mt-2 text-sm font-medium text-slate-900">{formatVerdictLabel(draft.default_on_gap)}</p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
        <div className="space-y-6">
          <div className="space-y-4">
            <div>
              <p className="text-sm font-medium text-slate-900">Check definition</p>
              <p className="text-sm text-slate-500">Define the reusable operator-facing intent, target Knowledge Base, and question template.</p>
            </div>

            <Field label="Check name" required>
              <input
                className="field"
                value={draft.name}
                onChange={(event) => onChange({ ...draft, name: event.target.value })}
                placeholder="Special airport rule check"
              />
            </Field>

            <Field label="Description" hint="Short operator context for when this check should be reused.">
              <textarea
                className="field min-h-[104px] resize-y"
                value={draft.description}
                onChange={(event) => onChange({ ...draft, description: event.target.value })}
                placeholder="Validate whether the proposed procedure complies with the airport operations corpus."
              />
            </Field>

            <Field label="Knowledge Base" required hint="Compliance target is always a Knowledge Base in the current Workspace.">
              <select
                className="field"
                value={draft.knowledge_base_id}
                onChange={(event) => onChange({ ...draft, knowledge_base_id: event.target.value })}
              >
                <option value="">Select a Knowledge Base</option>
                {knowledgeBases
                  .slice()
                  .sort((left, right) => left.name.localeCompare(right.name))
                  .map((knowledgeBase) => (
                    <option key={knowledgeBase.id} value={knowledgeBase.id}>
                      {knowledgeBase.name}
                    </option>
                  ))}
              </select>
            </Field>

            <Field label="Query template" required hint="The canonical question this check asks of the selected Knowledge Base.">
              <textarea
                className="field min-h-[132px] resize-y"
                value={draft.query_template}
                onChange={(event) => onChange({ ...draft, query_template: event.target.value })}
                placeholder="Assess whether the described operation is compliant with the referenced procedures."
              />
            </Field>

            <Field label="Instructions" hint="Execution guidance for how evidence, conflicts, gaps, and answer structure should be produced.">
              <textarea
                className="field min-h-[132px] resize-y"
                value={draft.instructions}
                onChange={(event) => onChange({ ...draft, instructions: event.target.value })}
                placeholder="Return verdict, supporting evidence, gaps, and conflicts using cited material from the Knowledge Base only."
              />
            </Field>
          </div>

          <div className="surface-soft space-y-4 p-5">
            <div className="flex items-center gap-2 text-slate-900">
              <ShieldCheck size={16} />
              <p className="text-sm font-medium">Verdict policy</p>
            </div>
            <p className="text-sm text-slate-500">Choose which verdicts are allowed and which one the system should use when cited support is incomplete.</p>

            <div className="flex flex-wrap gap-3">
              {DEFAULT_COMPLIANCE_VERDICTS.map((verdict) => {
                const active = draft.allowed_values.includes(verdict);
                return (
                  <button
                    key={verdict}
                    type="button"
                    onClick={() => toggleVerdict(verdict)}
                    className={cn(
                      'rounded-2xl border px-4 py-3 text-sm font-medium transition',
                      active
                        ? 'border-blue-200 bg-blue-50 text-blue-700 shadow-[0_10px_24px_rgba(59,130,246,0.08)]'
                        : 'border-white/80 bg-white/70 text-slate-600 hover:bg-white',
                    )}
                  >
                    {formatVerdictLabel(verdict)}
                  </button>
                );
              })}
            </div>

            {customVerdicts.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {customVerdicts.map((verdict) => (
                  <StatusBadge key={verdict} tone="default">
                    Custom verdict: {formatVerdictLabel(verdict)}
                  </StatusBadge>
                ))}
              </div>
            )}

            <Field label="Default on gap" hint="Used when the response cannot support a stronger verdict from cited material.">
              <select
                className="field"
                value={draft.default_on_gap}
                onChange={(event) => onChange({ ...draft, default_on_gap: event.target.value as ComplianceCheckDraft['default_on_gap'] })}
              >
                {draft.allowed_values.map((verdict) => (
                  <option key={verdict} value={verdict}>
                    {formatVerdictLabel(verdict)}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <div className="surface-soft space-y-4 p-5">
            <div className="flex items-center gap-2 text-slate-900">
              <Wand2 size={16} />
              <p className="text-sm font-medium">Result sections</p>
            </div>
            <p className="text-sm text-slate-500">Keep the saved check opinionated about which result blocks operators should receive by default.</p>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {[
                { key: 'include_summary', label: 'Summary' },
                { key: 'include_answer', label: 'Answer' },
                { key: 'include_evidence', label: 'Evidence' },
                { key: 'include_gaps', label: 'Gaps' },
                { key: 'include_conflicts', label: 'Conflicts' },
              ].map((item) => {
                const enabled = draft[item.key as keyof typeof draft] === true;
                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => toggleOutput(item.key as keyof Pick<
                      ComplianceCheckDraft,
                      'include_summary' | 'include_answer' | 'include_evidence' | 'include_gaps' | 'include_conflicts'
                    >)}
                    className={cn(
                      'flex items-center justify-between rounded-2xl border px-4 py-3 text-left text-sm transition',
                      enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-white/80 bg-white/70 text-slate-600',
                    )}
                  >
                    <span>{item.label}</span>
                    {enabled ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} className="opacity-40" />}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="surface-soft space-y-4 p-5">
            <div>
              <p className="text-sm font-medium text-slate-900">Knowledge Base target</p>
              <p className="text-sm text-slate-500">Operators should always see which Knowledge Base will be queried and whether it is currently ready.</p>
            </div>

            {selectedKnowledgeBase ? (
              <div className="space-y-3 rounded-[24px] border border-white/75 bg-white/75 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-900">{selectedKnowledgeBase.name}</p>
                    <p className="line-clamp-2 text-sm text-slate-500">{selectedKnowledgeBase.description || 'No description yet.'}</p>
                  </div>
                  <StatusBadge tone={selectedKnowledgeBase.status === 'active' ? 'success' : 'warning'}>
                    {selectedKnowledgeBase.status === 'active' ? 'Enabled' : 'Disabled'}
                  </StatusBadge>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl bg-slate-50/90 p-3">
                    <p className="metric-label">Documents</p>
                    <p className="mt-2 text-sm font-medium text-slate-900">{selectedKnowledgeBase.documents.length} total members</p>
                  </div>
                  <div className="rounded-2xl bg-slate-50/90 p-3">
                    <p className="metric-label">Enabled members</p>
                    <p className="mt-2 text-sm font-medium text-slate-900">
                      {selectedKnowledgeBase.documents.filter((document) => document.enabled).length}
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-[24px] border border-dashed border-slate-300/80 bg-white/40 p-5 text-sm text-slate-500">
                Select a Knowledge Base to bind this check to a reusable retrieval scope.
              </div>
            )}
          </div>

          <div className="surface-soft space-y-4 p-5">
            <div>
              <p className="text-sm font-medium text-slate-900">Retrieval tuning</p>
              <p className="text-sm text-slate-500">Keep these as product controls, not raw JSON, so operators can reason about scope and context size.</p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Per-document top K" hint="Sections retrieved from each Knowledge Base member.">
                <input
                  className="field"
                  type="number"
                  min={1}
                  value={draft.per_document_top_k}
                  onChange={(event) => onChange({ ...draft, per_document_top_k: event.target.value })}
                />
              </Field>

              <Field label="Global top K" hint="Merged sections kept for final answer generation.">
                <input
                  className="field"
                  type="number"
                  min={1}
                  value={draft.global_top_k}
                  onChange={(event) => onChange({ ...draft, global_top_k: event.target.value })}
                />
              </Field>

              <Field label="Selection mode">
                <select
                  className="field"
                  value={draft.selection_mode}
                  onChange={(event) => onChange({ ...draft, selection_mode: event.target.value as ComplianceCheckDraft['selection_mode'] })}
                >
                  <option value="outline_llm">Outline LLM</option>
                  <option value="lexical_fallback">Lexical fallback</option>
                </select>
              </Field>

              <Field label="Max context pages" hint="Leave blank to defer to backend defaults.">
                <input
                  className="field"
                  type="number"
                  min={1}
                  value={draft.max_context_pages}
                  onChange={(event) => onChange({ ...draft, max_context_pages: event.target.value })}
                  placeholder="20"
                />
              </Field>

              <Field label="Max context tokens" hint="Leave blank to defer to backend defaults.">
                <input
                  className="field"
                  type="number"
                  min={1}
                  value={draft.max_context_tokens}
                  onChange={(event) => onChange({ ...draft, max_context_tokens: event.target.value })}
                  placeholder="12000"
                />
              </Field>
            </div>
          </div>

          <div className="surface-soft space-y-4 p-5">
            <div>
              <p className="text-sm font-medium text-slate-900">Generation policy</p>
              <p className="text-sm text-slate-500">Keep compliance generation deterministic by default and expose only the basic tuning surface here.</p>
            </div>

            <Field label="Temperature" hint="Use 0 for strict deterministic behavior. Leave blank to defer to backend defaults.">
              <input
                className="field"
                type="number"
                min={0}
                step="0.1"
                value={draft.temperature}
                onChange={(event) => onChange({ ...draft, temperature: event.target.value })}
                placeholder="0"
              />
            </Field>

            <Field label="Availability" hint="Disabled checks remain visible in the catalog but should not be treated as active console configuration.">
              <select className="field" value={draft.status} onChange={(event) => onChange({ ...draft, status: event.target.value })}>
                <option value="active">Enabled</option>
                <option value="disabled">Disabled</option>
              </select>
            </Field>

            <div className="rounded-[24px] border border-white/75 bg-white/72 p-4 text-sm text-slate-500">
              Last updated: {selectedCheck ? formatDateTime(selectedCheck.updated_at) : 'Not saved yet'}
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="btn-primary" onClick={onSave} disabled={saveBlocked || savePending}>
          {savePending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
          <span>{mode === 'create' ? (savePending ? 'Creating…' : 'Create Check') : savePending ? 'Saving…' : 'Save changes'}</span>
        </button>

        <button type="button" className="btn-secondary" onClick={onReset} disabled={savePending || deletePending || (!isDirty && mode !== 'create')}>
          <span>{mode === 'create' ? 'Reset draft' : 'Reset to saved state'}</span>
        </button>

        {mode === 'edit' && (
          <button type="button" className="btn-ghost text-red-600" onClick={onDelete} disabled={savePending || deletePending}>
            {deletePending ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
            <span>{deletePending ? 'Deleting…' : 'Delete check'}</span>
          </button>
        )}
      </div>
    </div>
  );
};
