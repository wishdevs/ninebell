'use client';

import type { ReactNode } from 'react';
import { RiCheckLine } from '@remixicon/react';
import { cn } from '@/lib/utils';
import { formatInteger } from '@/lib/data/format';
import type { BomPart } from './model';

/**
 * 구매발주 계획서 공용 조각 — 섹션 헤더·컴팩트 표 셀·트리 체크박스·부품 표.
 *
 * 표(Th/Td)는 11px 컴팩트 규격(LiveGridCard·tax-invoice 시뮬레이션과 동일) — ERP 그리드를
 * 비추는 자리라 규격을 어긋내지 않는다. 선택/활성 표시는 테두리+배경만 쓰고 바깥 ring 은
 * 그리지 않는다(스크롤 컨테이너에서 잘린다 — LiveChoiceCard 주석 참조).
 */

// ── 섹션 헤더(단계 안내) ─────────────────────────────────────────────────────

/** 섹션 제목 + 안내 한 줄 — pre-run 폼의 제목/설명 문법과 같은 중립 헤더. */
export function SimSectionHeader({ title, prompt }: { title: string; prompt?: ReactNode }) {
  return (
    <div className="min-w-0 shrink-0">
      <p className="text-foreground text-[length:var(--text-body-lg)] leading-snug font-semibold">
        {title}
      </p>
      {prompt ? (
        <p className="text-foreground-secondary mt-0.5 text-[length:var(--text-body-sm)] leading-relaxed">
          {prompt}
        </p>
      ) : null}
    </div>
  );
}

// ── 컴팩트 표 셀 ─────────────────────────────────────────────────────────────

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

// ── 트리 체크박스 ────────────────────────────────────────────────────────────

interface RowCheckboxProps {
  checked: boolean;
  indeterminate?: boolean;
  disabled?: boolean;
  onClick: () => void;
  label: string;
}

/**
 * 테이블 셀 체크박스 — members-table RowCheckbox(role=checkbox, mixed=흰색 바) 패턴의
 * 로컬 복제. 클릭 타깃을 24px(size-6)로 맞추고 시각 박스(size-4)는 원본 규격을 유지한다.
 */
export function RowCheckbox({
  checked,
  indeterminate = false,
  disabled = false,
  onClick,
  label,
}: RowCheckboxProps) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? 'mixed' : checked}
      aria-label={label}
      disabled={disabled}
      // 행 전체 클릭도 토글이라(모듈 풀), 버블을 막지 않으면 버튼+행이 각각 토글해 상쇄된다
      // (tax-invoice invoice-list-step 의 stopPropagation 과 같은 이유).
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="flex size-6 shrink-0 items-center justify-center disabled:cursor-not-allowed"
    >
      <span
        aria-hidden
        className={cn(
          'flex size-4 items-center justify-center rounded-[var(--radius-sm)] border transition-colors',
          checked || indeterminate
            ? 'border-accent bg-accent text-white'
            : 'border-border-strong bg-surface hover:border-border',
          disabled && 'border-border bg-muted/60 opacity-60',
        )}
      >
        {checked ? (
          <RiCheckLine size={11} aria-hidden />
        ) : indeterminate ? (
          <span aria-hidden className="h-[2px] w-[8px] bg-white" />
        ) : null}
      </span>
    </button>
  );
}

// ── 미니 칩(거래처 구성 등) ──────────────────────────────────────────────────

export function MiniChip({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'warn';
}) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full px-1.5 py-px text-[10px] font-medium whitespace-nowrap',
        tone === 'warn' ? 'bg-warning/10 text-warning' : 'bg-muted/70 text-foreground-secondary',
      )}
    >
      {children}
    </span>
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

// ── 부품 표(확장 행 공용) ────────────────────────────────────────────────────

/**
 * 부품 목록 — 모듈 풀 확장 행과 발주단위 카드의 '부품 보기'가 같은 표를 쓴다.
 * 확장 행 안에 들어가므로 옅은 배경 + 들여쓰기(pl)로 트리 하위임을 표시한다.
 */
export function PartsTable({ parts }: { parts: readonly BomPart[] }) {
  return (
    <div className="bg-muted/20 py-1.5 pr-2 pl-8">
      <table className="w-full min-w-[760px] border-collapse text-[11px]">
        <thead className="text-foreground-tertiary">
          <tr>
            <Th>품목코드</Th>
            <Th>품목명</Th>
            <Th>규격</Th>
            <Th>단위</Th>
            <Th className="text-right">요청잔량</Th>
            <Th className="text-right">단가</Th>
            <Th className="text-right">금액</Th>
            <Th>거래처</Th>
          </tr>
        </thead>
        <tbody>
          {parts.map((p) => (
            <tr key={p.itemCode} className="border-border-subtle border-t align-middle">
              <Td className="text-foreground-tertiary font-mono whitespace-nowrap">{p.itemCode}</Td>
              <Td className="text-foreground-secondary">{p.name}</Td>
              <Td className="text-foreground-tertiary">{p.spec}</Td>
              <Td className="text-foreground-tertiary whitespace-nowrap">{p.unit}</Td>
              <Td className="text-foreground-secondary text-right tabular-nums">{p.remainQty}</Td>
              <Td className="text-foreground-secondary text-right whitespace-nowrap tabular-nums">
                {formatInteger(p.unitPrice)}
              </Td>
              <Td className="text-foreground-secondary text-right whitespace-nowrap tabular-nums">
                {formatInteger(p.amount)}
              </Td>
              <Td className="text-foreground-secondary whitespace-nowrap">{p.vendorClass}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
