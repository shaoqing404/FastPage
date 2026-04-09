import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Lock, ShieldCheck, User } from 'lucide-react';

import { authApi } from '../features/auth/api';
import { getErrorMessage } from '../lib/utils';

export const LoginPage: React.FC = () => {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('changeme');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError('');

    try {
      const response = await authApi.login({ username, password });
      localStorage.setItem('token', response.access_token);
      localStorage.setItem('user', JSON.stringify(response.user));
      navigate('/overview');
    } catch (error: unknown) {
      setError(getErrorMessage(error, 'Authentication failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(255,255,255,0.95),_transparent_26%),radial-gradient(circle_at_bottom_right,_rgba(191,219,254,0.82),_transparent_28%),linear-gradient(180deg,_#f8fafc_0%,_#e9eef5_100%)] px-6">
      <div className="absolute left-12 top-12 h-72 w-72 rounded-full bg-white/70 blur-3xl" />
      <div className="absolute bottom-16 right-12 h-80 w-80 rounded-full bg-blue-200/55 blur-3xl" />

      <div className="relative grid w-full max-w-[1180px] grid-cols-[1.15fr_0.85fr] gap-8">
        <div className="glass-panel px-10 py-12">
          <div className="space-y-8">
            <div className="inline-flex h-14 w-14 items-center justify-center rounded-[18px] bg-white/88 text-blue-600 shadow-sm">
              <ShieldCheck size={26} />
            </div>
            <div className="space-y-4">
              <p className="text-xs font-medium uppercase tracking-[0.28em] text-slate-500">PageIndex</p>
              <h1 className="max-w-2xl text-5xl font-semibold tracking-[-0.05em] text-slate-950">
                Knowledge operations for structured documents, sessions, and model execution.
              </h1>
              <p className="max-w-2xl text-base leading-7 text-slate-600">
                Sign in to a workbench designed for professional knowledge flows, not a generic admin dashboard. Documents, skills, providers,
                and chat context stay connected in one surface.
              </p>
            </div>

            <div className="grid grid-cols-3 gap-4">
              <Feature label="Session-aware chat" hint="Persistent conversation continuity for document work." />
              <Feature label="Provider control" hint="Tenant-scoped model provider profiles and API keys." />
              <Feature label="Readable diagnostics" hint="Runs, citations, and pipeline state in one place." />
            </div>
          </div>
        </div>

        <div className="glass-panel">
          <div className="glass-panel-header">
            <div>
              <h2 className="panel-title">Sign in</h2>
              <p className="panel-subtitle">Use your tenant credentials to enter the workbench.</p>
            </div>
          </div>
          <form onSubmit={handleLogin} className="glass-panel-body space-y-5">
            <label className="field-stack">
              <span className="field-label">Username</span>
              <div className="relative">
                <User className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                <input
                  type="text"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  className="field pl-11"
                  placeholder="admin"
                  required
                />
              </div>
            </label>

            <label className="field-stack">
              <span className="field-label">Password</span>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="field pl-11"
                  placeholder="changeme"
                  required
                />
              </div>
            </label>

            {error && (
              <div className="inline-alert inline-alert-danger">
                <div>
                  <p className="font-medium text-slate-900">Unable to sign in</p>
                  <p className="text-sm text-slate-700">{error}</p>
                </div>
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-3.5">
              <span>{loading ? 'Signing in…' : 'Enter workbench'}</span>
              {!loading && <ArrowRight size={16} />}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

const Feature = ({ label, hint }: { label: string; hint: string }) => (
  <div className="rounded-[24px] border border-white/80 bg-white/58 p-4">
    <p className="text-sm font-medium text-slate-900">{label}</p>
    <p className="mt-2 text-sm leading-6 text-slate-500">{hint}</p>
  </div>
);
