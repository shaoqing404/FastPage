import type { ComplianceCitation, ComplianceRun, ComplianceVerdict } from '../../types';

const toLabel = (value: string | null | undefined, fallback: string) =>
  (value || fallback)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());

export const formatComplianceLabel = (value: string | null | undefined, fallback = 'Unknown') => toLabel(value, fallback);

export const getRunStatusTone = (status: ComplianceRun['status']) => {
  switch (status) {
    case 'completed':
      return 'success';
    case 'failed':
    case 'cancelled':
      return 'danger';
    case 'queued':
      return 'warning';
    case 'running':
      return 'accent';
    default:
      return 'default';
  }
};

export const getVerdictTone = (verdict: ComplianceVerdict | null | undefined) => {
  switch (verdict) {
    case 'pass':
      return 'success';
    case 'fail':
      return 'danger';
    case 'inconclusive':
      return 'warning';
    case 'not_applicable':
      return 'default';
    default:
      return 'default';
  }
};

export const formatCitationChain = (citation: ComplianceCitation) =>
  [
    citation.document_label || citation.document_id || 'Unknown document',
    citation.version_label || citation.version_id || 'Unknown version',
    citation.page_label || 'Page unavailable',
    citation.node_id ? `Node ${citation.node_id}` : 'Node unavailable',
  ].join(' / ');
