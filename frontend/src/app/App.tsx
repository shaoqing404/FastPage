import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { MainLayout } from '../components/layout/MainLayout';
import { ActivityPage } from '../pages/ActivityPage';
import { ChatPage } from '../pages/ChatPage';
import { ControlPlanePage } from '../pages/ControlPlanePage';
import { DocumentsPage } from '../pages/DocumentsPage';
import { LoginPage } from '../pages/LoginPage';
import { OverviewPage } from '../pages/OverviewPage';
import { SkillChatPage } from '../pages/SkillChatPage';
import { SkillsPage } from '../pages/SkillsPage';

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
  return <>{children}</>;
};

export const App: React.FC = () => (
  <QueryClientProvider client={queryClient}>
    <BrowserRouter basename={BASENAME === '/' ? undefined : BASENAME}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <MainLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/overview" replace />} />
          <Route path="overview" element={<OverviewPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="skills" element={<SkillsPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="chat/skills/:skillId" element={<SkillChatPage />} />
          <Route path="control-plane" element={<ControlPlanePage />} />
          <Route path="activity" element={<ActivityPage />} />
          <Route path="metrics" element={<Navigate to="/activity" replace />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </QueryClientProvider>
);
