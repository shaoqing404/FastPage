import React from 'react';

import { cn } from '../../lib/utils';

type InlineToken =
  | { type: 'text'; value: string }
  | { type: 'strong'; value: string }
  | { type: 'code'; value: string }
  | { type: 'link'; label: string; href: string };

type Block =
  | { type: 'heading'; level: number; text: string }
  | { type: 'ordered-list'; items: string[] }
  | { type: 'unordered-list'; items: string[] }
  | { type: 'paragraph'; text: string };

const INLINE_PATTERN = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

const tokenizeInline = (value: string): InlineToken[] => {
  const parts = value.split(INLINE_PATTERN).filter(Boolean);
  return parts.map((part) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return { type: 'strong', value: part.slice(2, -2) };
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return { type: 'code', value: part.slice(1, -1) };
    }
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      return { type: 'link', label: linkMatch[1], href: linkMatch[2] };
    }
    return { type: 'text', value: part };
  });
};

const parseMarkdown = (value: string): Block[] => {
  const lines = value.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let paragraphLines: string[] = [];
  let orderedItems: string[] = [];
  let unorderedItems: string[] = [];

  const flushParagraph = () => {
    if (!paragraphLines.length) return;
    blocks.push({ type: 'paragraph', text: paragraphLines.join('\n').trim() });
    paragraphLines = [];
  };

  const flushLists = () => {
    if (orderedItems.length) {
      blocks.push({ type: 'ordered-list', items: orderedItems });
      orderedItems = [];
    }
    if (unorderedItems.length) {
      blocks.push({ type: 'unordered-list', items: unorderedItems });
      unorderedItems = [];
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushLists();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushLists();
      blocks.push({ type: 'heading', level: headingMatch[1].length, text: headingMatch[2] });
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      if (unorderedItems.length) flushLists();
      orderedItems.push(orderedMatch[1]);
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.*)$/);
    if (unorderedMatch) {
      flushParagraph();
      if (orderedItems.length) flushLists();
      unorderedItems.push(unorderedMatch[1]);
      continue;
    }

    flushLists();
    paragraphLines.push(trimmed);
  }

  flushParagraph();
  flushLists();
  return blocks;
};

const renderInline = (value: string) =>
  tokenizeInline(value).map((token, index) => {
    if (token.type === 'strong') {
      return <strong key={`${token.type}-${index}`}>{token.value}</strong>;
    }
    if (token.type === 'code') {
      return <code key={`${token.type}-${index}`}>{token.value}</code>;
    }
    if (token.type === 'link') {
      return (
        <a key={`${token.type}-${index}`} href={token.href} target="_blank" rel="noreferrer">
          {token.label}
        </a>
      );
    }
    return <React.Fragment key={`${token.type}-${index}`}>{token.value}</React.Fragment>;
  });

export const MarkdownContent: React.FC<{ content: string; className?: string }> = ({ content, className }) => {
  const blocks = parseMarkdown(content);

  const renderHeading = (level: number, key: string, text: string) => {
    const normalizedLevel = Math.min(level + 2, 6);
    if (normalizedLevel === 3) {
      return <h3 key={key}>{renderInline(text)}</h3>;
    }
    if (normalizedLevel === 4) {
      return <h4 key={key}>{renderInline(text)}</h4>;
    }
    if (normalizedLevel === 5) {
      return <h5 key={key}>{renderInline(text)}</h5>;
    }
    if (normalizedLevel === 6) {
      return <h6 key={key}>{renderInline(text)}</h6>;
    }
    return <h2 key={key}>{renderInline(text)}</h2>;
  };

  return (
    <div className={cn('markdown-content', className)}>
      {blocks.map((block, index) => {
        if (block.type === 'heading') {
          return renderHeading(block.level, `${block.type}-${index}`, block.text);
        }
        if (block.type === 'ordered-list') {
          return (
            <ol key={`${block.type}-${index}`}>
              {block.items.map((item, itemIndex) => (
                <li key={`${block.type}-${index}-${itemIndex}`}>{renderInline(item)}</li>
              ))}
            </ol>
          );
        }
        if (block.type === 'unordered-list') {
          return (
            <ul key={`${block.type}-${index}`}>
              {block.items.map((item, itemIndex) => (
                <li key={`${block.type}-${index}-${itemIndex}`}>{renderInline(item)}</li>
              ))}
            </ul>
          );
        }
        return <p key={`${block.type}-${index}`}>{renderInline(block.text)}</p>;
      })}
    </div>
  );
};
