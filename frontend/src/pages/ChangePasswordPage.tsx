import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { KeyRound, Loader2, CheckCircle2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { GlassPanel, InlineAlert, Field } from '../components/ui/workbench';
import { authApi } from '../features/auth/api';
import { resolveAppPath, storeAuthTokenResponse } from '../lib/api/client';
import { getErrorMessage } from '../lib/utils';

export const ChangePasswordPage: React.FC = () => {
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [formError, setFormError] = useState('');

  const mutation = useMutation({
    mutationFn: async () => {
      if (!currentPassword.trim()) throw new Error('Current password is required.');
      if (newPassword.length < 8) throw new Error('New password must be at least 8 characters.');
      if (newPassword !== confirmPassword) throw new Error('Passwords do not match.');
      return authApi.changePassword({ current_password: currentPassword, new_password: newPassword });
    },
    onSuccess: (response) => {
      storeAuthTokenResponse(response);
      setFormError('');
      // Redirect after a short delay so the user sees the success state
      setTimeout(() => navigate(resolveAppPath('/workspace'), { replace: true }), 1200);
    },
    onError: (error: unknown) => {
      setFormError(getErrorMessage(error, 'Failed to change password'));
    },
  });

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(255,255,255,0.95),_transparent_26%),radial-gradient(circle_at_bottom_right,_rgba(191,219,254,0.82),_transparent_28%),linear-gradient(180deg,_#f8fafc_0%,_#e9eef5_100%)] px-6">
      <div className="absolute left-12 top-12 h-72 w-72 rounded-full bg-white/70 blur-3xl" />
      <div className="absolute bottom-16 right-12 h-80 w-80 rounded-full bg-blue-200/55 blur-3xl" />

      <GlassPanel className="relative w-full max-w-[520px]" bodyClassName="space-y-6">
        <div className="space-y-3">
          <div className="inline-flex h-14 w-14 items-center justify-center rounded-[18px] bg-white/88 text-blue-600 shadow-sm">
            {mutation.isSuccess ? <CheckCircle2 size={26} /> : <KeyRound size={26} />}
          </div>
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-[0.28em] text-slate-500">Security</p>
            <h1 className="text-3xl font-semibold tracking-[-0.05em] text-slate-950">
              {mutation.isSuccess ? 'Password updated' : 'Change your password'}
            </h1>
            <p className="text-base leading-7 text-slate-600">
              {mutation.isSuccess
                ? 'Your password has been updated. Redirecting to the workspace…'
                : 'Your account requires a password change before you can continue.'}
            </p>
          </div>
        </div>

        {!mutation.isSuccess && (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              setFormError('');
              mutation.mutate();
            }}
          >
            <Field label="Current password">
              <input
                id="change-password-current"
                className="field"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
                autoFocus
              />
            </Field>
            <Field label="New password" hint="At least 8 characters">
              <input
                id="change-password-new"
                className="field"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
              />
            </Field>
            <Field label="Confirm new password">
              <input
                id="change-password-confirm"
                className="field"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
              />
            </Field>

            {formError && (
              <InlineAlert tone="danger" title="Password change failed">
                {formError}
              </InlineAlert>
            )}

            <button
              type="submit"
              className="btn-primary w-full"
              disabled={mutation.isPending}
            >
              {mutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <KeyRound size={16} />}
              <span>{mutation.isPending ? 'Updating…' : 'Update password'}</span>
            </button>
          </form>
        )}
      </GlassPanel>
    </div>
  );
};
