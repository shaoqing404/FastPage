import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Activity,
  BarChart3,
  BookCopy,
  Crown,
  KeyRound,
  Layers3,
  LogOut,
  MessageSquare,
  PlusCircle,
  Settings2,
  ShieldCheck,
  Sparkles,
  Users2,
} from 'lucide-react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { authApi } from '../../features/auth/api';
import { workspacesApi } from '../../features/workspaces/api';
import {
  clearStoredAuth,
  resolveAppPath,
  resolveStoredUser,
  resolveStoredWorkspace,
  resolveStoredWorkspaceMembership,
  storeAuthTokenResponse,
  subscribeToSessionChanges,
} from '../../lib/api/client';
import { getErrorMessage } from '../../lib/utils';
import { cn } from '../../lib/utils';

const BASE_NAV_ITEMS = [
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
  const [navFocused, setNavFocused] = useState(false);
  const hideTimerRef = useRef<number | null>(null);
  const [user, setUser] = useState(() => resolveStoredUser() || {});
  const [workspace, setWorkspace] = useState(() => resolveStoredWorkspace() || {});
  const [workspaceMembership, setWorkspaceMembership] = useState(() => resolveStoredWorkspaceMembership() || {});
  const [switchError, setSwitchError] = useState('');
  const workspaceId = typeof workspace.id === 'string' ? workspace.id : '';
  const workspaceLabel =
    typeof workspace.name === 'string' && workspace.name.trim().length > 0
      ? workspace.name.trim()
      : typeof workspace.slug === 'string' && workspace.slug.trim().length > 0
        ? workspace.slug.trim()
        : typeof user.workspace_id === 'string' && user.workspace_id.trim().length > 0
          ? user.workspace_id.trim()
          : 'Active workspace';
  const workspaceRole =
    typeof workspaceMembership.role === 'string' && workspaceMembership.role.trim().length > 0
      ? workspaceMembership.role.trim()
      : typeof user.workspace_membership_role === 'string' && user.workspace_membership_role.trim().length > 0
        ? user.workspace_membership_role.trim()
        : 'unknown';
  const workspaceStatus =
    typeof workspaceMembership.status === 'string' && workspaceMembership.status.trim().length > 0
      ? workspaceMembership.status.trim()
      : typeof workspace.status === 'string' && workspace.status.trim().length > 0
        ? workspace.status.trim()
        : 'unknown';
  const showAdminNav = workspaceMembership.permissions?.can_manage_members || workspaceMembership.permissions?.can_manage_invites || workspaceRole === 'founder';
  const isPlatformAdmin = user.is_platform_admin === true;
  const canCreateWorkspace = user.can_create_workspace === true || isPlatformAdmin;
  const navItems = useMemo(
    () => {
      const items = showAdminNav
        ? [...BASE_NAV_ITEMS, { to: '/workspace/admin', label: 'Admin', icon: Users2 }]
        : [...BASE_NAV_ITEMS];
      if (isPlatformAdmin) {
        items.push({ to: '/platform/users', label: 'Platform', icon: Crown });
      }
      return items;
    },
    [showAdminNav, isPlatformAdmin],
  );
  const isOverview = location.pathname === '/workspace' || location.pathname === '/overview' || location.pathname === '/';
  const availableWorkspacesQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: workspacesApi.list,
  });
  const switchContextMutation = useMutation({
    mutationFn: (nextWorkspaceId: string) => authApi.switchContext({ workspace_id: nextWorkspaceId }),
    onSuccess: (response) => {
      storeAuthTokenResponse(response);
      window.location.assign(resolveAppPath('/workspace'));
    },
    onError: (error: unknown) => {
      setSwitchError(getErrorMessage(error, 'Workspace switch failed'));
    },
  });
  const availableWorkspaces = availableWorkspacesQuery.data || [];

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  const scheduleHide = useCallback(() => {
    clearHideTimer();
    if (isOverview || navHovered || navFocused) return;
    hideTimerRef.current = window.setTimeout(() => {
      if (!navHovered && !navFocused) {
        setNavVisible(false);
      }
    }, 5000);
  }, [clearHideTimer, isOverview, navFocused, navHovered]);

  useEffect(() => {
    setNavVisible(true);
    scheduleHide();
    return clearHideTimer;
  }, [clearHideTimer, location.pathname, scheduleHide]);

  useEffect(() => {
    if (isOverview) return;
    const handleMouseMove = (event: MouseEvent) => {
      if (event.clientY < 88) {
        setNavVisible(true);
        clearHideTimer();
        return;
      }
      if (event.clientY > 180 && !navHovered && !navFocused) {
        scheduleHide();
      }
    };
    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, [clearHideTimer, isOverview, navFocused, navHovered, scheduleHide]);

  useEffect(() => {
    if (navVisible) {
      scheduleHide();
    } else {
      clearHideTimer();
    }
  }, [clearHideTimer, navVisible, scheduleHide]);

  useEffect(() => clearHideTimer, [clearHideTimer]);

  useEffect(() => {
    return subscribeToSessionChanges(() => {
      setUser(resolveStoredUser() || {});
      setWorkspace(resolveStoredWorkspace() || {});
      setWorkspaceMembership(resolveStoredWorkspaceMembership() || {});
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    authApi.getContext().then((response) => {
      if (!cancelled) {
        storeAuthTokenResponse(response);
      }
    }).catch(() => {
      // Silent: 401 redirect is handled by the axios interceptor.
    });
    return () => { cancelled = true; };
  }, []);

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch (error) {
      console.error('Logout failed', error);
    } finally {
      clearStoredAuth();
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
            onMouseEnter={() => {
              setNavHovered(true);
              setNavVisible(true);
              clearHideTimer();
            }}
            onMouseLeave={() => {
              setNavHovered(false);
              scheduleHide();
            }}
            onFocusCapture={() => {
              setNavFocused(true);
              setNavVisible(true);
              clearHideTimer();
            }}
            onBlurCapture={(event) => {
              if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
              setNavFocused(false);
              scheduleHide();
            }}
          >
            <div className="mx-auto flex max-w-[1440px] items-center gap-4 rounded-full px-4 py-3 glass-nav">
              <div className="flex shrink-0 items-center gap-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-full bg-white/85 text-blue-600 shadow-sm">
                  <BarChart3 size={20} />
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.22em] text-slate-500">PageIndex</p>
                  <p className="text-sm font-semibold tracking-[-0.02em] text-slate-900">Workspace Console</p>
                </div>
              </div>

              <nav className="segmented min-w-0 flex-1 overflow-x-auto">
                {navItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <NavLink key={item.to} to={item.to} className={({ isActive }) => cn('nav-pill', isActive && 'nav-pill-active')}>
                      <Icon size={16} />
                      <span>{item.label}</span>
                    </NavLink>
                  );
                })}
              </nav>

              <div className="ml-auto flex min-w-0 shrink items-center gap-3">
                <NavLink to="/chat" className={({ isActive }) => cn('nav-pill', isActive && 'nav-pill-active')}>
                  <MessageSquare size={16} />
                  <span>Skill Chat</span>
                </NavLink>
                <div className="hidden min-w-0 max-w-[240px] shrink rounded-full border border-white/75 bg-white/75 px-4 py-2 lg:block">
                  <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500">Workspace</p>
                  {availableWorkspaces.length > 0 ? (
                    <select
                      className="w-full truncate bg-transparent text-sm font-semibold text-slate-900 outline-none"
                      value={workspaceId}
                      disabled={switchContextMutation.isPending}
                      onChange={(event) => {
                        const nextWorkspaceId = event.target.value;
                        if (!nextWorkspaceId || nextWorkspaceId === workspaceId) return;
                        setSwitchError('');
                        switchContextMutation.mutate(nextWorkspaceId);
                      }}
                    >
                      {availableWorkspaces.map((item) => (
                        <option key={item.id} value={item.id} disabled={item.status !== 'active'}>
                          {item.name} · {item.membership_role}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <p className="max-w-[180px] truncate text-sm font-semibold text-slate-900">{workspaceLabel}</p>
                  )}
                  <p className="truncate text-[11px] uppercase tracking-[0.18em] text-slate-500">
                    {workspaceRole} · {workspaceStatus}
                  </p>
                  {switchError && <p className="truncate text-[11px] text-red-600">{switchError}</p>}
                  {canCreateWorkspace && (
                    <NavLink to="/workspace/create" className="mt-1 flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:text-blue-700">
                      <PlusCircle size={12} />
                      <span>New workspace</span>
                    </NavLink>
                  )}
                </div>
                <div className="min-w-0 max-w-[180px] shrink rounded-full border border-white/75 bg-white/75 px-4 py-2">
                  <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500">Operator</p>
                  <p className="truncate text-sm font-semibold text-slate-900">{user.username || 'admin'}</p>
                  {user.can_create_workspace && <p className="truncate text-[11px] uppercase tracking-[0.18em] text-slate-500">Workspace create enabled</p>}
                  {!user.can_create_workspace && showAdminNav && <p className="truncate text-[11px] uppercase tracking-[0.18em] text-slate-500">Admin surface enabled</p>}
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
          onMouseEnter={() => {
            setNavVisible(true);
            clearHideTimer();
          }}
          onFocus={() => {
            setNavVisible(true);
            clearHideTimer();
          }}
          aria-label="Reveal navigation"
        />
      )}

      <main className="page-container">
        <Outlet />
      </main>
    </div>
  );
};
