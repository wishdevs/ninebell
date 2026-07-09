'use client';

import { RiArrowLeftSLine, RiArrowRightSLine, RiCalendarLine } from '@remixicon/react';
import { useMemo, useState } from 'react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

/**
 * 디자인 날짜 선택기 — 네이티브 <input type="date"> 대체(디자인 시스템 팔레트/팝오버).
 *
 * Radix Popover(포털) 위에 월 달력을 그린다 → 표/그리드 셀 안에서도 잘리지 않는다.
 * 값/출력은 로컬 기준 'yyyy-mm-dd'(문자열). TZ 밀림 방지 위해 toISOString 을 쓰지 않고
 * 연·월·일을 직접 조합한다.
 */

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'] as const;

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** 연·월(0-base)·일 → 'yyyy-mm-dd'. */
function toIso(y: number, m0: number, d: number): string {
  return `${y}-${pad2(m0 + 1)}-${pad2(d)}`;
}

/** 'yyyy-mm-dd' → {y, m0, d} | null(형식 불일치). */
function parseIso(v: string): { y: number; m0: number; d: number } | null {
  const mt = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (!mt) return null;
  return { y: Number(mt[1]), m0: Number(mt[2]) - 1, d: Number(mt[3]) };
}

interface DatePickerProps {
  /** 선택값 'yyyy-mm-dd'(빈 문자열이면 미선택). */
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
}

export function DatePicker({ value, onChange, disabled, ariaLabel, className }: DatePickerProps) {
  const [open, setOpen] = useState(false);
  // 보기 기준 월 — 선택값 있으면 그 달, 없으면 오늘.
  const [view, setView] = useState<{ y: number; m0: number }>(() => {
    const p = parseIso(value);
    if (p) return { y: p.y, m0: p.m0 };
    const now = new Date();
    return { y: now.getFullYear(), m0: now.getMonth() };
  });

  const todayIso = useMemo(() => {
    const n = new Date();
    return toIso(n.getFullYear(), n.getMonth(), n.getDate());
  }, []);

  // 이번 달 셀(앞쪽 공백 + 1..말일, 7의 배수로 채움).
  const cells = useMemo(() => {
    const startWeekday = new Date(view.y, view.m0, 1).getDay(); // 0=일
    const daysInMonth = new Date(view.y, view.m0 + 1, 0).getDate();
    const out: (number | null)[] = [];
    for (let i = 0; i < startWeekday; i += 1) out.push(null);
    for (let d = 1; d <= daysInMonth; d += 1) out.push(d);
    while (out.length % 7 !== 0) out.push(null);
    return out;
  }, [view]);

  const openChange = (o: boolean) => {
    setOpen(o);
    if (o) {
      const p = parseIso(value);
      if (p) setView({ y: p.y, m0: p.m0 }); // 열 때 선택월로 동기화.
    }
  };

  const prevMonth = () =>
    setView((v) => (v.m0 === 0 ? { y: v.y - 1, m0: 11 } : { y: v.y, m0: v.m0 - 1 }));
  const nextMonth = () =>
    setView((v) => (v.m0 === 11 ? { y: v.y + 1, m0: 0 } : { y: v.y, m0: v.m0 + 1 }));

  const pick = (d: number) => {
    onChange(toIso(view.y, view.m0, d));
    setOpen(false);
  };

  const hasValue = parseIso(value) != null;

  return (
    <Popover open={open} onOpenChange={openChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={ariaLabel}
          className={cn(
            'border-border bg-surface flex h-10 w-full items-center justify-between gap-2 rounded-sm border px-3 text-left text-sm outline-none',
            'focus-visible:border-accent focus-visible:ring-accent focus-visible:ring-2',
            'disabled:cursor-not-allowed disabled:opacity-50',
            className,
          )}
        >
          <span
            className={cn(
              'min-w-0 truncate tabular-nums',
              hasValue ? 'text-foreground' : 'text-muted-foreground/60',
            )}
          >
            {hasValue ? value : '날짜 선택'}
          </span>
          <RiCalendarLine size={15} aria-hidden className="text-foreground-tertiary shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-3">
        <div className="mb-2 flex items-center justify-between">
          <button
            type="button"
            onClick={prevMonth}
            aria-label="이전 달"
            className="text-foreground-tertiary hover:text-foreground hover:bg-muted/60 rounded-sm p-1 transition-colors"
          >
            <RiArrowLeftSLine size={18} aria-hidden />
          </button>
          <span className="text-foreground text-sm font-semibold tabular-nums">
            {view.y}. {pad2(view.m0 + 1)}
          </span>
          <button
            type="button"
            onClick={nextMonth}
            aria-label="다음 달"
            className="text-foreground-tertiary hover:text-foreground hover:bg-muted/60 rounded-sm p-1 transition-colors"
          >
            <RiArrowRightSLine size={18} aria-hidden />
          </button>
        </div>
        <div className="grid grid-cols-7 gap-0.5">
          {WEEKDAYS.map((w, i) => (
            <span
              key={w}
              className={cn(
                'flex h-7 items-center justify-center text-[11px] font-medium',
                i === 0
                  ? 'text-danger/80'
                  : i === 6
                    ? 'text-accent/80'
                    : 'text-foreground-tertiary',
              )}
            >
              {w}
            </span>
          ))}
          {cells.map((d, i) => {
            if (d == null) return <span key={`empty-${i}`} />;
            const iso = toIso(view.y, view.m0, d);
            const selected = iso === value;
            const isToday = iso === todayIso;
            return (
              <button
                key={iso}
                type="button"
                onClick={() => pick(d)}
                aria-pressed={selected}
                className={cn(
                  'flex h-8 w-8 items-center justify-center rounded-sm text-[13px] tabular-nums transition-colors',
                  selected
                    ? 'bg-accent text-accent-foreground font-semibold'
                    : 'text-foreground hover:bg-muted/70',
                  !selected && isToday ? 'ring-border-strong ring-1' : '',
                )}
              >
                {d}
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
