import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Archive, Loader2 } from 'lucide-react';

import { GlassPanel, SectionToolbar, StatusBadge, Field, InlineAlert } from '../components/ui/workbench';
import { platformApi } from '../features/platform/api';
import { formatDateTime, getErrorMessage } from '../lib/utils';
import type { PlatformResourceRule } from '../types';

const formatPermissionSummary = (permissions: Record<string, boolean | undefined>) => {
  const enabled = Object.entries(permissions)
    .filter(([, value]) => value)
    .map(([key]) => key);
  return enabled.length > 0 ? enabled.join(', ') : 'none';
};

const ResourceRulesPanel = ({ rules }: { rules: Record<string, PlatformResourceRule> }) => (
  <div className="space-y-4">
    {Object.entries(rules).map(([name, rule]) => (
      <div key={name} className="rounded-2xl border border-slate-200 bg-white/70 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-semibold text-slate-900">{name}</p>
          <StatusBadge>{rule.scope}</StatusBadge>
        </div>
        <p className="mt-2 text-sm text-slate-600">{rule.explanation}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(rule.counts).map(([key, value]) => (
            <span key={key} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
              {key}: {value}
            </span>
          ))}
        </div>
      </div>
    ))}
  </div>
);

export const PlatformWorkspaceDetailPage: React.FC = () => {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [archiveConfirmed, setArchiveConfirmed] = useState(false);
  const [archiveError, setArchiveError] = useState('');

  const wsQuery = useQuery({
    queryKey: ['platform-workspace', workspaceId],
    queryFn: () => platformApi.getWorkspace(workspaceId!),
    enabled: !!workspaceId,
  });
  const portraitQuery = useQuery({
    queryKey: ['platform-workspace-access-portrait', workspaceId],
    queryFn: () => platformApi.getWorkspaceAccessPortrait(workspaceId!),
    enabled: !!workspaceId,
  });

  const detail = wsQuery.data;
  const portrait = portraitQuery.data;

  const archiveMutation = useMutation({
    mutationFn: () => platformApi.archiveWorkspace(workspaceId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['platform-workspace', workspaceId] });
      queryClient.invalidateQueries({ queryKey: ['platform-workspaces'] });
      setArchiveConfirmed(false);
      setArchiveError('');
    },
    onError: (error: unknown) => {
      setArchiveError(getErrorMessage(error, 'Archive failed'));
    },
  });

  const canArchive = detail && detail.status === 'active' && !detail.is_default;

  if (!workspaceId) return null;

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Workspace Detail"
        description={detail ? `${detail.name} · ${detail.slug}` : 'Loading…'}
      />

      <button type="button" className="btn-secondary" onClick={() => navigate('/platform/workspaces')}>
        <ArrowLeft size={16} />
        <span>Back to workspaces</span>
      </button>

      {wsQuery.isLoading && <p className="text-sm text-slate-500">Loading workspace details…</p>}

      {detail && (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            <GlassPanel title="Workspace info">
              <div className="space-y-3 text-sm">
                <Field label="ID"><p className="font-mono text-xs text-slate-900">{detail.id}</p></Field>
                <Field label="Name"><p className="text-slate-900">{detail.name}</p></Field>
                <Field label="Slug"><p className="font-mono text-xs text-slate-900">{detail.slug}</p></Field>
                <Field label="Tenant"><p className="text-slate-900">{detail.tenant_name} <span className="text-xs text-slate-400">({detail.tenant_id})</span></p></Field>
                <Field label="Status"><StatusBadge tone={detail.status === 'active' ? 'success' : 'danger'}>{detail.status}</StatusBadge></Field>
                <Field label="Default"><StatusBadge tone={detail.is_default ? 'warning' : 'default'}>{detail.is_default ? 'Yes' : 'No'}</StatusBadge></Field>
                <Field label="Founder"><p className="text-slate-900">{portrait?.founder.username || detail.founder_username || detail.founder_email || '—'}</p></Field>
                <Field label="Created by"><p className="font-mono text-xs text-slate-900">{detail.created_by || '—'}</p></Field>
                <Field label="Created"><p className="text-slate-900">{formatDateTime(detail.created_at)}</p></Field>
                {detail.archived_at && <Field label="Archived at"><p className="text-red-600">{formatDateTime(detail.archived_at)}</p></Field>}
                {detail.archived_by && <Field label="Archived by"><p className="font-mono text-xs text-slate-900">{detail.archived_by}</p></Field>}
              </div>
            </GlassPanel>

            <GlassPanel title="Archive workspace" subtitle="Archive freezes the workspace. Default workspaces cannot be archived.">
              <div className="space-y-4">
                {!canArchive && detail.status === 'archived' && (
                  <InlineAlert tone="warning" title="Already archived">
                    This workspace was archived at {formatDateTime(detail.archived_at)}.
                  </InlineAlert>
                )}
                {!canArchive && detail.is_default && (
                  <InlineAlert tone="warning" title="Default workspace">
                    Default workspaces cannot be archived.
                  </InlineAlert>
                )}
                {canArchive && (
                  <>
                    <label className="flex items-start gap-3 rounded-2xl border border-white/80 bg-white/70 p-4 text-sm text-slate-600">
                      <input type="checkbox" checked={archiveConfirmed} onChange={(e) => setArchiveConfirmed(e.target.checked)} className="mt-1" />
                      <span>I understand that archiving freezes this workspace and invalidates pending invites.</span>
                    </label>
                    {archiveError && <InlineAlert tone="danger" title="Archive failed">{archiveError}</InlineAlert>}
                    <div className="flex justify-end">
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={!archiveConfirmed || archiveMutation.isPending}
                        onClick={() => { setArchiveError(''); archiveMutation.mutate(); }}
                      >
                        {archiveMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Archive size={16} />}
                        <span>{archiveMutation.isPending ? 'Archiving…' : 'Archive workspace'}</span>
                      </button>
                    </div>
                  </>
                )}
              </div>
            </GlassPanel>
          </div>

          {portrait && (
            <div className="grid gap-6 lg:grid-cols-3">
              <GlassPanel title="Membership summary">
                <div className="space-y-3 text-sm">
                  <Field label="Total"><p className="text-slate-900">{portrait.membership_summary.total}</p></Field>
                  <Field label="Active"><p className="text-slate-900">{portrait.membership_summary.active}</p></Field>
                  <Field label="Founder invariant">
                    <StatusBadge tone={portrait.membership_summary.active_founder_invariant_ok ? 'success' : 'danger'}>
                      {portrait.membership_summary.active_founder_invariant_ok ? 'OK' : 'Broken'}
                    </StatusBadge>
                  </Field>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(portrait.membership_summary.by_role).map(([role, count]) => (
                      <span key={role} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                        {role}: {count}
                      </span>
                    ))}
                  </div>
                </div>
              </GlassPanel>
              <GlassPanel title="Invite summary">
                <div className="flex flex-wrap gap-2">
                  {Object.entries(portrait.invite_summary).map(([status, count]) => (
                    <span key={status} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                      {status}: {count}
                    </span>
                  ))}
                </div>
              </GlassPanel>
              <GlassPanel title="Archive state">
                <div className="space-y-3 text-sm">
                  <Field label="Status"><StatusBadge tone={portrait.archive_state.status === 'active' ? 'success' : 'danger'}>{portrait.archive_state.status}</StatusBadge></Field>
                  <Field label="Archived at"><p className="text-slate-900">{portrait.archive_state.archived_at ? formatDateTime(portrait.archive_state.archived_at) : '—'}</p></Field>
                  <Field label="Archived by"><p className="font-mono text-xs text-slate-900">{portrait.archive_state.archived_by || '—'}</p></Field>
                </div>
              </GlassPanel>
            </div>
          )}

          <GlassPanel title="Members" subtitle={`${(portrait?.members || detail.members).length} member(s)`}>
            {(portrait?.members || detail.members).length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">No members.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500">
                      <th className="px-4 py-3 font-medium">Username</th>
                      <th className="px-4 py-3 font-medium">Email</th>
                      <th className="px-4 py-3 font-medium">Role</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Effective permissions</th>
                      <th className="px-4 py-3 font-medium">Joined</th>
                    </tr>
                  </thead>
                  <tbody>
                    {portrait
                      ? portrait.members.map((m) => (
                          <tr key={m.id} className="border-b border-slate-100">
                            <td className="px-4 py-3 font-medium text-slate-900">{m.username}</td>
                            <td className="px-4 py-3 text-slate-600">{m.email || '—'}</td>
                            <td className="px-4 py-3"><StatusBadge>{m.role}</StatusBadge></td>
                            <td className="px-4 py-3"><StatusBadge tone={m.status === 'active' ? 'success' : 'default'}>{m.status}</StatusBadge></td>
                            <td className="px-4 py-3 text-slate-600">{formatPermissionSummary(m.effective_permissions)}</td>
                            <td className="px-4 py-3 text-slate-500">{formatDateTime(m.created_at)}</td>
                          </tr>
                        ))
                      : detail.members.map((m) => (
                          <tr key={m.id} className="border-b border-slate-100">
                            <td className="px-4 py-3 font-medium text-slate-900">{m.username}</td>
                            <td className="px-4 py-3 text-slate-600">{m.email || '—'}</td>
                            <td className="px-4 py-3"><StatusBadge>{m.role}</StatusBadge></td>
                            <td className="px-4 py-3"><StatusBadge tone={m.status === 'active' ? 'success' : 'default'}>{m.status}</StatusBadge></td>
                            <td className="px-4 py-3 text-slate-600">—</td>
                            <td className="px-4 py-3 text-slate-500">{formatDateTime(m.created_at)}</td>
                          </tr>
                        ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>

          {portrait && (
            <GlassPanel title="Resource scope" subtitle="Workspace-level resource ownership and visibility summaries.">
              <ResourceRulesPanel rules={portrait.resource_scope} />
            </GlassPanel>
          )}
        </>
      )}
    </div>
  );
};
