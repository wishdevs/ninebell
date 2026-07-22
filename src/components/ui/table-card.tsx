import type { ReactNode } from 'react';

/**
 * 목록 테이블 카드 셸 — 카드 래퍼(overflow-x-auto)·<table>·thead 클래스를 단일 소유한다
 * (members-table ↔ audit ↔ logs 에 자구 동일하게 복제돼 있던 셸 3줄 흡수). tbody 행 렌더는
 * children 으로 화면 자유 — 확장행·체크박스·인라인 편집 셀렉트를 그대로 수용한다.
 * Th/Td(table-cell.tsx)는 head/children 안에서 그대로 재사용.
 */

interface TableCardProps {
  /** 가로 스크롤 최소폭(px) — members 1000 / logs 900 / audit 820. */
  minWidth: number;
  /** <tr><Th>…</Th></tr> — thead 클래스는 TableCard 가 소유. */
  head: ReactNode;
  /** <tbody> 행들 — 확장행·체크박스·인라인 셀렉트 등 화면 자유. */
  children: ReactNode;
  /** table 의 aria-label. */
  ariaLabel?: string;
}

/** 행 공통 클래스 — 화면이 cn()으로 확장한다(선택 강조·cursor-pointer 등). */
export const tableRowClass = 'border-border-subtle row-hover border-b last:border-0';

export function TableCard({ minWidth, head, children, ariaLabel }: TableCardProps) {
  return (
    <div className="border-border bg-surface overflow-x-auto rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
      {/* min-w 는 화면마다 달라 Tailwind JIT 로 못 만든다 — 인라인 style 로 px 지정. */}
      <table aria-label={ariaLabel} className="w-full text-left text-sm" style={{ minWidth }}>
        <thead className="border-border text-foreground-tertiary border-b text-[length:var(--text-caption)] font-medium tracking-[0.04em]">
          {head}
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
