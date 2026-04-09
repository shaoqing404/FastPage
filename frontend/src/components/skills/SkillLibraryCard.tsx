import React from 'react';
import { Layers3, Settings2 } from 'lucide-react';

import { StatusBadge } from '../ui/workbench';
import { cn } from '../../lib/utils';
import type { KnowledgeBaseSummary, SkillConsoleItem } from './types';
import { getKnowledgeBaseDocumentCount } from './types';

export const SkillLibraryCard: React.FC<{
  skill: SkillConsoleItem;
  knowledgeBase: KnowledgeBaseSummary | null;
  providerLabel: string;
  selected: boolean;
  onSelect: () => void;
}> = ({ skill, knowledgeBase, providerLabel, selected, onSelect }) => {
  const active = skill.is_active !== false;
  const documentCount = knowledgeBase ? getKnowledgeBaseDocumentCount(knowledgeBase) : skill.document_ids.length;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn('list-row w-full text-left', selected && 'list-row-active')}
    >
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Settings2 size={16} className="text-slate-400" />
          <p className="font-medium text-slate-900">{skill.name}</p>
          <StatusBadge tone={active ? 'success' : 'warning'}>{active ? 'Active' : 'Inactive'}</StatusBadge>
        </div>
        <p className="line-clamp-2 text-sm text-slate-500">{skill.description || skill.system_prompt}</p>
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone={knowledgeBase ? 'accent' : 'warning'}>
            {knowledgeBase ? knowledgeBase.name : 'Legacy document shim'}
          </StatusBadge>
          <StatusBadge>{documentCount} docs</StatusBadge>
          <StatusBadge>{providerLabel}</StatusBadge>
        </div>
      </div>
      <div className="space-y-3 text-right">
        <div className="flex items-center justify-end gap-2 text-sm text-slate-500">
          <Layers3 size={15} />
          <span>{knowledgeBase?.status || 'kb-unbound'}</span>
        </div>
        <p className="text-sm font-medium text-slate-700">{skill.model}</p>
      </div>
    </button>
  );
};
