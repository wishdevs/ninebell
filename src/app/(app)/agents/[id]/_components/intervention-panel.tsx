'use client';

import { useState } from 'react';
import {
  RiCheckLine,
  RiCornerDownLeftLine,
  RiHand,
  RiSendPlaneLine,
  RiSparkling2Line,
} from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { NOW_ANCHOR, formatRelativeKorean } from '@/lib/data/format';
import type { ChatMessage, Intervention } from '@/lib/data/agents';
import { cn } from '@/lib/utils';

/**
 * 사람 개입(HITL) 패널 — 브라우저 오른쪽 영역에 표현된다.
 * - choice: 증빙유형·프로젝트처럼 의미 있는 선택을 사용자가 승인.
 * - chat: 남은 필드를 자연어 한 문장으로 입력(대화형).
 * 데모이므로 선택/전송은 토스트와 로컬 상태로만 반영한다.
 */
export function InterventionPanel({ intervention }: { intervention: Intervention }) {
  return (
    <div className="flex h-full flex-col gap-4">
      <div className="border-warning/30 bg-warning/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
        <RiHand size={16} aria-hidden className="text-warning mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            {intervention.title}
          </p>
          <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">
            {intervention.prompt}
          </p>
        </div>
      </div>

      {intervention.kind === 'choice' ? (
        <ChoiceForm intervention={intervention} />
      ) : (
        <ChatForm intervention={intervention} />
      )}
    </div>
  );
}

function ChoiceForm({ intervention }: { intervention: Intervention }) {
  const [selected, setSelected] = useState<string | null>(null);
  const options = intervention.options ?? [];

  function confirm() {
    const opt = options.find((o) => o.id === selected);
    if (!opt) return;
    toast.success(`승인: ${opt.label}`, { description: '다음 단계로 진행합니다.' });
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-col gap-2">
        {options.map((opt) => {
          const active = selected === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => setSelected(opt.id)}
              aria-pressed={active}
              className={cn(
                'flex items-center gap-3 rounded-[var(--radius-md)] border px-3 py-2.5 text-left transition-colors',
                active
                  ? 'border-accent bg-accent/5 ring-accent/30 ring-2'
                  : 'border-border hover:bg-muted/60',
              )}
            >
              <span
                aria-hidden
                className={cn(
                  'flex size-5 shrink-0 items-center justify-center rounded-full border',
                  active
                    ? 'border-accent bg-accent text-accent-foreground'
                    : 'border-border-strong',
                )}
              >
                {active ? <RiCheckLine size={12} /> : null}
              </span>
              <span className="min-w-0">
                <span className="text-foreground block text-[length:var(--text-body-sm)] font-medium">
                  {opt.label}
                </span>
                {opt.hint ? (
                  <span className="text-foreground-tertiary block text-[11px]">{opt.hint}</span>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-auto flex items-center gap-2 pt-1">
        <Button size="sm" disabled={!selected} onClick={confirm} className="flex-1">
          <RiCheckLine size={14} aria-hidden />
          승인하고 계속
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => toast.info('실행을 일시정지했습니다.')}
        >
          나중에
        </Button>
      </div>
    </div>
  );
}

function ChatForm({ intervention }: { intervention: Intervention }) {
  const [messages, setMessages] = useState<readonly ChatMessage[]>(intervention.messages ?? []);
  const [draft, setDraft] = useState('');

  function send() {
    const text = draft.trim();
    if (!text) return;
    const now = NOW_ANCHOR.toISOString();
    const userMsg: ChatMessage = { id: `u-${messages.length}`, role: 'user', text, at: now };
    const agentMsg: ChatMessage = {
      id: `a-${messages.length}`,
      role: 'agent',
      text: '입력을 반영했어요. 남은 필드가 있으면 이어서 알려주세요. (데모 응답)',
      at: now,
    };
    setMessages((prev) => [...prev, userMsg, agentMsg]);
    setDraft('');
    toast.success('대화 입력을 전송했습니다.');
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
        {messages.map((m) => (
          <ChatBubble key={m.id} message={m} />
        ))}
      </div>
      <div className="border-border bg-surface-raised flex items-end gap-2 rounded-[var(--radius-md)] border p-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          rows={2}
          placeholder={intervention.placeholder}
          className="text-foreground placeholder:text-muted-foreground max-h-28 min-h-0 flex-1 resize-none bg-transparent text-[length:var(--text-body-sm)] outline-none"
        />
        <Button size="icon" onClick={send} aria-label="전송" disabled={!draft.trim()}>
          <RiSendPlaneLine size={15} aria-hidden />
        </Button>
      </div>
      <p className="text-foreground-tertiary -mt-1 flex items-center gap-1 text-[10px]">
        <RiCornerDownLeftLine size={11} aria-hidden /> Enter 전송 · Shift+Enter 줄바꿈
      </p>
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const isAgent = message.role === 'agent';
  return (
    <div className={cn('flex gap-2', isAgent ? 'justify-start' : 'justify-end')}>
      {isAgent ? (
        <span
          aria-hidden
          className="bg-accent/10 text-accent mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full"
        >
          <RiSparkling2Line size={12} />
        </span>
      ) : null}
      <div className={cn('max-w-[78%]', isAgent ? '' : 'items-end')}>
        <div
          className={cn(
            'rounded-[var(--radius-md)] px-3 py-2 text-[length:var(--text-body-sm)] leading-relaxed',
            isAgent
              ? 'bg-muted text-foreground rounded-tl-sm'
              : 'bg-accent text-accent-foreground rounded-tr-sm',
          )}
        >
          {message.text}
        </div>
        <p
          className={cn(
            'text-foreground-tertiary mt-1 text-[10px]',
            isAgent ? 'text-left' : 'text-right',
          )}
        >
          {formatRelativeKorean(message.at)}
        </p>
      </div>
    </div>
  );
}
