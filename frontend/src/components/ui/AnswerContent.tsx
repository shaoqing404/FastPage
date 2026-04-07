import React from 'react';

import { cn } from '../../lib/utils';
import { MarkdownContent } from './MarkdownContent';

type AnswerContentProps = {
  content: string | null | undefined;
  className?: string;
  variant?: 'full' | 'compact';
  emptyFallback?: string;
};

export const AnswerContent: React.FC<AnswerContentProps> = ({
  content,
  className,
  variant = 'full',
  emptyFallback = 'No assistant answer recorded yet.',
}) => {
  const trimmed = content?.trim();

  if (!trimmed) {
    return <p className={cn('text-sm text-slate-500', className)}>{emptyFallback}</p>;
  }

  return (
    <MarkdownContent
      content={trimmed}
      className={cn(
        variant === 'compact' && 'markdown-content-compact text-sm text-slate-600',
        className,
      )}
    />
  );
};
