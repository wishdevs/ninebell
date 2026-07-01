'use client';

import { useState } from 'react';
import { RiCheckLine, RiHand, RiSendPlaneLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import type { HitlPayload, LiveHitl } from '@/lib/live/types';
import { cn } from '@/lib/utils';

interface LiveChoiceCardProps {
  hitl: LiveHitl;
  /** 응답 전달 — 부모가 sendHitl(hitl.id, payload) 로 바인딩. */
  onSubmit: (payload: HitlPayload) => Promise<boolean>;
}

/**
 * 옵션형 HITL 응답 카드 — kind=confirm/select(단일)·multiselect(다중)·input/search(자유입력).
 * demo-echo 의 `confirm`(예/아니요)을 포함해 대화형이 아닌 개입을 처리한다.
 * 단일 선택은 클릭 즉시 제출(빠른 확인 UX), 다중/자유입력은 확인 버튼으로 제출한다.
 */
export function LiveChoiceCard({ hitl, onSubmit }: LiveChoiceCardProps) {
  const options = hitl.options ?? [];
  const isMulti = hitl.kind === 'multiselect';
  const isText = hitl.kind === 'input' || hitl.kind === 'search';
  const allowText = hitl.allowText || isText;

  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(payload: HitlPayload) {
    if (busy) return;
    setBusy(true);
    setError(null);
    const ok = await onSubmit(payload);
    // 성공 시 흐름이 재개돼 result/다음 HITL 프레임이 카드를 교체한다.
    if (!ok) {
      setError('응답을 전달하지 못했습니다(흐름이 종료됐을 수 있음).');
      setBusy(false);
    }
  }

  function toggle(value: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  }

  const textPayload = (): HitlPayload =>
    hitl.kind === 'search' ? { query: text.trim() } : { text: text.trim() };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="border-warning/30 bg-warning/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
        <RiHand size={16} aria-hidden className="text-warning mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            {hitl.title}
          </p>
          {hitl.prompt ? (
            <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">
              {hitl.prompt}
            </p>
          ) : null}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {options.map((opt) => {
          const active = checked.has(opt.value);
          return (
            <button
              key={opt.value}
              type="button"
              disabled={busy}
              aria-pressed={isMulti ? active : undefined}
              onClick={() => (isMulti ? toggle(opt.value) : void submit({ value: opt.value }))}
              className={cn(
                'flex items-center gap-3 rounded-[var(--radius-md)] border px-3 py-2.5 text-left transition-colors disabled:opacity-60',
                active
                  ? 'border-accent bg-accent/5 ring-accent/30 ring-2'
                  : 'border-border hover:bg-muted/60',
              )}
            >
              <span
                aria-hidden
                className={cn(
                  'flex size-5 shrink-0 items-center justify-center border',
                  isMulti ? 'rounded-[var(--radius-sm)]' : 'rounded-full',
                  active
                    ? 'border-accent bg-accent text-accent-foreground'
                    : 'border-border-strong',
                )}
              >
                {active ? <RiCheckLine size={12} /> : null}
              </span>
              <span className="min-w-0">
                <span className="text-foreground flex items-center gap-1.5 text-[length:var(--text-body-sm)] font-medium">
                  {opt.label}
                  {opt.recommended ? (
                    <span className="bg-accent/10 text-accent rounded-full px-1.5 py-0.5 text-[9px] font-bold">
                      추천
                    </span>
                  ) : null}
                </span>
                {opt.description ? (
                  <span className="text-foreground-tertiary block text-[11px]">
                    {opt.description}
                  </span>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>

      {allowText ? (
        <div className="border-border bg-surface-raised flex items-end gap-2 rounded-[var(--radius-md)] border p-2">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && text.trim()) {
                e.preventDefault();
                void submit(textPayload());
              }
            }}
            disabled={busy}
            placeholder={hitl.searchPlaceholder ?? hitl.textLabel ?? '직접 입력…'}
            className="text-foreground placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-[length:var(--text-body-sm)] outline-none disabled:opacity-50"
          />
          <Button
            size="icon"
            aria-label="전송"
            disabled={!text.trim() || busy}
            onClick={() => void submit(textPayload())}
          >
            <RiSendPlaneLine size={15} aria-hidden />
          </Button>
        </div>
      ) : null}

      {isMulti ? (
        <Button
          size="sm"
          disabled={busy || checked.size === 0}
          onClick={() => void submit({ values: [...checked] })}
          className="w-full"
        >
          <RiCheckLine size={14} aria-hidden />
          선택 확인 ({checked.size})
        </Button>
      ) : null}

      {error ? <span className="text-danger text-[12px]">{error}</span> : null}
    </div>
  );
}
