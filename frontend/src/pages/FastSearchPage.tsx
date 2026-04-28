import React, { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { FileSearch, Loader2, Zap } from 'lucide-react';

import { GlassPanel, InlineAlert, KeyMetric, SectionToolbar, StatusBadge } from '../components/ui/workbench';
import { documentsApi } from '../features/documents/api';
import { searchApi } from '../features/search/api';
import type { FastSearchRequest, FastSearchResponse } from '../features/search/api';
import { getErrorMessage } from '../lib/utils';
import { FastSearchNodeList } from '../components/search/FastSearchNodeList';

const FAST_SEARCH_TOP_K_DEFAULT = 3;
const FAST_SEARCH_TOP_K_MAX = 10;

export const FastSearchPage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [selectedDocId, setSelectedDocId] = useState('');
  const [topK, setTopK] = useState<number>(FAST_SEARCH_TOP_K_DEFAULT);
  const [searchError, setSearchError] = useState('');
  const [searchResult, setSearchResult] = useState<FastSearchResponse | null>(null);
  const [requestLatencyMs, setRequestLatencyMs] = useState<number | null>(null);

  const formatMillisecondsAsSeconds = (value: number | null | undefined) => {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'N/A';
    return `${(Number(value) / 1000).toFixed(5)} s`;
  };

  const formatSource = (value: string | null | undefined) => value ? value.replace(/_/g, ' ') : 'N/A';

  const { data: documents = [], isLoading: isLoadingDocs } = useQuery({
    queryKey: ['documents'],
    queryFn: () => documentsApi.list({}),
  });

  const searchMutation = useMutation({
    mutationFn: async (payload: FastSearchRequest) => {
      const startedAt = performance.now();
      try {
        return await searchApi.fastSearch(payload);
      } finally {
        setRequestLatencyMs(performance.now() - startedAt);
      }
    },
    onSuccess: (data) => {
      setSearchError('');
      setSearchResult(data);
    },
    onError: (error: unknown) => {
      setSearchError(getErrorMessage(error, 'Fast Search failed'));
      setSearchResult(null);
    },
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !selectedDocId) return;
    
    const doc = documents.find(d => d.id === selectedDocId);
    if (!doc || !doc.active_version_id) {
      setSearchError('Selected document has no active version');
      return;
    }

    searchMutation.mutate({
      document_id: doc.id,
      version_id: doc.active_version_id,
      query,
      node_top_k: topK,
      include_snippets: true,
    });
  };

  const readyDocuments = documents.filter(d => d.status === 'index_ready');
  const searchStatus = searchMutation.isPending ? '搜索中' : searchResult ? '完成' : searchError ? '失败' : '待搜索';

  return (
    <div className="space-y-8">
      <SectionToolbar
        title="Fast Search"
        description="Low-latency explicit fact search surface, bypassing DeepResearch LLM pipelines."
        actions={
          <div className="flex items-center gap-2 text-sm text-slate-500 font-medium">
            <Zap size={16} className="text-yellow-500" />
            <span>Sub-second Retrieval</span>
          </div>
        }
      />

      {searchError && (
        <InlineAlert tone="danger" title="Search Error">
          {searchError}
        </InlineAlert>
      )}

      <div className="grid grid-cols-[1fr_2fr] gap-6">
        <div className="space-y-6">
          <GlassPanel title="Search Configuration">
            <form onSubmit={handleSearch} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Target Document</label>
                <select
                  className="field w-full"
                  value={selectedDocId}
                  onChange={(e) => setSelectedDocId(e.target.value)}
                  disabled={isLoadingDocs}
                  required
                >
                  <option value="" disabled>Select a ready document...</option>
                  {readyDocuments.map(doc => (
                    <option key={doc.id} value={doc.id}>{doc.display_name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Top K Nodes</label>
                <input
                  type="number"
                  min={1}
                  max={FAST_SEARCH_TOP_K_MAX}
                  className="field w-full"
                  value={topK}
                  onChange={(e) => setTopK(Math.min(FAST_SEARCH_TOP_K_MAX, Math.max(1, Number(e.target.value) || FAST_SEARCH_TOP_K_DEFAULT)))}
                />
                <p className="mt-1 text-xs text-slate-500">推荐 3，最多 10。每个节点可能对应一整个章节正文。</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Query</label>
                <input
                  type="text"
                  className="field w-full"
                  placeholder="e.g. 特殊机场有哪些？"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  required
                />
              </div>

              <button
                type="submit"
                className="btn-primary w-full justify-center"
                disabled={searchMutation.isPending || !selectedDocId || !query.trim()}
              >
                {searchMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <FileSearch size={16} />}
                <span>{searchMutation.isPending ? 'Searching...' : 'Search'}</span>
              </button>
            </form>
          </GlassPanel>
        </div>

        <div className="space-y-6">
          {searchResult?.boundary_flags?.includes('complex_query') && (
            <InlineAlert tone="warning" title="Complex Query Detected">
              {searchResult.fallback_recommendation || '建议使用 DeepResearch'}
            </InlineAlert>
          )}
          {searchResult?.fallback_recommendation && !searchResult.boundary_flags?.includes('complex_query') && (
            <InlineAlert tone="default" title="Search Fallback">
              {searchResult.fallback_recommendation}
            </InlineAlert>
          )}

          <GlassPanel title="检索状态" subtitle="当前 Fast Search 请求的耗时、后端路径和降级原因。">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <KeyMetric label="状态" value={searchStatus} />
              <KeyMetric label="接口耗时" value={formatMillisecondsAsSeconds(requestLatencyMs)} />
              <KeyMetric label="后端总耗时" value={formatMillisecondsAsSeconds(searchResult?.server_total_latency_ms ?? searchResult?.latency_ms)} />
              <KeyMetric label="目录加载" value={formatMillisecondsAsSeconds(searchResult?.corpus_load_latency_ms)} />
              <KeyMetric label="正文加载" value={formatMillisecondsAsSeconds(searchResult?.content_enrich_latency_ms)} />
              <KeyMetric label="Dense/ES" value={formatMillisecondsAsSeconds(searchResult?.dense_search_latency_ms)} />
              <KeyMetric label="节点打分" value={formatMillisecondsAsSeconds(searchResult?.node_score_latency_ms ?? searchResult?.legacy_node_shadow_latency_ms)} />
              <KeyMetric label="召回模式" value={searchResult?.mode || 'N/A'} />
              <KeyMetric label="生效后端" value={formatSource(searchResult?.active_backend)} />
              <KeyMetric label="召回节点数" value={searchResult?.nodes.length ?? 0} />
              <KeyMetric label="请求 dense source" value={formatSource(searchResult?.requested_dense_source)} />
              <KeyMetric label="实际 dense source" value={formatSource(searchResult?.dense_source)} />
              <KeyMetric label="TopK" value={searchResult?.node_top_k ?? topK} />
              <KeyMetric label="Query embedding" value={searchResult?.query_embedding_computed ? `${searchResult.query_embedding_dimensions ?? 'N/A'} 维` : '未计算'} />
              <KeyMetric label="ES 查询" value={searchResult?.es_executed ? '已执行' : '未执行'} />
              <KeyMetric label="正文检索面" value={searchResult?.section_text_participated ? `${searchResult.section_text_node_count ?? 0} nodes` : '未参与'} />
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {searchResult?.boundary_flags?.length ? (
                searchResult.boundary_flags.map((flag) => (
                  <StatusBadge key={flag} tone="warning">{formatSource(flag)}</StatusBadge>
                ))
              ) : (
                <StatusBadge tone="success">no boundary flags</StatusBadge>
              )}
              {searchResult?.fallback_reason ? (
                <StatusBadge tone="danger">{searchResult.fallback_reason}</StatusBadge>
              ) : (
                <StatusBadge tone="success">no fallback reason</StatusBadge>
              )}
            </div>
          </GlassPanel>

          <GlassPanel
            title="Search Results"
            subtitle={searchResult ? `Found ${searchResult.nodes.length} nodes · backend ${formatSource(searchResult.active_backend)} · ${formatMillisecondsAsSeconds(searchResult.latency_ms)}` : 'Awaiting search...'}
          >
            {searchMutation.isPending ? (
              <div className="empty-state min-h-[300px]">
                <Loader2 size={24} className="animate-spin text-blue-600 mb-4" />
                <p className="text-sm text-slate-500">Searching...</p>
              </div>
            ) : searchResult && searchResult.nodes.length > 0 ? (
              <FastSearchNodeList nodes={searchResult.nodes} />
            ) : searchResult ? (
              <div className="empty-state min-h-[300px]">
                <p className="text-sm font-medium text-slate-900">No nodes found</p>
                <p className="text-xs text-slate-500">Try a different query or document.</p>
              </div>
            ) : (
              <div className="empty-state min-h-[300px]">
                <FileSearch size={32} className="text-slate-300 mb-4" />
                <p className="text-sm text-slate-500">Run a search to see extracted nodes.</p>
              </div>
            )}
          </GlassPanel>
        </div>
      </div>
    </div>
  );
};
