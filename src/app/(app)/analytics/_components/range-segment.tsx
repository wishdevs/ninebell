'use client';

import { RANGE_LABEL, type AnalyticsRange } from '@/lib/data/analytics';
import { cn } from '@/lib/utils';

const RANGES: readonly AnalyticsRange[] = ['7d', '28d', '90d'];

interface RangeSegmentProps {
  value: AnalyticsRange;
  onChange: (next: AnalyticsRange) => void;
}

/**
 * 기간 세그먼트 컨트롤. 선택된 탭은 `bg-accent/15 text-accent`로 강조한다.
 * 라벨은 `RANGE_LABEL`(최근 7일/28일/90일)을 그대로 사용한다.
 */
export function RangeSegment({ value, onChange }: RangeSegmentProps) {
  return (
    <div
      role="tablist"
      aria-label="기간 선택"
      className="border-border bg-surface inline-flex items-center gap-0.5 rounded-[var(--radius-md)] border p-0.5 text-xs shadow-[var(--shadow-card)]"
    >
      {RANGES.map((range) => {
        const selected = range === value;
        return (
          <button
            key={range}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(range)}
            className={cn(
              'rounded-[var(--radius-sm)] px-3 py-1.5 font-medium transition-colors duration-[var(--duration-fast)]',
              selected
                ? 'bg-accent/15 text-accent'
                : 'text-foreground-secondary hover:text-foreground hover:bg-muted',
            )}
          >
            {RANGE_LABEL[range]}
          </button>
        );
      })}
    </div>
  );
}
