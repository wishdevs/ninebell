'use client';

import { useState } from 'react';
import {
  RiCheckLine,
  RiCornerDownLeftLine,
  RiSendPlaneLine,
  RiSparkling2Line,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { MarkdownContent } from '@/components/ui/markdown-content';
import type { ChatMessage, LiveHitl } from '@/lib/live/types';
import { cn } from '@/lib/utils';

interface LiveChatCardProps {
  hitl: LiveHitl;
  messages: readonly ChatMessage[];
  /** 한 턴 전송 — 부모가 sendChat(hitl.id, text) 로 바인딩(사용자 말풍선 낙관 추가는 훅이 처리). */
  onSend: (text: string) => Promise<boolean>;
  /** 대화 종료 — 부모가 finishChat(hitl.id) 로 바인딩. done 신호 → BE 마무리(result). */
  onComplete: () => Promise<boolean>;
}

/**
 * 대화형 폼 채움 HITL — 남은 상세 필드를 자연어 한 문장으로 채운다.
 * 어시스턴트 말풍선(스트리밍)은 useLiveRun 이 chat 프레임으로 누적하고, 사용자는
 * 아래 입력창으로 한 턴씩 보낸다. '완료'를 누르면 흐름이 마무리된다(사용자만 종료).
 */
export function LiveChatCard({ hitl, messages, onSend, onComplete }: LiveChatCardProps) {
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 마지막 어시스턴트 말풍선이 스트리밍 중이면 입력 잠금(턴 충돌 방지).
  const streaming = messages.some((m) => m.streaming);
  // 마지막이 사용자 말풍선이면 에이전트 응답 대기(채우는 중). 전송/완료 중에도 처리 중으로 본다.
  // 단, 그 사용자 말풍선이 전송 실패(error)면 대기 중이 아니므로 처리 중으로 보지 않는다.
  const lastMessage = messages[messages.length - 1];
  const processing = busy || completing || (lastMessage?.role === 'user' && !lastMessage.error);

  async function send() {
    const text = draft.trim();
    if (!text || busy || streaming) return;
    setBusy(true);
    setError(null);
    setDraft('');
    const ok = await onSend(text);
    if (!ok) setError('메시지를 전달하지 못했습니다(흐름이 종료됐을 수 있음).');
    setBusy(false);
  }

  async function complete() {
    if (busy || completing) return;
    setCompleting(true);
    setError(null);
    const ok = await onComplete();
    // 성공 시 BE 가 result 프레임을 보내 카드가 닫힌다(여기서 상태 정리 불필요).
    if (!ok) {
      setError('선택 완료 전달에 실패했습니다(흐름이 종료됐을 수 있음).');
      setCompleting(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="border-warning/30 bg-warning/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
        <RiSparkling2Line size={16} aria-hidden className="text-warning mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            {hitl.title} · 대화형 입력
          </p>
          {hitl.prompt ? (
            <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">
              {hitl.prompt}
            </p>
          ) : null}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
        {messages.map((m) => (
          <Bubble key={m.id} message={m} />
        ))}
        {processing ? (
          <TypingIndicator label={completing ? '마무리하는 중…' : '에이전트가 처리 중…'} />
        ) : null}
      </div>

      <div className="border-border bg-surface-raised flex items-end gap-2 rounded-[var(--radius-md)] border p-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          rows={2}
          disabled={streaming || completing}
          placeholder="추가·수정할 내용을 한 문장으로 입력하세요"
          className="text-foreground placeholder:text-muted-foreground max-h-28 min-h-0 flex-1 resize-none bg-transparent text-[length:var(--text-body-sm)] outline-none disabled:opacity-50"
        />
        <Button
          size="icon"
          onClick={() => void send()}
          aria-label="전송"
          disabled={!draft.trim() || busy || streaming || completing}
        >
          <RiSendPlaneLine size={15} aria-hidden />
        </Button>
      </div>

      <div className="flex items-center justify-between gap-2">
        <p className="text-foreground-tertiary flex items-center gap-1 text-[10px]">
          <RiCornerDownLeftLine size={11} aria-hidden /> Enter 전송 · Shift+Enter 줄바꿈
        </p>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void complete()}
          disabled={busy || completing}
          className="border-accent/30 text-accent hover:bg-accent/10 shrink-0"
        >
          <RiCheckLine size={14} aria-hidden />
          {completing ? '완료 중…' : '선택 완료'}
        </Button>
      </div>

      {error ? <span className="text-danger text-[12px]">{error}</span> : null}
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';

  // 채움 실행로그 말풍선(note==='action') — 대화가 아니라 "무엇을 했는지" 표기.
  if (message.note === 'action') {
    return (
      <div className="text-foreground-tertiary flex items-center gap-1.5 px-1 text-[11px]">
        <span aria-hidden className="bg-accent/60 size-1.5 shrink-0 rounded-full" />
        <span className="min-w-0 font-mono">{message.content}</span>
      </div>
    );
  }

  return (
    <div className={cn('flex gap-2', isUser ? 'justify-end' : 'justify-start')}>
      {!isUser ? (
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
            ? message.error
              ? 'bg-danger/10 text-danger max-w-[80%] rounded-tr-sm'
              : 'bg-accent text-accent-foreground max-w-[80%] rounded-tr-sm'
            : 'bg-muted text-foreground max-w-[92%] min-w-0 rounded-tl-sm',
        )}
      >
        {/* 사용자 입력은 그대로, 어시스턴트는 마크다운(표) 렌더. */}
        {isUser ? message.content : <MarkdownContent content={message.content} />}
        {message.streaming ? <span className="ml-0.5 inline-block animate-pulse">▍</span> : null}
        {isUser && message.error ? (
          <span className="mt-1 block text-[10px] opacity-80">전송 실패</span>
        ) : null}
      </div>
    </div>
  );
}

function TypingIndicator({ label }: { label: string }) {
  return (
    <div className="text-foreground-tertiary flex items-center gap-2 px-1 text-[12px]">
      <span className="inline-flex gap-1" aria-hidden>
        <span className="bg-accent/70 size-1.5 animate-bounce rounded-full [animation-delay:-0.3s]" />
        <span className="bg-accent/70 size-1.5 animate-bounce rounded-full [animation-delay:-0.15s]" />
        <span className="bg-accent/70 size-1.5 animate-bounce rounded-full" />
      </span>
      {label}
    </div>
  );
}
