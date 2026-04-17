import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { GlassPanel, SectionToolbar, StatusBadge, EmptyState } from '../components/ui/workbench';
import { platformApi } from '../features/platform/api';
import { formatDateTime } from '../lib/utils';

export const PlatformUsersPage: React.FC = () => {
  const navigate = useNavigate();
  const usersQuery = useQuery({
    queryKey: ['platform-users'],
    queryFn: platformApi.listUsers,
  });

  const users = usersQuery.data || [];

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Platform Users"
        description="All registered users across all tenants. Click a row to view details."
      />

      <GlassPanel>
        {usersQuery.isLoading ? (
          <p className="py-12 text-center text-sm text-slate-500">Loading users…</p>
        ) : users.length === 0 ? (
          <EmptyState title="No users found" description="Platform user records will appear here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3 font-medium">Username</th>
                  <th className="px-4 py-3 font-medium">Email</th>
                  <th className="px-4 py-3 font-medium">Active</th>
                  <th className="px-4 py-3 font-medium">Workspace Create</th>
                  <th className="px-4 py-3 font-medium">Platform Admin</th>
                  <th className="px-4 py-3 font-medium">Tenants</th>
                  <th className="px-4 py-3 font-medium">Workspaces</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr
                    key={user.id}
                    className="cursor-pointer border-b border-slate-100 transition-colors hover:bg-white/60"
                    onClick={() => navigate(`/platform/users/${user.id}`)}
                  >
                    <td className="px-4 py-3 font-medium text-slate-900">{user.username}</td>
                    <td className="px-4 py-3 text-slate-600">{user.email || '—'}</td>
                    <td className="px-4 py-3">
                      <StatusBadge tone={user.is_active ? 'success' : 'danger'}>{user.is_active ? 'Yes' : 'No'}</StatusBadge>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge tone={user.can_create_workspace ? 'success' : 'default'}>{user.can_create_workspace ? 'Yes' : 'No'}</StatusBadge>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge tone={user.is_platform_admin ? 'warning' : 'default'}>{user.is_platform_admin ? 'Yes' : 'No'}</StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{user.tenant_membership_count}</td>
                    <td className="px-4 py-3 text-slate-600">{user.workspace_membership_count}</td>
                    <td className="px-4 py-3 text-slate-500">{formatDateTime(user.created_at)}</td>
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
