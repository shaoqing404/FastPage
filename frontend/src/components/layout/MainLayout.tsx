import React, { useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Activity,
  BarChart3,
  BookCopy,
  KeyRound,
  Layers3,
  LogOut,
  MessageSquare,
  Settings2,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { authApi } from '../../features/auth/api';
import { cn } from '../../lib/utils';

const NAV_ITEMS = [
  { to: '/workspace', label: 'Workspace', icon: Sparkles },
  { to: '/knowledge-bases', label: 'Knowledge Base', icon: Layers3 },
  { to: '/compliance-checks', label: 'Compliance', icon: ShieldCheck },
  { to: '/documents', label: 'Documents', icon: BookCopy },
  { to: '/skills', label: 'Skills', icon: Settings2 },
  { to: '/runs', label: 'Runs', icon: Activity },
  { to: '/providers', label: 'Providers', icon: KeyRound },
] as const;

export const MainLayout: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [navVisible, setNavVisible] = useState(true);
  const [navHovered, setNavHovered] = useState(false);
  const user = useMemo(() => JSON.parse(localStorage.getItem('user') || '{}'), []);
  const workspaceLabel =
    typeof user.workspace_id === 'string' && user.workspace_id.trim().length > 0 ? user.workspace_id.trim() : 'Active workspace';
  const isOverview = location.pathname === '/workspace' || location.pathname === '/overview' || location.pathname === '/';

  useEffect(() => {
    setNavVisible(true);
    if (isOverview) return;
    const timer = window.setTimeout(() => {
      if (!navHovered) setNavVisible(false);
    }, 2200);
    return () => window.clearTimeout(timer);
  }, [isOverview, location.pathname, navHovered]);

  useEffect(() => {
    if (isOverview) return;
    const handleMouseMove = (event: MouseEvent) => {
      if (event.clientY < 84) {
        setNavVisible(true);
        return;
      }
      if (event.clientY > 180 && !navHovered) {
        setNavVisible(false);
      }
    };
    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, [isOverview, navHovered]);

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch (error) {
      console.error('Logout failed', error);
    } finally {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      navigate('/login');
    }
  };

  return (
    <div className="app-shell">
      <AnimatePresence>
        {(navVisible || isOverview) && (
          <motion.header
            initial={{ y: -24, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -24, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 280, damping: 26 }}
            className="fixed inset-x-0 top-5 z-40 px-6"
            onMouseEnter={() => setNavHovered(true)}
            onMouseLeave={() => setNavHovered(false)}
          >
            <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-6 rounded-full px-4 py-3 glass-nav">
              <div className="flex items-center gap-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-full bg-white/85 text-blue-600 shadow-sm">
                  <BarChart3 size={20} />
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.22em] text-slate-500">PageIndex</p>
                  <p className="text-sm font-semibold tracking-[-0.02em] text-slate-900">Workspace Console</p>
                </div>
              </div>

              <nav className="segmented">
                {NAV_ITEMS.map((item) => {
                  const Icon = item.icon;
                  return (
                    <NavLink key={item.to} to={item.to} className={({ isActive }) => cn('nav-pill', isActive && 'nav-pill-active')}>
                      <Icon size={16} />
                      <span>{item.label}</span>
                    </NavLink>
                  );
                })}
              </nav>

              <div className="flex items-center gap-3">
                <NavLink to="/chat" className={({ isActive }) => cn('nav-pill', isActive && 'nav-pill-active')}>
                  <MessageSquare size={16} />
                  <span>Skill Chat</span>
                </NavLink>
                <div className="hidden rounded-full border border-white/75 bg-white/75 px-4 py-2 lg:block">
                  <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500">Workspace</p>
                  <p className="max-w-[180px] truncate text-sm font-semibold text-slate-900">{workspaceLabel}</p>
                </div>
                <div className="rounded-full border border-white/75 bg-white/75 px-4 py-2">
                  <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500">Operator</p>
                  <p className="text-sm font-semibold text-slate-900">{user.username || 'admin'}</p>
                </div>
                <button type="button" className="icon-button" onClick={handleLogout} title="Sign out">
                  <LogOut size={16} />
                </button>
              </div>
            </div>
          </motion.header>
        )}
      </AnimatePresence>

      {!navVisible && !isOverview && (
        <button
          type="button"
          className="fixed left-1/2 top-4 z-30 h-2.5 w-28 -translate-x-1/2 rounded-full bg-white/75 shadow-[0_18px_36px_rgba(148,163,184,0.28)] backdrop-blur-xl"
          onMouseEnter={() => setNavVisible(true)}
          aria-label="Reveal navigation"
        />
      )}

      <main className="page-container">
        <Outlet />
      </main>
    </div>
  );
};
