import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCcw } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';

import { ComplianceLaunchPanel, ComplianceRunDetail, ComplianceRunList } from '../components/compliance';
import { InlineAlert, KeyMetric, SectionToolbar, GlassPanel } from '../components/ui/workbench';
import { complianceApi } from '../features/compliance';
import { knowledgeBasesApi } from '../features/knowledge-bases/api';
import { providersApi } from '../features/providers/api';
import { runtimeObservationsApi } from '../features/runtime-observations/api';
import type { ComplianceRun, RunObservationEvent, RunObservationSnapshot } from '../types';
import { getErrorMessage } from '../lib/utils';

const matchesSearch = (run: ComplianceRun, query: string) => {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;
  return [
    run.input.question,
    run.summary,
    run.answer,
    run.verdict,
    run.error?.message,
    run.compliance_check_id,
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(normalizedQuery));
};

export const ComplianceRunsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [modeFilter, setModeFilter] = useState('all');
  const [checkFilter, setCheckFilter] = useState('all');
  const [streamedObservationEvents, setStreamedObservationEvents] = useState<RunObservationEvent[]>([]);

  const runsQuery = useQuery({
    queryKey: ['compliance-runs'],
    queryFn: () => complianceApi.runs.list(),
    refetchInterval: 5000,
  });
  const checksQuery = useQuery({
    queryKey: ['compliance-checks'],
    queryFn: () => complianceApi.checks.list(),
  });
  const knowledgeBasesQuery = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: () => knowledgeBasesApi.list(),
  });
  const providersQuery = useQuery({
    queryKey: ['providers'],
    queryFn: () => providersApi.list(),
  });

  const runs = useMemo(() => runsQuery.data || [], [runsQuery.data]);
  const checks = useMemo(() => checksQuery.data || [], [checksQuery.data]);
  const knowledgeBases = useMemo(() => knowledgeBasesQuery.data || [], [knowledgeBasesQuery.data]);
  const providers = useMemo(() => providersQuery.data || [], [providersQuery.data]);
  const selectedRunId = searchParams.get('run') || '';

  const checksById = useMemo(() => Object.fromEntries(checks.map((check) => [check.id, check])) as Record<string, (typeof checks)[number]>, [checks]);
  const knowledgeBasesById = useMemo(
    () => Object.fromEntries(knowledgeBases.map((knowledgeBase) => [knowledgeBase.id, knowledgeBase])) as Record<string, (typeof knowledgeBases)[number]>,
    [knowledgeBases],
  );

  const filteredRuns = useMemo(
    () =>
      runs.filter((run) => {
        const matchesStatus = statusFilter === 'all' ? true : run.status === statusFilter;
        const matchesMode = modeFilter === 'all' ? true : run.mode === modeFilter;
        const matchesCheck =
          checkFilter === 'all' ? true : checkFilter === 'adhoc' ? !run.compliance_check_id : run.compliance_check_id === checkFilter;
        return matchesStatus && matchesMode && matchesCheck && matchesSearch(run, search);
      }),
    [checkFilter, modeFilter, runs, search, statusFilter],
  );

  useEffect(() => {
    if (selectedRunId || filteredRuns.length === 0) return;
    const next = new URLSearchParams(searchParams);
    next.set('run', filteredRuns[0].id);
    setSearchParams(next, { replace: true });
  }, [filteredRuns, searchParams, selectedRunId, setSearchParams]);

  const selectedRunSummary = useMemo(() => runs.find((run) => run.id === selectedRunId) || null, [runs, selectedRunId]);

  const selectedRunQuery = useQuery({
    queryKey: ['compliance-run', selectedRunId],
    queryFn: () => complianceApi.runs.get(selectedRunId),
    enabled: Boolean(selectedRunId),
    refetchInterval: selectedRunSummary && ['queued', 'running'].includes(selectedRunSummary.status) ? 3000 : false,
  });
  const observationSnapshotQuery = useQuery({
    queryKey: ['runtime-observation', 'compliance', selectedRunId],
    queryFn: () => runtimeObservationsApi.getSnapshot('compliance', selectedRunId),
    enabled: Boolean(selectedRunId),
    refetchInterval: selectedRunSummary && ['queued', 'running'].includes(selectedRunSummary.status) ? 3000 : false,
  });

  const selectedRun = selectedRunQuery.data || selectedRunSummary || null;
  useEffect(() => {
    setStreamedObservationEvents([]);
    if (!selectedRunId || !selectedRunSummary || !['queued', 'running'].includes(selectedRunSummary.status)) return undefined;
    const controller = new AbortController();
    runtimeObservationsApi.stream('compliance', selectedRunId, {
      signal: controller.signal,
      onObservation: (event) => {
        setStreamedObservationEvents((current) => (
          current.some((item) => item.id === event.id) ? current : [...current, event]
        ));
      },
    }).catch(() => {});
    return () => controller.abort();
  }, [selectedRunId, selectedRunSummary]);
  const selectedCheck = selectedRun?.compliance_check_id ? checksById[selectedRun.compliance_check_id] || null : null;
  const selectedKnowledgeBase = selectedRun ? knowledgeBasesById[selectedRun.target.knowledge_base_id] || null : null;
  const observationSnapshot = useMemo<RunObservationSnapshot | null>(() => {
    const base = observationSnapshotQuery.data || null;
    if (!streamedObservationEvents.length) return base;
    return {
      run_kind: 'compliance',
      run_id: selectedRunId,
      status: selectedRun?.status || base?.status || 'queued',
      current_step: streamedObservationEvents[streamedObservationEvents.length - 1]?.step || base?.current_step || null,
      worker_node_code: base?.worker_node_code || null,
      queue: base?.queue || {},
      timings: base?.timings || {},
      execution_context: (selectedRun?.execution_context || base?.execution_context || {}) as Record<string, unknown>,
      partial_answer: selectedRun?.answer || base?.partial_answer || null,
      events: streamedObservationEvents,
    };
  }, [observationSnapshotQuery.data, selectedRun, selectedRunId, streamedObservationEvents]);

  const pageError = [runsQuery.error, checksQuery.error, knowledgeBasesQuery.error, providersQuery.error]
    .filter(Boolean)
    .map((error) => getErrorMessage(error, 'Failed to load compliance data'))
    .join(' · ');

  const totalRuns = runs.length;
  const runningRuns = runs.filter((run) => run.status === 'running' || run.status === 'queued').length;
  const completedRuns = runs.filter((run) => run.status === 'completed').length;
  const failedRuns = runs.filter((run) => run.status === 'failed').length;

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Compliance Runs"
        description="Launch one-off compliance questions, execute saved checks, filter past runs, and inspect structured result provenance without dropping into raw JSON."
        actions={
          <button type="button" className="btn-secondary" onClick={() => runsQuery.refetch()}>
            <RefreshCcw size={16} />
            <span>Refresh runs</span>
          </button>
        }
      />

      {pageError && (
        <InlineAlert tone="danger" title="Compliance Runs page failed to load cleanly">
          {pageError}
        </InlineAlert>
      )}

      <div className="grid grid-cols-4 gap-4">
        <KeyMetric label="Runs" value={totalRuns} hint="Compliance history in this Workspace" />
        <KeyMetric label="In flight" value={runningRuns} hint="Queued or actively executing" />
        <KeyMetric label="Completed" value={completedRuns} hint="Structured result available" />
        <KeyMetric label="Failed" value={failedRuns} hint="Needs operator review" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.5fr_0.86fr]">
        <GlassPanel title="Run log" subtitle="Filter by status, mode, or saved check, then open a detail view.">
          <ComplianceRunList
            runs={filteredRuns}
            hasAnyRuns={runs.length > 0}
            selectedRunId={selectedRunId}
            knowledgeBasesById={knowledgeBasesById}
            checksById={checksById}
            search={search}
            onSearchChange={setSearch}
            statusFilter={statusFilter}
            onStatusFilterChange={setStatusFilter}
            modeFilter={modeFilter}
            onModeFilterChange={setModeFilter}
            checkFilter={checkFilter}
            onCheckFilterChange={setCheckFilter}
            isLoading={runsQuery.isLoading}
            onSelect={(runId) => {
              const next = new URLSearchParams(searchParams);
              next.set('run', runId);
              setSearchParams(next);
            }}
          />
        </GlassPanel>

        <ComplianceRunDetail
          run={selectedRun}
          check={selectedCheck}
          knowledgeBase={selectedKnowledgeBase}
          providers={providers}
          observationSnapshot={observationSnapshot}
          isLoading={selectedRunQuery.isLoading && !selectedRunSummary}
          isRefreshing={selectedRunQuery.isFetching}
          loadError={selectedRunQuery.error ? getErrorMessage(selectedRunQuery.error, 'Failed to refresh selected run') : ''}
        />

        <ComplianceLaunchPanel
          knowledgeBases={knowledgeBases}
          checks={checks}
          providers={providers}
          onRunCreated={(run) => {
            const next = new URLSearchParams(searchParams);
            next.set('run', run.id);
            setSearchParams(next);
          }}
        />
      </div>
    </div>
  );
};
