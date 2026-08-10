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
 *
 * **타이포 규칙(2026-08-04 가독성 개편)** — 실측 결과 이 화면의 고유 문구 103개 중 77개가
 * 11px 이하였고, 정작 "결정에 쓰는" 질문·선택지가 13px 로 보조 문구와 구분되지 않았다.
 * 그래서 위계를 크기로 다시 세운다:
 *   질문 20px/700 > 선택지 라벨 15px/600 > 선택지 설명·본문 13px > 메타 라벨 11px
 * 표(Th/Td)만 예외로 11px 를 유지한다 — ERP 그리드를 그대로 비추는 자리라 LiveGridCard 와
 * 규격이 어긋나면 안 되기 때문이다. 대신 표 **안의 입력 위젯**은 12px/h-9 로 올린다.
 */

/** 결정에 직접 쓰는 텍스트 — 질문 문구. 화면에서 가장 큰 글자여야 한다. */
export const QUESTION_TEXT_CLASS = 'text-[20px] leading-snug font-bold tracking-tight';

// ── 단계 헤더 ────────────────────────────────────────────────────────────────

export function SimStepHeader({ title, prompt }: { title: string; prompt?: ReactNode }) {
  return (
    <div className="border-warning/30 bg-warning/10 flex shrink-0 items-start gap-2.5 rounded-[var(--radius-md)] border px-3.5 py-2.5">
      <RiFlaskLine size={18} aria-hidden className="text-warning mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-foreground text-[length:var(--text-body-lg)] leading-snug font-semibold">
          {title}
        </p>
        {prompt ? (
          <p className="text-foreground-secondary mt-1 text-[length:var(--text-body-sm)] leading-relaxed">
            {prompt}
          </p>
        ) : null}
      </div>
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
        // py-3 + 15px 라벨 → 실측 높이 ≥48px. 터치 타깃 권장치(44×44)를 카드 자체로 만족한다.
        'flex cursor-pointer items-center gap-3 rounded-[var(--radius-md)] border px-3.5 py-3 text-left transition-colors',
        'focus-visible:ring-accent focus-visible:ring-2 focus-visible:ring-offset-2',
        'focus-visible:ring-offset-background focus-visible:outline-none',
        active
          ? 'border-accent bg-accent/5 ring-accent/30 ring-2'
          : 'border-border hover:border-accent/50 hover:bg-muted/60',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'flex size-6 shrink-0 items-center justify-center rounded-full border',
          active ? 'border-accent bg-accent text-accent-foreground' : 'border-border-strong',
        )}
      >
        {active ? <RiCheckLine size={15} /> : null}
      </span>
      <span className="min-w-0">
        <span className="text-foreground block text-[15px] leading-snug font-semibold">
          {label}
        </span>
        {description ? (
          <span className="text-foreground-secondary mt-0.5 block text-[length:var(--text-body-sm)] leading-snug">
            {description}
          </span>
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

// 표 자체는 11px 밀도를 유지하되, **직접 타이핑하는 입력 위젯**은 12px/h-9 로 올린다
// — 입력 중 자기가 친 값을 확인하는 자리라 정적 셀보다 한 단계 크게 둔다.
const CELL_INPUT_CLASS = cn(
  'border-border bg-surface text-foreground placeholder:text-muted-foreground h-9 w-full min-w-0 rounded-[var(--radius-sm)] border px-2 text-[12px] outline-none',
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
          size === 'cell' ? 'h-9 text-[12px]' : 'h-10 text-sm',
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
