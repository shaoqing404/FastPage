import React, { useEffect, useState } from 'react';
import { CheckCircle2, Loader2, LogIn, MailCheck, UserPlus } from 'lucide-react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { GlassPanel, InlineAlert, Field } from '../components/ui/workbench';
import { workspacesApi } from '../features/workspaces/api';
import { resolveAppPath, storeInviteAcceptResponse, storeClaimResponse } from '../lib/api/client';
import { getErrorMessage } from '../lib/utils';
import type { InvitePreviewResponse } from '../types';

type PageMode = 'loading' | 'preview' | 'claiming' | 'accepting' | 'accepted' | 'error';

export const WorkspaceInviteAcceptPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { inviteId } = useParams<{ inviteId: string }>();

  const [mode, setMode] = useState<PageMode>('loading');
  const [preview, setPreview] = useState<InvitePreviewResponse | null>(null);
  const [error, setError] = useState('');

  // Claim form state
  const [claimUsername, setClaimUsername] = useState('');
  const [claimPassword, setClaimPassword] = useState('');
  const [claimConfirm, setClaimConfirm] = useState('');
  const [claimPending, setClaimPending] = useState(false);

  const missingInviteId = !inviteId;
  const hasToken = Boolean(localStorage.getItem('token'));

  // On mount: if user has token → auto-accept; else → fetch preview
  useEffect(() => {
    if (!inviteId) return;

    let cancelled = false;

    if (hasToken) {
      // Authenticated user → auto-accept flow (existing behavior)
      setMode('accepting');
      const acceptInvite = async () => {
        try {
          const response = await workspacesApi.acceptInvite(inviteId);
          if (cancelled) return;
          storeInviteAcceptResponse(response);
          setMode('accepted');
          window.location.assign(resolveAppPath('/workspace/admin'));
        } catch (nextError) {
          if (cancelled) return;
          setMode('error');
          setError(getErrorMessage(nextError, 'Workspace invite acceptance failed.'));
        }
      };
      acceptInvite();
    } else {
      // No token → fetch preview for claim form
      const loadPreview = async () => {
        try {
          const data = await workspacesApi.previewInvite(inviteId);
          if (cancelled) return;
          setPreview(data);
          if (data.valid) {
            // Pre-fill username from email
            const emailPrefix = data.email_masked.split('@')[0]?.replace(/\*/g, '') || '';
            setClaimUsername(emailPrefix.length > 1 ? emailPrefix : '');
            setMode('preview');
          } else {
            setMode('error');
            setError('This invite is no longer valid. It may have expired, been revoked, or already accepted.');
          }
        } catch (nextError) {
          if (cancelled) return;
          setMode('error');
          setError(getErrorMessage(nextError, 'Failed to load invite details.'));
        }
      };
      loadPreview();
    }

    return () => { cancelled = true; };
  }, [inviteId, hasToken]);

  const handleClaim = async () => {
    if (!inviteId) return;
    if (claimPassword.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (claimPassword !== claimConfirm) {
      setError('Passwords do not match.');
      return;
    }

    setError('');
    setClaimPending(true);
    setMode('claiming');

    try {
      const response = await workspacesApi.claimInvite(inviteId, {
        password: claimPassword,
        username: claimUsername.trim() || undefined,
      });
      storeClaimResponse(response);
      setMode('accepted');
      window.location.assign(resolveAppPath('/workspace'));
    } catch (nextError) {
      setMode('preview');
      setClaimPending(false);
      setError(getErrorMessage(nextError, 'Failed to claim invite.'));
    }
  };

  const handleGoLogin = () => {
    navigate(`/login?redirect=${encodeURIComponent(location.pathname + location.search)}`, { replace: true });
  };

  // --- Render ---
  const renderIcon = () => {
    if (mode === 'accepted') return <CheckCircle2 size={26} />;
    if (mode === 'accepting' || mode === 'claiming' || mode === 'loading') return <Loader2 size={26} className="animate-spin" />;
    if (mode === 'error') return <MailCheck size={26} />;
    return <UserPlus size={26} />;
  };

  const renderTitle = () => {
    if (missingInviteId) return 'Invite link is incomplete';
    if (mode === 'loading') return 'Loading invite…';
    if (mode === 'accepting' || mode === 'claiming') return 'Processing…';
    if (mode === 'accepted') return 'Welcome! Redirecting to workspace…';
    if (mode === 'error') return 'Invite could not be processed';
    if (preview) return `Join ${preview.workspace_name}`;
    return 'Workspace Invite';
  };

  const renderSubtitle = () => {
    if (mode === 'preview' && preview) {
      return `${preview.inviter_username} invited ${preview.email_masked} to join as ${preview.role}.`;
    }
    if (mode === 'accepting') return 'Accepting invite with your current session…';
    if (mode === 'accepted') return 'Your workspace context is being set up.';
    if (mode === 'error') return 'Check the error details below for more information.';
    return '';
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(255,255,255,0.95),_transparent_26%),radial-gradient(circle_at_bottom_right,_rgba(191,219,254,0.82),_transparent_28%),linear-gradient(180deg,_#f8fafc_0%,_#e9eef5_100%)] px-6">
      <div className="absolute left-12 top-12 h-72 w-72 rounded-full bg-white/70 blur-3xl" />
      <div className="absolute bottom-16 right-12 h-80 w-80 rounded-full bg-blue-200/55 blur-3xl" />

      <GlassPanel className="relative w-full max-w-[620px]" bodyClassName="space-y-6">
        <div className="space-y-3">
          <div className="inline-flex h-14 w-14 items-center justify-center rounded-[18px] bg-white/88 text-blue-600 shadow-sm">
            {renderIcon()}
          </div>
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-[0.28em] text-slate-500">Workspace Invite</p>
            <h1 className="text-4xl font-semibold tracking-[-0.05em] text-slate-950">{renderTitle()}</h1>
            {renderSubtitle() && <p className="text-base leading-7 text-slate-600">{renderSubtitle()}</p>}
          </div>
        </div>

        {/* Claim form — shown when user has no token and invite is valid */}
        {mode === 'preview' && preview && (
          <div className="space-y-5">
            <div className="rounded-xl border border-blue-100 bg-blue-50/60 p-4 space-y-1">
              <p className="text-sm font-medium text-blue-900">🆕 First time here? Set up your account</p>
              <p className="text-xs text-blue-700">Create a username and password to join the workspace immediately.</p>
            </div>

            <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); handleClaim(); }}>
              <Field label="Username" hint="You can change this later.">
                <input
                  id="claim-username"
                  className="field"
                  type="text"
                  value={claimUsername}
                  onChange={(e) => setClaimUsername(e.target.value)}
                  placeholder="your-username"
                  autoFocus
                />
              </Field>
              <Field label="Password" hint="At least 8 characters">
                <input
                  id="claim-password"
                  className="field"
                  type="password"
                  value={claimPassword}
                  onChange={(e) => setClaimPassword(e.target.value)}
                  autoComplete="new-password"
                />
              </Field>
              <Field label="Confirm password">
                <input
                  id="claim-password-confirm"
                  className="field"
                  type="password"
                  value={claimConfirm}
                  onChange={(e) => setClaimConfirm(e.target.value)}
                  autoComplete="new-password"
                />
              </Field>

              <button type="submit" className="btn-primary w-full" disabled={claimPending}>
                {claimPending ? <Loader2 size={16} className="animate-spin" /> : <UserPlus size={16} />}
                <span>{claimPending ? 'Creating account…' : 'Create account & join'}</span>
              </button>
            </form>

            <div className="relative flex items-center gap-4 py-1">
              <div className="h-px flex-1 bg-slate-200" />
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">or</span>
              <div className="h-px flex-1 bg-slate-200" />
            </div>

            <button type="button" className="btn-secondary w-full" onClick={handleGoLogin}>
              <LogIn size={16} />
              <span>Already have an account? Log in</span>
            </button>
          </div>
        )}

        {/* Error display */}
        {(mode === 'error' || (error && mode === 'preview')) && (
          <InlineAlert tone="danger" title="Invite error">
            {error || (missingInviteId ? 'Invite id is missing from the URL.' : 'An unknown error occurred.')}
          </InlineAlert>
        )}
      </GlassPanel>
    </div>
  );
};
