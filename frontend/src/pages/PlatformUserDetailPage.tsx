import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Save, Loader2, KeyRound, Copy, CheckCircle2 } from 'lucide-react';

import { GlassPanel, SectionToolbar, StatusBadge, Field, InlineAlert } from '../components/ui/workbench';
import { platformApi } from '../features/platform/api';
import { formatDateTime, getErrorMessage } from '../lib/utils';
import type { PlatformResourceRule, PlatformUserUpdateInput } from '../types';

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
          {Object.entries(rule.counts).length === 0 ? (
            <span className="text-xs text-slate-500">No resolved counts.</span>
          ) : (
            Object.entries(rule.counts).map(([key, value]) => (
              <span key={key} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                {key}: {value}
              </span>
            ))
          )}
        </div>
      </div>
    ))}
  </div>
);

export const PlatformUserDetailPage: React.FC = () => {
  const { userId } = useParams<{ userId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const userQuery = useQuery({
    queryKey: ['platform-user', userId],
    queryFn: () => platformApi.getUser(userId!),
    enabled: !!userId,
  });
  const portraitQuery = useQuery({
    queryKey: ['platform-user-access-portrait', userId],
    queryFn: () => platformApi.getUserAccessPortrait(userId!),
    enabled: !!userId,
  });

  const detail = userQuery.data;
  const portrait = portraitQuery.data;

  const [isActive, setIsActive] = useState<boolean | undefined>();
  const [canCreateWorkspace, setCanCreateWorkspace] = useState<boolean | undefined>();
  const [isPlatformAdmin, setIsPlatformAdmin] = useState<boolean | undefined>();
  const [patchError, setPatchError] = useState('');
  const [patchSuccess, setPatchSuccess] = useState('');

  // Reset password state
  const [resetModalOpen, setResetModalOpen] = useState(false);
  const [tempPassword, setTempPassword] = useState('');
  const [resetCopied, setResetCopied] = useState(false);

  // Sync defaults when data loads
  React.useEffect(() => {
    if (detail) {
      setIsActive(detail.is_active);
      setCanCreateWorkspace(detail.can_create_workspace);
      setIsPlatformAdmin(detail.is_platform_admin);
    }
  }, [detail]);

  const patchMutation = useMutation({
    mutationFn: () => {
      const payload: PlatformUserUpdateInput = {};
      if (isActive !== detail?.is_active) payload.is_active = isActive;
      if (canCreateWorkspace !== detail?.can_create_workspace) payload.can_create_workspace = canCreateWorkspace;
      if (isPlatformAdmin !== detail?.is_platform_admin) payload.is_platform_admin = isPlatformAdmin;
      return platformApi.patchUser(userId!, payload);
    },
    onSuccess: () => {
      setPatchSuccess('User flags updated successfully.');
      setPatchError('');
      queryClient.invalidateQueries({ queryKey: ['platform-user', userId] });
      queryClient.invalidateQueries({ queryKey: ['platform-users'] });
    },
    onError: (error: unknown) => {
      setPatchError(getErrorMessage(error, 'Failed to update user'));
      setPatchSuccess('');
    },
  });

  const resetPasswordMutation = useMutation({
    mutationFn: () => platformApi.resetUserPassword(userId!),
    onSuccess: (response) => {
      setTempPassword(response.temporary_password);
      setResetModalOpen(true);
      setResetCopied(false);
    },
    onError: (error: unknown) => {
      setPatchError(getErrorMessage(error, 'Failed to reset password'));
    },
  });

  const handleCopyTempPassword = async () => {
    try {
      await navigator.clipboard.writeText(tempPassword);
      setResetCopied(true);
      setTimeout(() => setResetCopied(false), 3000);
    } catch {
      // Clipboard may not be available
    }
  };

  const hasChanges = detail && (isActive !== detail.is_active || canCreateWorkspace !== detail.can_create_workspace || isPlatformAdmin !== detail.is_platform_admin);

  if (!userId) return null;

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="User Detail"
        description={detail ? `${detail.username} · ${detail.email || 'no email'}` : 'Loading…'}
      />

      <button type="button" className="btn-secondary" onClick={() => navigate('/platform/users')}>
        <ArrowLeft size={16} />
        <span>Back to users</span>
      </button>

      {userQuery.isLoading && <p className="text-sm text-slate-500">Loading user details…</p>}

      {detail && (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            <GlassPanel title="User flags" subtitle="Toggle capabilities for this user.">
              <div className="space-y-4">
                <label className="flex items-center gap-3 text-sm">
                  <input type="checkbox" checked={isActive ?? false} onChange={(e) => setIsActive(e.target.checked)} />
                  <span className="font-medium text-slate-900">is_active</span>
                  <span className="text-slate-500">— can this user log in?</span>
                </label>
                <label className="flex items-center gap-3 text-sm">
                  <input type="checkbox" checked={canCreateWorkspace ?? false} onChange={(e) => setCanCreateWorkspace(e.target.checked)} />
                  <span className="font-medium text-slate-900">can_create_workspace</span>
                  <span className="text-slate-500">— self-service workspace creation</span>
                </label>
                <label className="flex items-center gap-3 text-sm">
                  <input type="checkbox" checked={isPlatformAdmin ?? false} onChange={(e) => setIsPlatformAdmin(e.target.checked)} />
                  <span className="font-medium text-slate-900">is_platform_admin</span>
                  <span className="text-slate-500">— full platform-level access</span>
                </label>

                {patchError && <InlineAlert tone="danger" title="Update failed">{patchError}</InlineAlert>}
                {patchSuccess && <InlineAlert tone="success" title="Updated">{patchSuccess}</InlineAlert>}

                <div className="flex justify-end">
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={!hasChanges || patchMutation.isPending}
                    onClick={() => {
                      setPatchError('');
                      setPatchSuccess('');
                      patchMutation.mutate();
                    }}
                  >
                    {patchMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                    <span>{patchMutation.isPending ? 'Saving…' : 'Save changes'}</span>
                  </button>
                </div>
              </div>
            </GlassPanel>

            <GlassPanel title="Identity" subtitle="Read-only user information.">
              <div className="space-y-3 text-sm">
                <Field label="User ID"><p className="text-slate-900 font-mono text-xs">{detail.id}</p></Field>
                <Field label="Username"><p className="text-slate-900">{detail.username}</p></Field>
                <Field label="Email"><p className="text-slate-900">{detail.email || '—'}</p></Field>
                <Field label="Primary tenant ID"><p className="text-slate-900 font-mono text-xs">{detail.tenant_id}</p></Field>
                <Field label="Compat tenant ID"><p className="text-slate-900 font-mono text-xs">{portrait?.user.compat_tenant_id || '—'}</p></Field>
                <Field label="Created"><p className="text-slate-900">{formatDateTime(detail.created_at)}</p></Field>
                <Field label="Updated"><p className="text-slate-900">{formatDateTime(detail.updated_at)}</p></Field>
              </div>

              <div className="mt-4 pt-4 border-t border-slate-200">
                <button
                  type="button"
                  className="btn-secondary w-full"
                  disabled={resetPasswordMutation.isPending}
                  onClick={() => {
                    setPatchError('');
                    resetPasswordMutation.mutate();
                  }}
                >
                  {resetPasswordMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <KeyRound size={16} />}
                  <span>{resetPasswordMutation.isPending ? 'Resetting…' : 'Reset password'}</span>
                </button>
                <p className="mt-2 text-xs text-slate-500">Generates a temporary password. The user will be forced to change it on next login.</p>
              </div>
            </GlassPanel>
          </div>

          {/* Reset Password Modal */}
          {resetModalOpen && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
              <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl space-y-4">
                <div className="flex items-center gap-3">
                  <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-amber-100 text-amber-600">
                    <KeyRound size={20} />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-slate-900">Temporary Password</h3>
                    <p className="text-sm text-slate-500">Copy and share with the user securely.</p>
                  </div>
                </div>

                <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <code className="flex-1 font-mono text-sm text-slate-900 select-all break-all">{tempPassword}</code>
                  <button type="button" className="btn-secondary shrink-0" onClick={handleCopyTempPassword}>
                    {resetCopied ? <CheckCircle2 size={16} className="text-green-600" /> : <Copy size={16} />}
                    <span>{resetCopied ? 'Copied' : 'Copy'}</span>
                  </button>
                </div>

                <InlineAlert tone="warning" title="One-time visibility">
                  This password will not be shown again. The user must change it on their next login.
                </InlineAlert>

                <div className="flex justify-end">
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => {
                      setResetModalOpen(false);
                      setTempPassword('');
                    }}
                  >
                    <span>Done</span>
                  </button>
                </div>
              </div>
            </div>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            <GlassPanel title="Access portrait" subtitle="Normalized effective access for the default resolved context.">
              {!portrait ? (
                <p className="text-sm text-slate-500">Loading portrait…</p>
              ) : (
                <div className="space-y-4 text-sm">
                  <Field label="Requested context">
                    <p className="text-slate-900 font-mono text-xs">
                      tenant={portrait.effective_portrait.requested_context.tenant_id || 'auto'} / workspace={portrait.effective_portrait.requested_context.workspace_id || 'auto'}
                    </p>
                  </Field>
                  <Field label="Resolved context">
                    <p className="text-slate-900 font-mono text-xs">
                      {portrait.effective_portrait.resolved_context
                        ? `${portrait.effective_portrait.resolved_context.tenant_id} / ${portrait.effective_portrait.resolved_context.workspace_id} (${portrait.effective_portrait.resolved_context.source})`
                        : 'unresolved'}
                    </p>
                  </Field>
                  <Field label="Tenant membership">
                    <p className="text-slate-900">
                      {portrait.effective_portrait.tenant_membership.role || '—'} / {portrait.effective_portrait.tenant_membership.status || '—'}
                    </p>
                  </Field>
                  <Field label="Workspace membership">
                    <p className="text-slate-900">
                      {portrait.effective_portrait.workspace_membership.role || '—'} / {portrait.effective_portrait.workspace_membership.status || '—'}
                    </p>
                  </Field>
                  <Field label="Effective workspace permissions">
                    <p className="text-slate-900">{formatPermissionSummary(portrait.effective_portrait.workspace_membership.effective_permissions)}</p>
                  </Field>
                  <Field label="Platform permissions">
                    <div className="flex flex-wrap gap-2">
                      <StatusBadge tone={portrait.effective_portrait.platform_permissions.can_access_platform_control_plane ? 'warning' : 'default'}>
                        platform access: {portrait.effective_portrait.platform_permissions.can_access_platform_control_plane ? 'yes' : 'no'}
                      </StatusBadge>
                      <StatusBadge tone={portrait.effective_portrait.platform_permissions.can_create_workspace ? 'success' : 'default'}>
                        workspace create: {portrait.effective_portrait.platform_permissions.can_create_workspace ? 'yes' : 'no'}
                      </StatusBadge>
                    </div>
                  </Field>
                </div>
              )}
            </GlassPanel>

            <GlassPanel title="Explainability" subtitle="Why actions are allowed or denied in the resolved context.">
              {!portrait ? (
                <p className="text-sm text-slate-500">Loading explainability…</p>
              ) : (
                <div className="space-y-4">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Allowed</p>
                    <div className="mt-2 space-y-2">
                      {portrait.effective_portrait.explainability.allowed_reasons.map((reason) => (
                        <p key={reason} className="rounded-2xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{reason}</p>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Denied</p>
                    <div className="mt-2 space-y-2">
                      {portrait.effective_portrait.explainability.denied_reasons.map((reason) => (
                        <p key={reason} className="rounded-2xl bg-amber-50 px-3 py-2 text-sm text-amber-900">{reason}</p>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </GlassPanel>
          </div>

          <GlassPanel title="Tenant memberships" subtitle={`${detail.tenant_memberships.length} membership(s)`}>
            {detail.tenant_memberships.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">No tenant memberships.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500">
                      <th className="px-4 py-3 font-medium">Tenant</th>
                      <th className="px-4 py-3 font-medium">Role</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.tenant_memberships.map((tm) => (
                      <tr key={tm.id} className="border-b border-slate-100">
                        <td className="px-4 py-3 font-medium text-slate-900">{tm.tenant_name}</td>
                        <td className="px-4 py-3"><StatusBadge>{tm.role}</StatusBadge></td>
                        <td className="px-4 py-3"><StatusBadge tone={tm.status === 'active' ? 'success' : 'default'}>{tm.status}</StatusBadge></td>
                        <td className="px-4 py-3 text-slate-500">{formatDateTime(tm.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>

          <GlassPanel title="Workspace memberships" subtitle={`${detail.workspace_memberships.length} membership(s)`}>
            {detail.workspace_memberships.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">No workspace memberships.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500">
                      <th className="px-4 py-3 font-medium">Workspace</th>
                      <th className="px-4 py-3 font-medium">Tenant</th>
                      <th className="px-4 py-3 font-medium">Role</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.workspace_memberships.map((wm) => (
                      <tr key={wm.id} className="border-b border-slate-100">
                        <td className="px-4 py-3 font-medium text-slate-900">{wm.workspace_name} <span className="text-xs text-slate-400">({wm.workspace_slug})</span></td>
                        <td className="px-4 py-3 text-slate-600">{wm.tenant_name}</td>
                        <td className="px-4 py-3"><StatusBadge>{wm.role}</StatusBadge></td>
                        <td className="px-4 py-3"><StatusBadge tone={wm.status === 'active' ? 'success' : 'default'}>{wm.status}</StatusBadge></td>
                        <td className="px-4 py-3 text-slate-500">{formatDateTime(wm.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>

          {portrait && (
            <GlassPanel title="Resource rules" subtitle="Resolved scope summaries returned directly by the backend portrait API.">
              <ResourceRulesPanel rules={portrait.resource_rules} />
            </GlassPanel>
          )}
        </>
      )}
    </div>
  );
};
