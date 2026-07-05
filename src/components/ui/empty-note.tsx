import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface EmptyNoteProps {
  children: ReactNode;
  /** 상하 패딩 프리셋 — 기본 6(패널 내부), 카드 전체를 대체할 때는 10. */
  py?: 6 | 10;
  className?: string;
}

/**
 * 보더 없는 순수 텍스트 빈 상태 — 3단계 빈 상태 스펙트럼 중 가장 가벼운 티어.
 *
 * - `EmptyState` — 페이지/섹션급, 보더 + 아이콘 + 액션 슬롯.
 * - `EmptyHint` — 중첩 카드급, 점선 보더.
 * - `EmptyNote`(이 컴포넌트) — 인라인 리스트/패널 내부의 가벼운 안내, 보더 없음.
 */
export function EmptyNote({ children, py = 6, className }: EmptyNoteProps) {
  return (
    <p
      role="status"
      className={cn(
        'text-foreground-tertiary text-center text-[12px]',
        py === 10 ? 'py-10' : 'py-6',
        className,
      )}
    >
      {children}
    </p>
  );
}
