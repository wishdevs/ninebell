'use client';

import type { ReactNode } from 'react';
import { RiCloseLine } from '@remixicon/react';

/**
 * 목록 필터 툴바 셸 — 반응형 셸 + isFiltered 일 때만 노출되는 rounded-full 초기화 버튼을
 * 단일 소유한다(members-filter-bar ↔ audit ↔ logs 자구 중복 흡수). SearchInput·FilterPill 등은
 * children 으로 화면이 자유 배치한다. "전 화면 공통 기능"의 1차 착지 지점 — 내보내기(CSV)
 * 버튼·저장된 필터 등이 생기면 이 컴포넌트에 추가하면 전 목록 화면이 동시에 받는다.
 */

interface ListToolbarProps {
  /** useListParams().isFiltered — true 일 때만 초기화 버튼 노출. */
  isFiltered: boolean;
  onReset: () => void;
  /** SearchInput·FilterPill 등 자유 배치. */
  children: ReactNode;
}

export function ListToolbar({ isFiltered, onReset, children }: ListToolbarProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      {children}
      {isFiltered ? (
        <button
          type="button"
          onClick={onReset}
          className="text-foreground-tertiary hover:text-foreground-secondary inline-flex h-9 items-center gap-1 rounded-full px-2.5 text-[length:var(--text-body-sm)] font-medium transition-colors"
        >
          <RiCloseLine size={14} aria-hidden />
          초기화
        </button>
      ) : null}
    </div>
  );
}
