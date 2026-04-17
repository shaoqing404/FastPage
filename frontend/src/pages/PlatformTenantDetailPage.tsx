import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';

import { GlassPanel, SectionToolbar, StatusBadge, Field, KeyMetric } from '../components/ui/workbench';
import { platformApi } from '../features/platform/api';
import { formatDateTime } from '../lib/utils';

export const PlatformTenantDetailPage: React.FC = () => {
  const { tenantId } = useParams<{ tenantId: string }>();
  const navigate = useNavigate();

  const tenantQuery = useQuery({
    queryKey: ['platform-tenant', tenantId],
    queryFn: () => platformApi.getTenant(tenantId!),
    enabled: !!tenantId,
  });

  const detail = tenantQuery.data;

  if (!tenantId) return null;

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Tenant Detail"
        description={detail ? detail.name : 'Loading…'}
      />

      <button type="button" className="btn-secondary" onClick={() => navigate('/platform/tenants')}>
        <ArrowLeft size={16} />
        <span>Back to tenants</span>
      </button>

      {tenantQuery.isLoading && <p className="text-sm text-slate-500">Loading tenant details…</p>}

      {detail && (
        <>
          <div className="grid gap-6 lg:grid-cols-3">
            <GlassPanel title="Tenant info">
              <div className="space-y-3 text-sm">
                <Field label="ID"><p className="font-mono text-xs text-slate-900">{detail.id}</p></Field>
                <Field label="Name"><p className="text-slate-900">{detail.name}</p></Field>
                <Field label="Status"><StatusBadge tone={detail.status === 'active' ? 'success' : 'default'}>{detail.status}</StatusBadge></Field>
                <Field label="Created"><p className="text-slate-900">{formatDateTime(detail.created_at)}</p></Field>
              </div>
            </GlassPanel>
            <KeyMetric label="Users" value={detail.user_count} />
            <KeyMetric label="Workspaces" value={detail.workspace_count} />
          </div>

          <GlassPanel title="Users" subtitle={`${detail.users.length} user(s) in this tenant`}>
            {detail.users.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">No users.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500">
                      <th className="px-4 py-3 font-medium">Username</th>
                      <th className="px-4 py-3 font-medium">Email</th>
                      <th className="px-4 py-3 font-medium">Role</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Joined</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.users.map((u) => (
                      <tr key={u.id} className="border-b border-slate-100">
                        <td className="px-4 py-3 font-medium text-slate-900">{u.username}</td>
                        <td className="px-4 py-3 text-slate-600">{u.email || '—'}</td>
                        <td className="px-4 py-3"><StatusBadge>{u.role}</StatusBadge></td>
                        <td className="px-4 py-3"><StatusBadge tone={u.status === 'active' ? 'success' : 'default'}>{u.status}</StatusBadge></td>
                        <td className="px-4 py-3 text-slate-500">{formatDateTime(u.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>

          <GlassPanel title="Workspaces" subtitle={`${detail.workspaces.length} workspace(s) in this tenant`}>
            {detail.workspaces.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">No workspaces.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500">
                      <th className="px-4 py-3 font-medium">Name</th>
                      <th className="px-4 py-3 font-medium">Slug</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Default</th>
                      <th className="px-4 py-3 font-medium">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.workspaces.map((ws) => (
                      <tr key={ws.id} className="border-b border-slate-100">
                        <td className="px-4 py-3 font-medium text-slate-900">{ws.name}</td>
                        <td className="px-4 py-3 font-mono text-xs text-slate-600">{ws.slug}</td>
                        <td className="px-4 py-3">
                          <StatusBadge tone={ws.status === 'active' ? 'success' : ws.status === 'archived' ? 'danger' : 'default'}>{ws.status}</StatusBadge>
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge tone={ws.is_default ? 'warning' : 'default'}>{ws.is_default ? 'Yes' : 'No'}</StatusBadge>
                        </td>
                        <td className="px-4 py-3 text-slate-500">{formatDateTime(ws.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>
        </>
      )}
    </div>
  );
};
