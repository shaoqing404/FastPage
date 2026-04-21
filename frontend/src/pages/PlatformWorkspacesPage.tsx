import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { GlassPanel, SectionToolbar, StatusBadge, EmptyState } from '../components/ui/workbench';
import { platformApi } from '../features/platform/api';
import { formatDateTime } from '../lib/utils';

export const PlatformWorkspacesPage: React.FC = () => {
  const navigate = useNavigate();
  const workspacesQuery = useQuery({
    queryKey: ['platform-workspaces'],
    queryFn: platformApi.listWorkspaces,
  });

  const workspaces = workspacesQuery.data || [];

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Platform Workspaces"
        description="All workspaces across all tenants. Click a row to view details."
      />

      <GlassPanel>
        {workspacesQuery.isLoading ? (
          <p className="py-12 text-center text-sm text-slate-500">Loading workspaces…</p>
        ) : workspaces.length === 0 ? (
          <EmptyState title="No workspaces found" description="Platform workspace records will appear here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Slug</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Tenant</th>
                  <th className="px-4 py-3 font-medium">Founder</th>
                  <th className="px-4 py-3 font-medium">Members</th>
                  <th className="px-4 py-3 font-medium">Active</th>
                  <th className="px-4 py-3 font-medium">Default</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {workspaces.map((ws) => (
                  <tr
                    key={ws.id}
                    className="cursor-pointer border-b border-slate-100 transition-colors hover:bg-white/60"
                    onClick={() => navigate(`/platform/workspaces/${ws.id}`)}
                  >
                    <td className="px-4 py-3 font-medium text-slate-900">{ws.name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-600">{ws.slug}</td>
                    <td className="px-4 py-3">
                      <StatusBadge tone={ws.status === 'active' ? 'success' : ws.status === 'archived' ? 'danger' : 'default'}>{ws.status}</StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{ws.tenant_name}</td>
                    <td className="px-4 py-3 text-slate-600">{ws.founder_username || ws.founder_email || '—'}</td>
                    <td className="px-4 py-3 text-slate-600">{ws.member_count}</td>
                    <td className="px-4 py-3 text-slate-600">{ws.active_member_count}</td>
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
    </div>
  );
};
