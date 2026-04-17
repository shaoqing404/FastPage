import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { GlassPanel, SectionToolbar, StatusBadge, EmptyState } from '../components/ui/workbench';
import { platformApi } from '../features/platform/api';
import { formatDateTime } from '../lib/utils';

export const PlatformTenantsPage: React.FC = () => {
  const navigate = useNavigate();
  const tenantsQuery = useQuery({
    queryKey: ['platform-tenants'],
    queryFn: platformApi.listTenants,
  });

  const tenants = tenantsQuery.data || [];

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Platform Tenants"
        description="All tenants in the system. Click a row to view details."
      />

      <GlassPanel>
        {tenantsQuery.isLoading ? (
          <p className="py-12 text-center text-sm text-slate-500">Loading tenants…</p>
        ) : tenants.length === 0 ? (
          <EmptyState title="No tenants found" description="Platform tenant records will appear here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Users</th>
                  <th className="px-4 py-3 font-medium">Workspaces</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map((tenant) => (
                  <tr
                    key={tenant.id}
                    className="cursor-pointer border-b border-slate-100 transition-colors hover:bg-white/60"
                    onClick={() => navigate(`/platform/tenants/${tenant.id}`)}
                  >
                    <td className="px-4 py-3 font-medium text-slate-900">{tenant.name}</td>
                    <td className="px-4 py-3">
                      <StatusBadge tone={tenant.status === 'active' ? 'success' : 'default'}>{tenant.status}</StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{tenant.user_count}</td>
                    <td className="px-4 py-3 text-slate-600">{tenant.workspace_count}</td>
                    <td className="px-4 py-3 text-slate-500">{formatDateTime(tenant.created_at)}</td>
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
