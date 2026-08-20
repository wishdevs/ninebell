'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { formatWon, parseAmount } from './model';

/**
 * 세금계산서 실행 전 폼 공용 조각 — 금액 입력·요약 수치 타일 (시뮬레이션 ui.tsx 에서 승격).
 *
 * focus-visible 링은 쓰지 않는다(2026-08-04 사용자 확정) — 포커스 링 박스가 화면에 상시
 * 노출되는 걸 원치 않는다. 입력 포커스는 테두리 색 변화로만 표시한다.
 */

const AMOUNT_INPUT_CLASS = cn(
  'border-border bg-surface text-foreground placeholder:text-muted-foreground h-10 w-full min-w-0 rounded-[var(--radius-sm)] border px-2.5 text-sm outline-none',
  'focus-visible:border-accent',
  'aria-invalid:border-danger disabled:opacity-50',
);

/**
 * 금액 입력 — 포커스 중엔 원시 숫자, 포커스가 빠지면 천단위 구분으로 보여준다.
 * (입력 중에 콤마를 끼워 넣으면 캐럿이 튀므로 blur 시점에만 포맷한다.) 음수 허용 — 취소분.
 */
export function AmountInput({
  value,
  onChange,
  ariaLabel,
  placeholder,
  invalid,
  disabled,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  ariaLabel: string;
  placeholder?: string;
  invalid?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const [focused, setFocused] = useState(false);
  const parsed = parseAmount(value);
  const display = focused || parsed === null ? value : formatWon(parsed);

  return (
    <input
      value={display}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onChange={(e) => {
        // 숫자와 선행 '-' 만 남긴다(콤마 붙여넣기도 그대로 흡수).
        const next = e.target.value.replace(/[^\d-]/g, '').replace(/(?!^)-/g, '');
        onChange(next);
      }}
      inputMode="numeric"
      aria-label={ariaLabel}
      aria-invalid={invalid || undefined}
      disabled={disabled}
      placeholder={placeholder}
      className={cn(AMOUNT_INPUT_CLASS, 'text-right tabular-nums', className)}
    />
  );
}

// ── 요약 수치 타일 ───────────────────────────────────────────────────────────

export function StatTile({
  label,
  value,
  tone = 'neutral',
  sub,
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'success' | 'warning' | 'danger';
  sub?: string;
}) {
  return (
    <div className="border-border-subtle bg-muted/40 flex min-w-0 flex-col gap-0.5 rounded-[var(--radius-md)] border px-3 py-2">
      <span className="text-foreground-tertiary text-[11px] font-semibold tracking-wide">
        {label}
      </span>
      <span
        className={cn(
          'truncate text-[17px] font-semibold tabular-nums',
          tone === 'success' && 'text-success',
          tone === 'warning' && 'text-warning',
          tone === 'danger' && 'text-danger',
          tone === 'neutral' && 'text-foreground',
        )}
      >
        {value}
      </span>
      {sub ? <span className="text-foreground-tertiary text-[11px]">{sub}</span> : null}
    </div>
  );
}
