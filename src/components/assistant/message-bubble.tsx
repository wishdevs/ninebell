import { RiRefreshLine, RiSparkling2Line } from '@remixicon/react';
import { cn } from '@/lib/utils';
import type { AssistantMessage, AssistantSnapshot } from '@/lib/assistant/types';
import { MarkdownText } from './markdown-text';
import { AgentActionCard, isActionResolvable } from './agent-action-card';

interface MessageBubbleProps {
  message: AssistantMessage;
  snapshot: AssistantSnapshot;
  onRetry?: () => void;
}

export function MessageBubble({ message, snapshot, onRetry }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const isAssistant = !isUser && !message.error;
  const actionResolvable = message.action ? isActionResolvable(message.action, snapshot) : false;

  return (
    <div className={cn('flex gap-2', isUser ? 'justify-end' : 'justify-start')}>
      {isAssistant ? (
        <span
          aria-hidden
          className="bg-accent/10 text-accent mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full"
        >
          <RiSparkling2Line size={12} />
        </span>
      ) : null}
      <div
        className={cn(
          'rounded-[var(--radius-md)] px-3 py-2 text-[length:var(--text-body-sm)] leading-relaxed',
          isUser
            ? 'bg-accent text-accent-foreground max-w-[80%] rounded-tr-sm'
            : message.error
              ? 'bg-danger/10 text-danger max-w-[92%]'
              : 'bg-muted text-foreground max-w-[92%] min-w-0 rounded-tl-sm',
        )}
      >
        {message.content ? (
          isAssistant ? (
            <MarkdownText content={message.content} />
          ) : (
            <span className="whitespace-pre-wrap">{message.content}</span>
          )
        ) : message.streaming ? (
          <span className="text-muted-foreground">응답 생성 중…</span>
        ) : message.action ? (
          <span className="text-muted-foreground">
            {actionResolvable
              ? '관련 항목을 찾았습니다.'
              : '관련 항목을 안내했지만 현재 목록에 없어 표시할 수 없습니다.'}
          </span>
        ) : null}
        {message.streaming && message.content ? (
          <span className="text-accent ml-0.5 inline-block animate-pulse">▍</span>
        ) : null}
        {message.error && onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="text-danger mt-1.5 flex items-center gap-1 text-[11px] font-medium underline-offset-2 transition hover:underline"
          >
            <RiRefreshLine size={12} aria-hidden />
            재시도
          </button>
        ) : null}
        {message.action && actionResolvable ? (
          <AgentActionCard action={message.action} snapshot={snapshot} />
        ) : null}
      </div>
    </div>
  );
}
