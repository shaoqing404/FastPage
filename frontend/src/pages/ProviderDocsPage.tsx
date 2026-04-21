import React, { useState } from 'react';
import { Copy, ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';

import { GlassPanel, InlineAlert, SectionToolbar } from '../components/ui/workbench';
import { resolveApiUrl } from '../lib/api/client';
import { copyTextToClipboard } from '../lib/clipboard';
import { getErrorMessage } from '../lib/utils';

const CURL_EXAMPLE = `curl -X GET \\
  -H "X-API-Key: <your-workspace-api-key>" \\
  "${resolveApiUrl('/model-providers')}"`;

const HEADER_EXAMPLE = 'X-API-Key: <your-workspace-api-key>';

const SKILL_RUN_EXAMPLE = `curl -X POST \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: <your-workspace-api-key>" \\
  "${resolveApiUrl('/chat/skills/<skill-id>/run')}" \\
  -d '{
    "question": "What changed in this policy?",
    "session_id": "<optional-session-id>"
  }'`;

const LISTED_ENDPOINTS = [
  '/api/v1/model-providers',
  '/api/v1/skills',
  '/api/v1/documents',
  '/api/v1/chat/skills/{skillId}/run',
];

export const ProviderDocsPage: React.FC = () => {
  const [copyFeedback, setCopyFeedback] = useState('');

  const handleCopy = async (value: string, label: string) => {
    try {
      await copyTextToClipboard(value);
      setCopyFeedback(`${label} copied.`);
    } catch (error) {
      setCopyFeedback(getErrorMessage(error, `Clipboard copy failed. Manually copy the ${label.toLowerCase()} shown on this page.`));
    }
  };

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Provider API docs"
        description="Workspace API keys authenticate service-to-service calls through the existing PageIndex API contract."
        actions={(
          <div className="flex items-center gap-2">
            <Link to="/providers" className="btn-secondary">
              <span>Back to providers</span>
            </Link>
            <button type="button" className="btn-secondary" onClick={() => handleCopy(HEADER_EXAMPLE, 'Header example')}>
              <Copy size={16} />
              <span>Copy header</span>
            </button>
            <button type="button" className="btn-primary" onClick={() => handleCopy(CURL_EXAMPLE, 'curl example')}>
              <Copy size={16} />
              <span>Copy curl</span>
            </button>
          </div>
        )}
      />

      {copyFeedback && (
        <InlineAlert tone="default" title="Copy status">
          {copyFeedback}
        </InlineAlert>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <GlassPanel title="Authentication" subtitle="API keys use a dedicated header. They do not replace browser session tokens.">
          <div className="space-y-4">
            <InlineAlert tone="default" title="Real contract">
              Workspace API keys authenticate requests with <strong>`X-API-Key`</strong>. Browser sessions continue to use <strong>`Authorization: Bearer &lt;token&gt;`</strong>.
            </InlineAlert>
            <div className="docs-code-block">{HEADER_EXAMPLE}</div>
            <div className="space-y-2 text-sm text-slate-600">
              <p>Workspace API keys are scoped to the current workspace at creation time.</p>
              <p>Creation, listing, and revoke operations are served by `/api/v1/auth/apikeys`.</p>
              <p>The raw key is only returned at creation time by the API response.</p>
            </div>
          </div>
        </GlassPanel>

        <GlassPanel title="Lifecycle" subtitle="Issue, store, and revoke keys under the same workspace context.">
          <div className="space-y-4 text-sm text-slate-600">
            <p>1. Create the workspace API key from the Providers page.</p>
            <p>2. Store the raw secret outside the browser if it will be used by automation or services.</p>
            <p>3. Send it on each request with the `X-API-Key` header.</p>
            <p>4. Revoke the key from the same workspace when it is no longer needed.</p>
          </div>
        </GlassPanel>
      </div>

      <GlassPanel title="Example requests" subtitle="Representative routes that already accept principal-based API key authentication.">
        <div className="space-y-5">
          <div className="docs-code-block">{CURL_EXAMPLE}</div>
          <div className="docs-code-block">{SKILL_RUN_EXAMPLE}</div>
          <div className="grid gap-3 md:grid-cols-2">
            {LISTED_ENDPOINTS.map((endpoint) => (
              <div key={endpoint} className="surface-soft p-4">
                <p className="font-medium text-slate-900">{endpoint}</p>
                <p className="mt-1 text-sm text-slate-500">Protected by the current principal contract and usable with `X-API-Key`.</p>
              </div>
            ))}
          </div>
        </div>
      </GlassPanel>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <GlassPanel title="Limits and boundaries" subtitle="What this page does not imply.">
          <div className="space-y-3 text-sm text-slate-600">
            <p>Platform routes do not accept workspace API key authentication.</p>
            <p>API keys are not interchangeable with browser login sessions.</p>
            <p>This page documents the current contract only. It does not imply an interactive API explorer or future endpoints.</p>
          </div>
        </GlassPanel>

        <GlassPanel title="Current API base" subtitle="Examples on this page are generated against the current frontend API base resolution.">
          <div className="space-y-4">
            <div className="docs-code-block">{resolveApiUrl('/')}</div>
            <a className="btn-secondary w-fit" href={resolveApiUrl('/model-providers')} target="_blank" rel="noreferrer">
              <ExternalLink size={16} />
              <span>Open provider endpoint</span>
            </a>
          </div>
        </GlassPanel>
      </div>
    </div>
  );
};
