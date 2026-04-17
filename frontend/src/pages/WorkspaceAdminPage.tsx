import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRightLeft, Copy, MailPlus, RefreshCcw, Settings2, Shield, UserPlus, Users } from 'lucide-react';

import { Field, GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { authApi } from '../features/auth/api';
import { workspacesApi } from '../features/workspaces/api';
import {
  clearStoredAuth,
  resolveActiveWorkspaceId,
  resolveAppPath,
  resolveStoredTenantMembership,
  resolveStoredUser,
  resolveStoredWorkspace,
  resolveStoredWorkspaceMembership,
  storeAuthTokenResponse,
  updateStoredWorkspace,
} from '../lib/api/client';
import { formatDateTime, getErrorMessage } from '../lib/utils';
import type {
  Workspace,
  WorkspaceCapabilityKey,
  WorkspaceInvite,
  WorkspaceInviteRole,
  WorkspaceListItem,
  WorkspaceMember,
  WorkspaceMembershipRole,
  WorkspaceMembershipStatus,
  WorkspacePermissions,
} from '../types';

const WORKSPACE_CAPABILITY_LABELS: Record<WorkspaceCapabilityKey, string> = {
  can_view_workspace: 'View workspace',
  can_edit_workspace_metadata: 'Edit metadata',
  can_manage_members: 'Manage members',
  can_manage_invites: 'Manage invites',
  can_transfer_founder: 'Transfer founder',
  can_archive_workspace: 'Archive workspace',
  can_manage_api_keys: 'Manage API keys',
  can_manage_providers: 'Manage providers',
  can_manage_knowledge_bases: 'Manage knowledge bases',
  can_manage_skills: 'Manage skills',
  can_run_skills: 'Run skills',
  can_view_runs: 'View runs',
};

const WORKSPACE_CAPABILITY_KEYS = Object.keys(WORKSPACE_CAPABILITY_LABELS) as WorkspaceCapabilityKey[];
const FOUNDER_ONLY_CAPABILITY_KEYS = new Set<WorkspaceCapabilityKey>(['can_transfer_founder', 'can_archive_workspace']);

const ROLE_TONE: Record<string, 'default' | 'success' | 'warning' | 'accent'> = {
  founder: 'accent',
  admin: 'success',
  member: 'default',
  guest: 'warning',
};

const STATUS_TONE: Record<string, 'default' | 'success' | 'warning' | 'danger'> = {
  active: 'success',
  pending: 'warning',
  accepted: 'success',
  archived: 'warning',
  disabled: 'warning',
  removed: 'danger',
  revoked: 'danger',
  expired: 'warning',
};

const getActorInviteRoles = (actorRole: string | null) => {
  if (actorRole === 'founder') return ['admin', 'member', 'guest'] as const;
  if (actorRole === 'admin') return ['member', 'guest'] as const;
  return [] as const;
};

const canManageMember = (actorRole: string | null, member: WorkspaceMember) => {
  if (actorRole === 'founder') return member.role !== 'founder';
  if (actorRole === 'admin') return member.role === 'member' || member.role === 'guest';
  return false;
};

const getManagedRoleOptions = (actorRole: string | null, member: WorkspaceMember) => {
  if (!canManageMember(actorRole, member)) return [] as WorkspaceMembershipRole[];
  if (actorRole === 'founder') return ['admin', 'member', 'guest'];
  return ['member', 'guest'];
};

const canRevokeInvite = (actorRole: string | null, invite: WorkspaceInvite) => {
  if (invite.status !== 'pending') return false;
  if (actorRole === 'founder') return true;
  if (actorRole === 'admin') return invite.role === 'member' || invite.role === 'guest';
  return false;
};

const parsePermissionsOverrideInput = (value: string, role: WorkspaceMembershipRole | WorkspaceInviteRole): WorkspacePermissions | undefined => {
  const trimmed = value.trim();
  if (!trimmed) return undefined;

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error('Capability overrides must be valid JSON.');
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Capability overrides must be a JSON object.');
  }

  const normalized: WorkspacePermissions = {};
  for (const [rawKey, rawValue] of Object.entries(parsed)) {
    if (!WORKSPACE_CAPABILITY_KEYS.includes(rawKey as WorkspaceCapabilityKey)) {
      throw new Error(`Capability override "${rawKey}" is not recognized.`);
    }
    if (typeof rawValue !== 'boolean') {
      throw new Error(`Capability override "${rawKey}" must be true or false.`);
    }
    if (rawValue && role !== 'founder' && FOUNDER_ONLY_CAPABILITY_KEYS.has(rawKey as WorkspaceCapabilityKey)) {
      throw new Error(`Capability override "${rawKey}" is founder-only and cannot be granted to ${role}.`);
    }
    normalized[rawKey as WorkspaceCapabilityKey] = rawValue;
  }

  return normalized;
};

const formatPermissionsOverride = (value: WorkspacePermissions | null | undefined) => {
  if (!value || Object.keys(value).length === 0) return '';
  return JSON.stringify(value, null, 2);
};

const toIsoDateTime = (value: string) => (value ? new Date(value).toISOString() : undefined);

const getInviteLink = (inviteId: string) =>
  typeof window === 'undefined' ? resolveAppPath(`/workspace-invites/${inviteId}/accept`) : `${window.location.origin}${resolveAppPath(`/workspace-invites/${inviteId}/accept`)}`;

const copyToClipboard = async (value: string) => {
  if (typeof navigator === 'undefined' || !navigator.clipboard) {
    throw new Error('Clipboard is unavailable in this browser.');
  }
  await navigator.clipboard.writeText(value);
};

type EditableMemberCardProps = {
  actorRole: string | null;
  member: WorkspaceMember;
  savePending: boolean;
  removePending: boolean;
  onSave: (membershipId: string, payload: { role: WorkspaceMembershipRole; status: WorkspaceMembershipStatus; permissions_override?: WorkspacePermissions }) => void;
  onRemove: (membershipId: string) => void;
};

const EditableMemberCard: React.FC<EditableMemberCardProps> = ({ actorRole, member, savePending, removePending, onSave, onRemove }) => {
  const manageAllowed = canManageMember(actorRole, member);
  const [role, setRole] = useState<WorkspaceMembershipRole>(member.role);
  const [status, setStatus] = useState<WorkspaceMembershipStatus>(member.status);
  const [permissionsOverride, setPermissionsOverride] = useState(() => formatPermissionsOverride(member.permissions_override));
  const [error, setError] = useState('');
  const roleOptions = getManagedRoleOptions(actorRole, member);

  return (
    <div className="surface-soft space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium text-slate-900">{member.email || member.user_id}</p>
            <StatusBadge tone={ROLE_TONE[member.role] || 'default'}>{member.role}</StatusBadge>
            <StatusBadge tone={STATUS_TONE[member.status] || 'default'}>{member.status}</StatusBadge>
          </div>
          <p className="text-sm text-slate-500">User ID {member.user_id}</p>
          <p className="text-xs text-slate-500">Updated {formatDateTime(member.updated_at)}</p>
        </div>
        {manageAllowed ? (
          <button type="button" className="btn-secondary" onClick={() => onRemove(member.id)} disabled={removePending}>
            <span>{removePending ? 'Removing…' : 'Remove member'}</span>
          </button>
        ) : (
          <p className="text-xs text-slate-500">
            {member.role === 'founder' ? 'Founder ownership moves through transfer only.' : 'Your current role cannot change this membership.'}
          </p>
        )}
      </div>

      {manageAllowed && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Role" hint={actorRole === 'admin' ? 'Admins may manage only member and guest roles.' : 'Founders may manage admin, member, and guest roles.'}>
              <select className="field" value={role} onChange={(event) => setRole(event.target.value as WorkspaceMembershipRole)}>
                {roleOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Status">
              <select className="field" value={status} onChange={(event) => setStatus(event.target.value as WorkspaceMembershipStatus)}>
                <option value="active">active</option>
                <option value="disabled">disabled</option>
                <option value="removed">removed</option>
              </select>
            </Field>
          </div>

          <Field label="Capability overrides" hint="Only known capability keys are allowed. Founder-only capabilities cannot be granted to non-founder roles.">
            <textarea
              className="field min-h-[112px] font-mono text-xs"
              value={permissionsOverride}
              onChange={(event) => setPermissionsOverride(event.target.value)}
              placeholder='{"can_manage_api_keys": false}'
            />
          </Field>

          {error && (
            <InlineAlert tone="warning" title="Member update is not valid">
              {error}
            </InlineAlert>
          )}

          <div className="flex justify-end">
            <button
              type="button"
              className="btn-primary"
              disabled={savePending}
              onClick={() => {
                try {
                  setError('');
                  onSave(member.id, {
                    role,
                    status,
                    permissions_override: parsePermissionsOverrideInput(permissionsOverride, role),
                  });
                } catch (nextError) {
                  setError(getErrorMessage(nextError, 'Failed to parse capability overrides'));
                }
              }}
            >
              <span>{savePending ? 'Saving…' : 'Save member'}</span>
            </button>
          </div>
        </>
      )}
    </div>
  );
};

type WorkspaceSwitcherCardProps = {
  workspaceId: string;
  workspaceOptions: WorkspaceListItem[];
  switchPending: boolean;
  switchError: string;
  onSwitch: (workspaceId: string) => void;
};

const WorkspaceSwitcherCard: React.FC<WorkspaceSwitcherCardProps> = ({ workspaceId, workspaceOptions, switchPending, switchError, onSwitch }) => {
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(() => workspaceId || workspaceOptions[0]?.id || '');

  return (
    <div className="surface-soft space-y-4 p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
        <ArrowRightLeft size={16} className="text-blue-600" />
        <span>Switch workspace</span>
      </div>
      <Field label="Available workspaces" hint="POST /api/v1/auth/context/switch still performs the handoff, but the list now comes from GET /api/v1/workspaces.">
        <select className="field" value={selectedWorkspaceId} onChange={(event) => setSelectedWorkspaceId(event.target.value)}>
          {workspaceOptions.map((item) => (
            <option key={item.id} value={item.id} disabled={item.status !== 'active'}>
              {item.name} · {item.membership_role} · {item.status}
            </option>
          ))}
        </select>
      </Field>
      {switchError && (
        <InlineAlert tone="warning" title="Workspace switch failed">
          {switchError}
        </InlineAlert>
      )}
      <button
        type="button"
        className="btn-primary"
        disabled={!selectedWorkspaceId.trim() || selectedWorkspaceId === workspaceId || switchPending}
        onClick={() => onSwitch(selectedWorkspaceId.trim())}
      >
        <span>{switchPending ? 'Switching…' : 'Switch workspace context'}</span>
      </button>
    </div>
  );
};

type WorkspaceMetadataCardProps = {
  workspace: Partial<Workspace> | null;
  canEditWorkspaceMetadata: boolean;
  metadataError: string;
  metadataPending: boolean;
  onSave: (payload: { name: string; slug: string }) => void;
};

const WorkspaceMetadataCard: React.FC<WorkspaceMetadataCardProps> = ({
  workspace,
  canEditWorkspaceMetadata,
  metadataError,
  metadataPending,
  onSave,
}) => {
  const [metadataName, setMetadataName] = useState(workspace?.name || '');
  const [metadataSlug, setMetadataSlug] = useState(workspace?.slug || '');

  return (
    <div className="space-y-4">
      <div className="surface-soft space-y-2 p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <Settings2 size={16} className="text-blue-600" />
          <span>Metadata</span>
        </div>
        <p className="text-sm text-slate-500">Founder and admin can edit workspace name and slug when `can_edit_workspace_metadata` is present.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Workspace name">
          <input className="field" value={metadataName} onChange={(event) => setMetadataName(event.target.value)} disabled={!canEditWorkspaceMetadata} />
        </Field>
        <Field label="Workspace slug" hint="The backend normalizes slug casing and separators.">
          <input className="field" value={metadataSlug} onChange={(event) => setMetadataSlug(event.target.value)} disabled={!canEditWorkspaceMetadata} />
        </Field>
      </div>
      {metadataError && (
        <InlineAlert tone="warning" title="Workspace settings update failed">
          {metadataError}
        </InlineAlert>
      )}
      {!canEditWorkspaceMetadata && (
        <InlineAlert tone="warning" title="Workspace settings are read-only">
          The current workspace membership does not grant `can_edit_workspace_metadata`.
        </InlineAlert>
      )}
      <div className="flex justify-end">
        <button
          type="button"
          className="btn-primary"
          disabled={!canEditWorkspaceMetadata || metadataPending}
          onClick={() =>
            onSave({
              name: metadataName.trim(),
              slug: metadataSlug.trim(),
            })
          }
        >
          <span>{metadataPending ? 'Saving…' : 'Save workspace settings'}</span>
        </button>
      </div>
    </div>
  );
};

export const WorkspaceAdminPage: React.FC = () => {
  const queryClient = useQueryClient();
  const user = resolveStoredUser();
  const workspace = resolveStoredWorkspace();
  const tenantMembership = resolveStoredTenantMembership();
  const workspaceMembership = resolveStoredWorkspaceMembership();
  const workspaceId = useMemo(() => {
    if (typeof workspace?.id === 'string' && workspace.id.trim()) return workspace.id;
    try {
      return resolveActiveWorkspaceId();
    } catch {
      return '';
    }
  }, [workspace]);

  const actorRole = typeof workspaceMembership?.role === 'string' ? workspaceMembership.role : null;
  const actorPermissions = workspaceMembership?.permissions || {};
  const canEditWorkspaceMetadata = actorPermissions.can_edit_workspace_metadata === true;
  const canManageMembers = actorPermissions.can_manage_members === true;
  const canManageInvites = actorPermissions.can_manage_invites === true;
  const canTransferFounder = actorPermissions.can_transfer_founder === true;
  const canArchiveWorkspace = actorPermissions.can_archive_workspace === true;
  const canAccessAdminSurface = canEditWorkspaceMetadata || canManageMembers || canManageInvites || canTransferFounder || canArchiveWorkspace;
  const grantedCapabilities = (Object.entries(actorPermissions) as Array<[WorkspaceCapabilityKey, boolean | undefined]>)
    .filter(([, granted]) => granted)
    .map(([key]) => key);

  const [successMessage, setSuccessMessage] = useState('');
  const [memberUserId, setMemberUserId] = useState('');
  const [memberRole, setMemberRole] = useState<WorkspaceMembershipRole>('member');
  const [memberOverrideText, setMemberOverrideText] = useState('');
  const [memberFormError, setMemberFormError] = useState('');

  const inviteRoleOptions = getActorInviteRoles(actorRole);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<WorkspaceInviteRole>(inviteRoleOptions[0] || 'member');
  const [inviteExpiresAt, setInviteExpiresAt] = useState('');
  const [inviteOverrideText, setInviteOverrideText] = useState('');
  const [inviteFormError, setInviteFormError] = useState('');
  const [latestInviteLink, setLatestInviteLink] = useState('');
  const [copySuccess, setCopySuccess] = useState('');

  const [metadataError, setMetadataError] = useState('');

  const [switchError, setSwitchError] = useState('');
  const [founderTargetUserId, setFounderTargetUserId] = useState('');
  const [archiveConfirmed, setArchiveConfirmed] = useState(false);
  const [archiveError, setArchiveError] = useState('');

  const workspacesQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: workspacesApi.list,
  });
  const membersQuery = useQuery({
    queryKey: ['workspace-members', workspaceId],
    queryFn: () => workspacesApi.listMembers(workspaceId),
    enabled: Boolean(workspaceId) && canManageMembers,
  });
  const invitesQuery = useQuery({
    queryKey: ['workspace-invites', workspaceId],
    queryFn: () => workspacesApi.listInvites(workspaceId),
    enabled: Boolean(workspaceId) && canManageInvites,
  });

  const metadataMutation = useMutation({
    mutationFn: (payload: { name: string; slug: string }) =>
      workspacesApi.updateWorkspace(
        payload,
        workspaceId,
      ),
    onSuccess: (updatedWorkspace) => {
      updateStoredWorkspace(updatedWorkspace);
      setMetadataError('');
      setSuccessMessage('Workspace settings saved.');
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
    onError: (error: unknown) => {
      setMetadataError(getErrorMessage(error, 'Workspace settings update failed'));
    },
  });

  const memberCreateMutation = useMutation({
    mutationFn: async () => {
      const userId = memberUserId.trim();
      if (!userId) {
        throw new Error('User ID is required.');
      }
      return workspacesApi.createMember(
        {
          user_id: userId,
          role: memberRole,
          permissions_override: parsePermissionsOverrideInput(memberOverrideText, memberRole),
        },
        workspaceId,
      );
    },
    onSuccess: () => {
      setMemberUserId('');
      setMemberRole('member');
      setMemberOverrideText('');
      setMemberFormError('');
      setSuccessMessage('Workspace member added.');
      queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] });
    },
    onError: (error: unknown) => {
      setMemberFormError(getErrorMessage(error, 'Failed to add workspace member'));
    },
  });

  const memberUpdateMutation = useMutation({
    mutationFn: ({
      membershipId,
      role,
      status,
      permissions_override,
    }: {
      membershipId: string;
      role: WorkspaceMembershipRole;
      status: WorkspaceMembershipStatus;
      permissions_override?: WorkspacePermissions;
    }) => workspacesApi.updateMember(membershipId, { role, status, permissions_override }, workspaceId),
    onSuccess: () => {
      setSuccessMessage('Workspace member updated.');
      queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] });
    },
  });

  const memberRemoveMutation = useMutation({
    mutationFn: (membershipId: string) => workspacesApi.removeMember(membershipId, workspaceId),
    onSuccess: () => {
      setSuccessMessage('Workspace member removed.');
      queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] });
    },
  });

  const inviteCreateMutation = useMutation({
    mutationFn: async () =>
      workspacesApi.createInvite(
        {
          email: inviteEmail.trim(),
          role: inviteRole,
          expires_at: toIsoDateTime(inviteExpiresAt),
          permissions_override: parsePermissionsOverrideInput(inviteOverrideText, inviteRole),
        },
        workspaceId,
      ),
    onSuccess: (invite) => {
      setInviteEmail('');
      setInviteRole(getActorInviteRoles(actorRole)[0] || 'member');
      setInviteExpiresAt('');
      setInviteOverrideText('');
      setInviteFormError('');
      setLatestInviteLink(getInviteLink(invite.id));
      setCopySuccess('');
      setSuccessMessage('Workspace invite created.');
      queryClient.invalidateQueries({ queryKey: ['workspace-invites', workspaceId] });
    },
    onError: (error: unknown) => {
      setInviteFormError(getErrorMessage(error, 'Failed to create invite'));
    },
  });

  const inviteRevokeMutation = useMutation({
    mutationFn: (inviteId: string) => workspacesApi.revokeInvite(inviteId, workspaceId),
    onSuccess: () => {
      setSuccessMessage('Workspace invite revoked.');
      queryClient.invalidateQueries({ queryKey: ['workspace-invites', workspaceId] });
    },
  });

  const switchContextMutation = useMutation({
    mutationFn: (targetWorkspaceId: string) => authApi.switchContext({ workspace_id: targetWorkspaceId }),
    onSuccess: (response) => {
      storeAuthTokenResponse(response);
      window.location.assign(resolveAppPath('/workspace'));
    },
    onError: (error: unknown) => {
      setSwitchError(getErrorMessage(error, 'Failed to switch workspace context'));
    },
  });

  const founderTransferMutation = useMutation({
    mutationFn: (targetUserId: string) => workspacesApi.transferFounder(targetUserId, workspaceId),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] });
      setFounderTargetUserId('');
      setSuccessMessage('Founder ownership transferred.');
      const refreshed = await authApi.switchContext({ workspace_id: workspaceId });
      storeAuthTokenResponse(refreshed);
    },
    onError: (error: unknown) => {
      setArchiveError(getErrorMessage(error, 'Founder transfer failed'));
    },
  });

  const archiveMutation = useMutation({
    mutationFn: () => workspacesApi.archive(workspaceId),
    onSuccess: () => {
      clearStoredAuth();
      window.location.assign(resolveAppPath('/login'));
    },
    onError: (error: unknown) => {
      setArchiveError(getErrorMessage(error, 'Workspace archive failed'));
    },
  });

  const workspaceOptions = workspacesQuery.data || [];
  const members = membersQuery.data || [];
  const invites = invitesQuery.data || [];
  const founderTransferOptions = members.filter((member) => member.status === 'active' && member.role !== 'founder');

  const pageError = [workspacesQuery.error, membersQuery.error, invitesQuery.error]
    .filter(Boolean)
    .map((error) => getErrorMessage(error, 'Failed to load workspace administration data'))
    .join(' · ');

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Workspace Admin"
        description="Manage workspace settings, discover available workspaces, and operate members, invites, founder transfer, and archive from one settings surface."
        actions={
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ['workspaces'] });
              if (canManageMembers) queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] });
              if (canManageInvites) queryClient.invalidateQueries({ queryKey: ['workspace-invites', workspaceId] });
            }}
          >
            <RefreshCcw size={16} />
            <span>Refresh admin data</span>
          </button>
        }
      />

      {pageError && (
        <InlineAlert tone="danger" title="Workspace admin data did not load cleanly">
          {pageError}
        </InlineAlert>
      )}

      {successMessage && (
        <InlineAlert tone="success" title="Updated">
          {successMessage}
        </InlineAlert>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        <KeyMetric label="Workspace" value={workspace?.name || workspace?.slug || workspaceId || 'Unknown'} hint={workspace?.status || 'No workspace status'} />
        <KeyMetric label="Role" value={actorRole || 'unknown'} hint={`Membership status: ${workspaceMembership?.status || 'unknown'}`} />
        <KeyMetric label="Members" value={canManageMembers ? members.length : 'Restricted'} hint={canManageMembers ? 'Workspace membership records' : 'Founder/admin only'} />
        <KeyMetric
          label="Invites"
          value={canManageInvites ? invites.filter((invite) => invite.status === 'pending').length : 'Restricted'}
          hint="Pending workspace invites"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
        <GlassPanel title="Current context" subtitle="Workspace switch discoverability now comes from a real workspace list contract, not a manual workspace id entry field.">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="surface-soft space-y-3 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium text-slate-900">{workspace?.name || 'Unknown workspace'}</p>
                <StatusBadge tone={STATUS_TONE[workspace?.status || ''] || 'default'}>{workspace?.status || 'unknown'}</StatusBadge>
                {workspaceMembership?.role && <StatusBadge tone={ROLE_TONE[workspaceMembership.role] || 'default'}>{workspaceMembership.role}</StatusBadge>}
              </div>
              <p className="text-sm text-slate-500">{workspace?.slug || workspaceId}</p>
              <p className="text-sm text-slate-500">Tenant membership {tenantMembership?.role || 'unknown'} · {tenantMembership?.status || 'unknown'}</p>
              <p className="text-sm text-slate-500">Workspace membership {workspaceMembership?.status || 'unknown'}</p>
            </div>

            <WorkspaceSwitcherCard
              key={`workspace-switcher:${workspaceId || 'none'}`}
              workspaceId={workspaceId}
              workspaceOptions={workspaceOptions}
              switchPending={switchContextMutation.isPending}
              switchError={switchError}
              onSwitch={(targetWorkspaceId) => {
                setSwitchError('');
                switchContextMutation.mutate(targetWorkspaceId);
              }}
            />
          </div>

          <div className="space-y-3">
            <p className="text-sm font-medium text-slate-900">Granted workspace capabilities</p>
            <div className="flex flex-wrap gap-2">
              {grantedCapabilities.length > 0 ? (
                grantedCapabilities.map((capability) => <StatusBadge key={capability}>{WORKSPACE_CAPABILITY_LABELS[capability]}</StatusBadge>)
              ) : (
                <p className="text-sm text-slate-500">No explicit workspace capabilities are available in the current session.</p>
              )}
            </div>
          </div>
        </GlassPanel>

        <GlassPanel title="Workspace settings" subtitle="This closes the Phase 4 metadata gap under the existing workspace admin surface instead of inventing a separate console.">
          <div className="space-y-4">
            <WorkspaceMetadataCard
              key={`workspace-metadata:${workspaceId || 'none'}:${workspace?.updated_at || workspace?.name || ''}:${workspace?.slug || ''}`}
              workspace={workspace}
              canEditWorkspaceMetadata={canEditWorkspaceMetadata}
              metadataError={metadataError}
              metadataPending={metadataMutation.isPending}
              onSave={(payload) => {
                setMetadataError('');
                metadataMutation.mutate(payload);
              }}
            />
            <div className="surface-soft space-y-2 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                <Shield size={16} className="text-blue-600" />
                <span>Session flags</span>
              </div>
              <p className="text-sm text-slate-500">{user?.email || 'No email on the current account'} · can_create_workspace {user?.can_create_workspace ? 'enabled' : 'disabled'} · platform admin {user?.is_platform_admin ? 'enabled' : 'disabled'}</p>
            </div>
          </div>
        </GlassPanel>
      </div>

      {!canAccessAdminSurface && (
        <InlineAlert tone="warning" title="Workspace admin actions are not available in this session">
          Your current workspace membership is {actorRole || 'unknown'}. Member and guest roles can still see the active workspace context, but settings, members, invites, founder
          transfer, and archive actions remain gated by workspace capability.
        </InlineAlert>
      )}

      {canAccessAdminSurface && (
        <>
          <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
            <GlassPanel title="Members" subtitle="List, add, update, or remove workspace memberships. Founder and admin limits match the backend contract exactly.">
              <div className="space-y-4">
                {canManageMembers && (
                  <div className="surface-soft space-y-4 p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                      <UserPlus size={16} className="text-blue-600" />
                      <span>Add existing user by ID</span>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Field label="User ID" hint="POST /members is for already-registered users. Invite remains the primary onboarding path.">
                        <input className="field" value={memberUserId} onChange={(event) => setMemberUserId(event.target.value)} placeholder="user_123" />
                      </Field>
                      <Field label="Role">
                        <select className="field" value={memberRole} onChange={(event) => setMemberRole(event.target.value as WorkspaceMembershipRole)}>
                          {actorRole === 'founder' && <option value="admin">admin</option>}
                          <option value="member">member</option>
                          <option value="guest">guest</option>
                        </select>
                      </Field>
                    </div>
                    <Field label="Capability overrides" hint="Only known capability keys are allowed. Founder-only capabilities cannot be granted to non-founder roles.">
                      <textarea
                        className="field min-h-[112px] font-mono text-xs"
                        value={memberOverrideText}
                        onChange={(event) => setMemberOverrideText(event.target.value)}
                        placeholder='{"can_manage_api_keys": false}'
                      />
                    </Field>
                    {memberFormError && (
                      <InlineAlert tone="warning" title="Member create failed">
                        {memberFormError}
                      </InlineAlert>
                    )}
                    <div className="flex justify-end">
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={memberCreateMutation.isPending}
                        onClick={() => {
                          setMemberFormError('');
                          memberCreateMutation.mutate();
                        }}
                      >
                        <span>{memberCreateMutation.isPending ? 'Adding…' : 'Add member'}</span>
                      </button>
                    </div>
                  </div>
                )}

                <div className="space-y-4">
                  {members.length > 0 ? (
                    members.map((member) => (
                      <EditableMemberCard
                        key={`${member.id}:${member.updated_at}`}
                        actorRole={actorRole}
                        member={member}
                        savePending={memberUpdateMutation.isPending && memberUpdateMutation.variables?.membershipId === member.id}
                        removePending={memberRemoveMutation.isPending && memberRemoveMutation.variables === member.id}
                        onSave={(membershipId, payload) => memberUpdateMutation.mutate({ membershipId, ...payload })}
                        onRemove={(membershipId) => memberRemoveMutation.mutate(membershipId)}
                      />
                    ))
                  ) : (
                    <div className="empty-state min-h-[220px]">
                      <Users size={18} className="text-slate-400" />
                      <p className="text-sm text-slate-500">No workspace membership records are available yet.</p>
                    </div>
                  )}
                </div>
              </div>
            </GlassPanel>

            <GlassPanel title="Invites" subtitle="Create, review, and revoke workspace invites. Email delivery is still out of scope, so the accept link is surfaced directly.">
              <div className="space-y-4">
                {canManageInvites && (
                  <div className="surface-soft space-y-4 p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                      <MailPlus size={16} className="text-blue-600" />
                      <span>Create invite</span>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Field label="Email" required>
                        <input className="field" type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} placeholder="user@example.com" />
                      </Field>
                      <Field label="Role">
                        <select className="field" value={inviteRole} onChange={(event) => setInviteRole(event.target.value as WorkspaceInviteRole)}>
                          {inviteRoleOptions.map((role) => (
                            <option key={role} value={role}>
                              {role}
                            </option>
                          ))}
                        </select>
                      </Field>
                    </div>
                    <Field label="Expires at" hint="Optional. Leave blank to use the backend default expiry.">
                      <input className="field" type="datetime-local" value={inviteExpiresAt} onChange={(event) => setInviteExpiresAt(event.target.value)} />
                    </Field>
                    <Field label="Capability overrides" hint="Only known capability keys are allowed. Founder-only capabilities cannot be granted to non-founder roles.">
                      <textarea
                        className="field min-h-[112px] font-mono text-xs"
                        value={inviteOverrideText}
                        onChange={(event) => setInviteOverrideText(event.target.value)}
                        placeholder='{"can_manage_api_keys": false}'
                      />
                    </Field>
                    {inviteFormError && (
                      <InlineAlert tone="warning" title="Invite create failed">
                        {inviteFormError}
                      </InlineAlert>
                    )}
                    <div className="flex justify-end">
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={inviteCreateMutation.isPending || inviteRoleOptions.length === 0}
                        onClick={() => {
                          setInviteFormError('');
                          inviteCreateMutation.mutate();
                        }}
                      >
                        <span>{inviteCreateMutation.isPending ? 'Creating…' : 'Create invite'}</span>
                      </button>
                    </div>
                  </div>
                )}

                {latestInviteLink && (
                  <InlineAlert
                    tone="success"
                    title="Latest invite link"
                    action={
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={async () => {
                          try {
                            await copyToClipboard(latestInviteLink);
                            setCopySuccess('Invite link copied.');
                          } catch (error) {
                            setCopySuccess(getErrorMessage(error, 'Unable to copy invite link'));
                          }
                        }}
                      >
                        <Copy size={16} />
                        <span>Copy link</span>
                      </button>
                    }
                  >
                    <p className="break-all">{latestInviteLink}</p>
                    {copySuccess && <p className="mt-2">{copySuccess}</p>}
                  </InlineAlert>
                )}

                <div className="space-y-3">
                  {invites.length > 0 ? (
                    invites.map((invite) => (
                      <div key={invite.id} className="surface-soft space-y-3 p-4">
                        <div className="flex flex-wrap items-start justify-between gap-4">
                          <div className="space-y-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="font-medium text-slate-900">{invite.email}</p>
                              <StatusBadge tone={ROLE_TONE[invite.role] || 'default'}>{invite.role}</StatusBadge>
                              <StatusBadge tone={STATUS_TONE[invite.status] || 'default'}>{invite.status}</StatusBadge>
                            </div>
                            <p className="text-sm text-slate-500">Expires {formatDateTime(invite.expires_at)}</p>
                            <p className="text-xs text-slate-500">Created {formatDateTime(invite.created_at)}</p>
                          </div>
                          {canRevokeInvite(actorRole, invite) && (
                            <button
                              type="button"
                              className="btn-secondary"
                              disabled={inviteRevokeMutation.isPending && inviteRevokeMutation.variables === invite.id}
                              onClick={() => inviteRevokeMutation.mutate(invite.id)}
                            >
                              <span>{inviteRevokeMutation.isPending && inviteRevokeMutation.variables === invite.id ? 'Revoking…' : 'Revoke invite'}</span>
                            </button>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge>{invite.accepted_user_id ? `Accepted by ${invite.accepted_user_id}` : 'Not yet accepted'}</StatusBadge>
                          {invite.status === 'pending' && (
                            <button
                              type="button"
                              className="btn-secondary"
                              onClick={async () => {
                                try {
                                  await copyToClipboard(getInviteLink(invite.id));
                                  setCopySuccess('Invite link copied.');
                                } catch (error) {
                                  setCopySuccess(getErrorMessage(error, 'Unable to copy invite link'));
                                }
                              }}
                            >
                              <Copy size={16} />
                              <span>Copy accept link</span>
                            </button>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="empty-state min-h-[220px]">
                      <MailPlus size={18} className="text-slate-400" />
                      <p className="text-sm text-slate-500">No workspace invites have been issued yet.</p>
                    </div>
                  )}
                </div>
              </div>
            </GlassPanel>
          </div>

          <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
            <GlassPanel title="Founder transfer" subtitle="Only the current founder may transfer ownership. The previous founder is demoted to admin in the same transaction.">
              <div className="space-y-4">
                <Field label="Target member" hint="The target must already be an active member, admin, or guest in this workspace.">
                  <select className="field" value={founderTargetUserId} onChange={(event) => setFounderTargetUserId(event.target.value)} disabled={!canTransferFounder}>
                    <option value="">Select a member</option>
                    {founderTransferOptions.map((member) => (
                      <option key={member.id} value={member.user_id}>
                        {member.email || member.user_id} · {member.role}
                      </option>
                    ))}
                  </select>
                </Field>
                {!canTransferFounder && (
                  <InlineAlert tone="warning" title="Founder transfer is restricted">
                    This action is available only when the current workspace membership grants `can_transfer_founder`.
                  </InlineAlert>
                )}
                {archiveError && (
                  <InlineAlert tone="warning" title="Founder transfer or archive failed">
                    {archiveError}
                  </InlineAlert>
                )}
                <div className="flex justify-end">
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={!canTransferFounder || !founderTargetUserId || founderTransferMutation.isPending}
                    onClick={() => {
                      setArchiveError('');
                      founderTransferMutation.mutate(founderTargetUserId);
                    }}
                  >
                    <span>{founderTransferMutation.isPending ? 'Transferring…' : 'Transfer founder'}</span>
                  </button>
                </div>
              </div>
            </GlassPanel>

            <GlassPanel title="Archive workspace" subtitle="Archive replaces delete in Phase 4. Default workspaces cannot be archived.">
              <div className="space-y-4">
                <div className="surface-soft space-y-2 p-4">
                  <p className="font-medium text-slate-900">{workspace?.name || workspaceId}</p>
                  <p className="text-sm text-slate-500">
                    Status {workspace?.status || 'unknown'} · {workspace?.is_default ? 'Default workspace cannot be archived.' : 'Archive freezes the workspace and blocks active collaboration.'}
                  </p>
                </div>
                <label className="flex items-start gap-3 rounded-2xl border border-white/80 bg-white/70 p-4 text-sm text-slate-600">
                  <input
                    type="checkbox"
                    checked={archiveConfirmed}
                    onChange={(event) => setArchiveConfirmed(event.target.checked)}
                    className="mt-1"
                    disabled={!canArchiveWorkspace || Boolean(workspace?.is_default)}
                  />
                  <span>I understand that archive freezes this workspace and invalidates pending invite acceptance.</span>
                </label>
                <div className="flex justify-end">
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={!canArchiveWorkspace || Boolean(workspace?.is_default) || !archiveConfirmed || archiveMutation.isPending}
                    onClick={() => {
                      setArchiveError('');
                      archiveMutation.mutate();
                    }}
                  >
                    <span>{archiveMutation.isPending ? 'Archiving…' : 'Archive workspace'}</span>
                  </button>
                </div>
              </div>
            </GlassPanel>
          </div>
        </>
      )}
    </div>
  );
};
