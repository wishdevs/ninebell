'use client';

import { useState, type ReactNode } from 'react';
import { RiCheckLine, RiFlaskLine } from '@remixicon/react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select-dropdown';
import { cn } from '@/lib/utils';
import { formatWon, parseAmount } from './model';

/**
 * 세금계산서 시뮬레이션 공용 조각 — 단계 헤더·선택지 버튼·컴팩트 표 셀·금액 입력.
 *
 * 디자인 언어는 기존 개입 화면을 그대로 잇는다: 단계 안내는 LiveChoiceCard 의 경고톤 배너,
 * 선택지는 같은 라디오형 버튼, 리스트 표는 LiveGridCard 의 컴팩트 셀(px-2 py-1.5 · text-[11px]).
 */

// ── 단계 헤더 ────────────────────────────────────────────────────────────────

export function SimStepHeader({ title, prompt }: { title: string; prompt?: ReactNode }) {
  return (
    <div className="border-warning/30 bg-warning/10 flex shrink-0 items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
      <RiFlaskLine size={16} aria-hidden className="text-warning mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">{title}</p>
        {prompt ? (
          <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">{prompt}</p>
        ) : null}
      </div>
    </div>
  );
}

// ── 질문 한 덩어리(라벨 + 선택지) ────────────────────────────────────────────

export function QuestionBlock({
  step,
  label,
  hint,
  children,
}: {
  step: number;
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span className="bg-accent/10 text-accent inline-flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold tabular-nums">
          {step}
        </span>
        <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">{label}</p>
      </div>
      {hint ? <p className="text-foreground-tertiary pl-7 text-[11px]">{hint}</p> : null}
      <div className="flex flex-col gap-2 pl-7">{children}</div>
    </div>
  );
}

// ── 선택지 버튼(라디오형) ────────────────────────────────────────────────────

export function ChoiceOption({
  label,
  description,
  active,
  onClick,
}: {
  label: string;
  description?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'flex cursor-pointer items-center gap-3 rounded-[var(--radius-md)] border px-3 py-2.5 text-left transition-colors',
        active
          ? 'border-accent bg-accent/5 ring-accent/30 ring-2'
          : 'border-border hover:bg-muted/60',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'flex size-5 shrink-0 items-center justify-center rounded-full border',
          active ? 'border-accent bg-accent text-accent-foreground' : 'border-border-strong',
        )}
      >
        {active ? <RiCheckLine size={12} /> : null}
      </span>
      <span className="min-w-0">
        <span className="text-foreground block text-[length:var(--text-body-sm)] font-medium">
          {label}
        </span>
        {description ? (
          <span className="text-foreground-tertiary block text-[11px]">{description}</span>
        ) : null}
      </span>
    </button>
  );
}

// ── 컴팩트 표 셀(LiveGridCard 규격) ──────────────────────────────────────────

export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <th scope="col" className={cn('px-2 py-1.5 font-semibold whitespace-nowrap', className)}>
      {children}
    </th>
  );
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cn('px-2 py-1.5', className)}>{children}</td>;
}

// ── 셀 안 텍스트 입력(LiveGridCard 인셀 입력 규격) ───────────────────────────

const CELL_INPUT_CLASS = cn(
  'border-border bg-surface text-foreground placeholder:text-muted-foreground h-8 w-full min-w-0 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none',
  'focus-visible:border-accent focus-visible:ring-accent/40 focus-visible:ring-2',
  'aria-invalid:border-danger disabled:opacity-50',
);

export function CellInput({
  value,
  onChange,
  ariaLabel,
  placeholder,
  invalid,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  ariaLabel: string;
  placeholder?: string;
  invalid?: boolean;
  className?: string;
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel}
      aria-invalid={invalid || undefined}
      placeholder={placeholder}
      maxLength={200}
      className={cn(CELL_INPUT_CLASS, className)}
    />
  );
}

/**
 * 금액 입력 — 포커스 중엔 원시 숫자, 포커스가 빠지면 천단위 구분으로 보여준다.
 * (입력 중에 콤마를 끼워 넣으면 캐럿이 튀므로 blur 시점에만 포맷한다.) 음수 허용 — 취소분 분할.
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
      className={cn(CELL_INPUT_CLASS, 'text-right tabular-nums', className)}
    />
  );
}

// ── 선택 드롭다운(셀/폼 공용) ────────────────────────────────────────────────

export function OptionSelect({
  value,
  options,
  onChange,
  ariaLabel,
  placeholder = '선택',
  disabled,
  invalid,
  size = 'cell',
}: {
  value: string;
  options: readonly string[];
  onChange: (v: string) => void;
  ariaLabel: string;
  placeholder?: string;
  disabled?: boolean;
  invalid?: boolean;
  size?: 'cell' | 'form';
}) {
  return (
    <Select value={value || undefined} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger
        aria-label={ariaLabel}
        aria-invalid={invalid || undefined}
        className={cn(
          'w-full min-w-0 rounded-[var(--radius-sm)]',
          size === 'cell' ? 'h-8 text-[11px]' : 'h-10 text-sm',
          invalid && 'border-danger',
        )}
      >
        <SelectValue placeholder={placeholder} className="min-w-0 flex-1 truncate text-left" />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o} value={o}>
            {o}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
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
      <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
        {label}
      </span>
      <span
        className={cn(
          'truncate text-base font-semibold tabular-nums',
          tone === 'success' && 'text-success',
          tone === 'warning' && 'text-warning',
          tone === 'danger' && 'text-danger',
          tone === 'neutral' && 'text-foreground',
        )}
      >
        {value}
      </span>
      {sub ? <span className="text-foreground-tertiary text-[10px]">{sub}</span> : null}
    </div>
  );
}
