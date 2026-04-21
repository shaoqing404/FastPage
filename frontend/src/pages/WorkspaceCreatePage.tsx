import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Loader2, Plus } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';

import { GlassPanel, Field, InlineAlert, SectionToolbar } from '../components/ui/workbench';
import { workspacesApi } from '../features/workspaces/api';
import { resolveAppPath, resolveStoredUser, storeAuthTokenResponse } from '../lib/api/client';
import { getErrorMessage } from '../lib/utils';

export const WorkspaceCreatePage: React.FC = () => {
  const navigate = useNavigate();
  const user = resolveStoredUser();
  const canCreate = user?.can_create_workspace === true || user?.is_platform_admin === true;
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [error, setError] = useState('');

  const createMutation = useMutation({
    mutationFn: () =>
      workspacesApi.create({
        name: name.trim(),
        ...(slug.trim() ? { slug: slug.trim() } : {}),
      }),
    onSuccess: (response) => {
      storeAuthTokenResponse(response);
      window.location.assign(resolveAppPath('/workspace'));
    },
    onError: (nextError: unknown) => {
      setError(getErrorMessage(nextError, 'Workspace creation failed'));
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setError('');
    createMutation.mutate();
  };

  if (!canCreate) {
    return (
      <div className="space-y-8">
        <SectionToolbar
          title="Create Workspace"
          description="Provision a new workspace and become its founder."
        />
        <GlassPanel>
          <InlineAlert tone="warning" title="Workspace creation is restricted">
            Your account does not have the <code>can_create_workspace</code> capability and is not a platform administrator. Contact your
            platform admin to enable workspace creation.
          </InlineAlert>
        </GlassPanel>
      </div>
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-10rem)] items-start justify-center pt-8">
      <div className="w-full max-w-3xl space-y-8">
        <SectionToolbar
          title="Create Workspace"
          description="Provision a new workspace inside the current tenant. You will become the founder and be automatically switched into the new workspace context."
        />

        <GlassPanel
          title="New workspace"
          subtitle="A workspace isolates knowledge bases, skills, providers, and API keys from other workspaces in the same tenant."
        >
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="grid gap-5 md:grid-cols-2">
              <Field label="Workspace name" required hint="A human-readable name for this workspace.">
                <input
                  className="field"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Engineering Team"
                  required
                  autoFocus
                />
              </Field>
              <Field label="Slug" hint="Optional. If omitted, the backend generates one from the name.">
                <input
                  className="field"
                  value={slug}
                  onChange={(event) => setSlug(event.target.value)}
                  placeholder="engineering-team"
                />
              </Field>
            </div>

            {error && (
              <InlineAlert tone="danger" title="Workspace creation failed">
                {error}
              </InlineAlert>
            )}

            <div className="flex items-center gap-3">
              <button type="submit" className="btn-primary" disabled={createMutation.isPending || !name.trim()}>
                {createMutation.isPending ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    <span>Creating…</span>
                  </>
                ) : (
                  <>
                    <Plus size={16} />
                    <span>Create workspace</span>
                  </>
                )}
              </button>
              <button type="button" className="btn-secondary" onClick={() => navigate('/workspace')}>
                <span>Cancel</span>
                <ArrowRight size={16} />
              </button>
            </div>
          </form>
        </GlassPanel>
      </div>
    </div>
  );
};
