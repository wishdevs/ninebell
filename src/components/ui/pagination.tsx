'use client';

import { RiArrowLeftSLine, RiArrowRightSLine } from '@remixicon/react';
import { cn } from '@/lib/utils';

interface PaginationProps {
  /** 1-indexed 현재 페이지. */
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

/**
 * 페이지 버튼 배열(1-indexed)을 만든다 — 첫/끝·현재±1 을 노출하고 그 사이는 생략('…').
 * 예) page=6, last=12 → [1, '…', 5, 6, 7, '…', 12].
 */
function pageItems(page: number, last: number): (number | 'ellipsis')[] {
  if (last <= 7) return Array.from({ length: last }, (_, i) => i + 1);
  const items: (number | 'ellipsis')[] = [1];
  const start = Math.max(2, page - 1);
  const end = Math.min(last - 1, page + 1);
  if (start > 2) items.push('ellipsis');
  for (let p = start; p <= end; p += 1) items.push(p);
  if (end < last - 1) items.push('ellipsis');
  items.push(last);
  return items;
}

const arrowClass =
  'inline-flex h-8 w-8 items-center justify-center rounded-sm border border-border bg-surface text-foreground-secondary transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none disabled:pointer-events-none disabled:opacity-40';

/**
 * 번호형 페이지네이션 — 총 건수 라벨 + '‹ 1 … n ›' 컨트롤. 현재 페이지를 강조하고
 * 경계에서 ‹/› 를 비활성화한다. total==0 이면 렌더하지 않는다.
 */
export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const last = Math.max(1, Math.ceil(total / pageSize));
  if (total === 0) return null;

  const go = (p: number) => {
    const clamped = Math.min(last, Math.max(1, p));
    if (clamped !== page) onPageChange(clamped);
  };

  return (
    <nav
      aria-label="페이지 탐색"
      className="flex flex-wrap items-center justify-between gap-3 pt-1"
    >
      <p className="text-muted-foreground text-[length:var(--text-body-sm)]">
        총 <span className="text-foreground font-medium tabular-nums">{total}</span>건
      </p>

      <div className="flex items-center gap-1">
        <button
          type="button"
          className={arrowClass}
          onClick={() => go(page - 1)}
          disabled={page <= 1}
          aria-label="이전 페이지"
        >
          <RiArrowLeftSLine size={16} aria-hidden />
        </button>

        {pageItems(page, last).map((item, i) =>
          item === 'ellipsis' ? (
            <span
              key={`ellipsis-${i}`}
              className="text-foreground-tertiary inline-flex h-8 w-8 items-center justify-center text-sm"
              aria-hidden
            >
              …
            </span>
          ) : (
            <button
              key={item}
              type="button"
              onClick={() => go(item)}
              aria-current={item === page ? 'page' : undefined}
              className={cn(
                'focus-visible:ring-accent focus-visible:ring-offset-background inline-flex h-8 min-w-8 items-center justify-center rounded-sm border px-2 text-sm tabular-nums transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none',
                item === page
                  ? 'border-accent bg-accent text-accent-foreground font-semibold shadow-sm'
                  : 'border-border bg-surface text-foreground-secondary hover:bg-muted',
              )}
            >
              {item}
            </button>
          ),
        )}

        <button
          type="button"
          className={arrowClass}
          onClick={() => go(page + 1)}
          disabled={page >= last}
          aria-label="다음 페이지"
        >
          <RiArrowRightSLine size={16} aria-hidden />
        </button>
      </div>
    </nav>
  );
}
