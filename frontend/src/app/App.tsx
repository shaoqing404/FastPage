import React from 'react';
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { MainLayout } from '../components/layout/MainLayout';
import { ActivityPage } from '../pages/ActivityPage';
import { ChangePasswordPage } from '../pages/ChangePasswordPage';
import { ComplianceChecksPage } from '../pages/ComplianceChecksPage';
import { ControlPlanePage } from '../pages/ControlPlanePage';
import { DocumentsPage } from '../pages/DocumentsPage';
import { KnowledgeBaseDetailPage } from '../pages/KnowledgeBaseDetailPage';
import { KnowledgeBasesPage } from '../pages/KnowledgeBasesPage';
import { LoginPage } from '../pages/LoginPage';
import { OverviewPage } from '../pages/OverviewPage';
import { PlatformTenantDetailPage } from '../pages/PlatformTenantDetailPage';
import { PlatformTenantsPage } from '../pages/PlatformTenantsPage';
import { PlatformUserDetailPage } from '../pages/PlatformUserDetailPage';
import { PlatformUsersPage } from '../pages/PlatformUsersPage';
import { PlatformWorkspaceDetailPage } from '../pages/PlatformWorkspaceDetailPage';
import { PlatformWorkspacesPage } from '../pages/PlatformWorkspacesPage';
import { ProviderDocsPage } from '../pages/ProviderDocsPage';
import { SkillChatPage } from '../pages/SkillChatPage';
import { SkillsPage } from '../pages/SkillsPage';
import { WorkspaceAdminPage } from '../pages/WorkspaceAdminPage';
import { WorkspaceCreatePage } from '../pages/WorkspaceCreatePage';
import { WorkspaceInviteAcceptPage } from '../pages/WorkspaceInviteAcceptPage';
import { FastSearchPage } from '../pages/FastSearchPage';
import { resolveStoredUser } from '../lib/api/client';

const BASENAME = (import.meta.env.BASE_URL || '/').replace(/\/$/, '') || '/';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;

  // Force password change if must_change_password is set
  const user = resolveStoredUser();
  if (user?.must_change_password === true) {
    return <Navigate to="/change-password" replace />;
  }

  return <>{children}</>;
};

const ChangePasswordRoute = ({ children }: { children: React.ReactNode }) => {
  // Change password page only requires a token, not the must_change_password check
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
};

const PlatformAdminRoute = ({ children }: { children: React.ReactNode }) => {
  const user = resolveStoredUser();
  if (user?.is_platform_admin !== true) return <Navigate to="/workspace" replace />;
  return <>{children}</>;
};

const LegacySkillChatRedirect = () => {
  const { skillId = '' } = useParams();
  return <Navigate to={skillId ? `/skills/${skillId}` : '/skills'} replace />;
};

export const App: React.FC = () => (
  <QueryClientProvider client={queryClient}>
    <BrowserRouter basename={BASENAME === '/' ? undefined : BASENAME}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/workspace-invites/:inviteId/accept" element={<WorkspaceInviteAcceptPage />} />
        <Route
          path="/change-password"
          element={
            <ChangePasswordRoute>
              <ChangePasswordPage />
            </ChangePasswordRoute>
          }
        />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <MainLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/workspace" replace />} />
          <Route path="workspace" element={<OverviewPage />} />
          <Route path="workspace/admin" element={<WorkspaceAdminPage />} />
          <Route path="workspace/create" element={<WorkspaceCreatePage />} />
          <Route path="overview" element={<Navigate to="/workspace" replace />} />
          <Route path="knowledge-bases" element={<KnowledgeBasesPage />} />
          <Route path="knowledge-bases/:kbId" element={<KnowledgeBaseDetailPage />} />
          <Route path="compliance-checks" element={<ComplianceChecksPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="skills" element={<SkillsPage />} />
          <Route path="skills/:skillId" element={<SkillChatPage />} />
          <Route path="search" element={<FastSearchPage />} />
          <Route path="chat" element={<Navigate to="/skills" replace />} />
          <Route path="chat/skills/:skillId" element={<LegacySkillChatRedirect />} />
          <Route path="runs" element={<ActivityPage />} />
          <Route path="activity" element={<Navigate to="/runs" replace />} />
          <Route path="providers" element={<ControlPlanePage />} />
          <Route path="providers/docs" element={<ProviderDocsPage />} />
          <Route path="control-plane" element={<Navigate to="/providers" replace />} />
          <Route path="metrics" element={<Navigate to="/runs" replace />} />
          <Route path="platform" element={<PlatformAdminRoute><Navigate to="/platform/users" replace /></PlatformAdminRoute>} />
          <Route path="platform/users" element={<PlatformAdminRoute><PlatformUsersPage /></PlatformAdminRoute>} />
          <Route path="platform/users/:userId" element={<PlatformAdminRoute><PlatformUserDetailPage /></PlatformAdminRoute>} />
          <Route path="platform/workspaces" element={<PlatformAdminRoute><PlatformWorkspacesPage /></PlatformAdminRoute>} />
          <Route path="platform/workspaces/:workspaceId" element={<PlatformAdminRoute><PlatformWorkspaceDetailPage /></PlatformAdminRoute>} />
          <Route path="platform/tenants" element={<PlatformAdminRoute><PlatformTenantsPage /></PlatformAdminRoute>} />
          <Route path="platform/tenants/:tenantId" element={<PlatformAdminRoute><PlatformTenantDetailPage /></PlatformAdminRoute>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </QueryClientProvider>
);
