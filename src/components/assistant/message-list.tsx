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
  // 사용자가 바닥에 있을 때만 자동 스크롤한다 — 스트리밍 중 위로 올려 읽는 사용자를 매 토큰마다
  // 끌어내리지 않도록. 바닥 센티넬의 가시성(스크롤 컨테이너 클리핑 포함)으로 판별한다.
  const atBottomRef = useRef(true);

  useEffect(() => {
    const el = endRef.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => {
      atBottomRef.current = entry.isIntersecting;
    });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (atBottomRef.current) {
      endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages]);

  const lastId = messages[messages.length - 1]?.id;

  // 완료된 마지막 어시스턴트 답변만 스크린리더에 한 번 알린다(스트리밍 중 토큰 단위 중복 낭독 방지).
  const announce = [...messages]
    .reverse()
    .find((m) => m.role === 'assistant' && !m.streaming && !m.error && m.content)?.content;

  return (
    <>
      <div className="flex flex-col gap-3">
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
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {announce ?? ''}
      </div>
    </>
  );
}
