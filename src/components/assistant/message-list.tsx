'use client';

import { useEffect, useRef } from 'react';
import type { AssistantMessage, AssistantSnapshot } from '@/lib/assistant/types';
import { MessageBubble } from './message-bubble';

interface MessageListProps {
  messages: readonly AssistantMessage[];
  snapshot: AssistantSnapshot;
  onRetry?: () => void;
}

export function MessageList({ messages, snapshot, onRetry }: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  const lastId = messages[messages.length - 1]?.id;

  return (
    <div className="flex flex-col gap-3" aria-live="polite">
      {messages.map((m) => (
        <MessageBubble
          key={m.id}
          message={m}
          snapshot={snapshot}
          onRetry={m.id === lastId ? onRetry : undefined}
        />
      ))}
      <div ref={endRef} />
    </div>
  );
}
