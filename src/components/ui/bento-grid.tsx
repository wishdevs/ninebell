import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

type ColSpan = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12;

interface BentoGridProps {
  children: ReactNode;
  className?: string;
}

/**
 * 12-column responsive bento grid container. Children should be
 * `<BentoCell span={N}>` instances; below the `lg` breakpoint the
 * grid collapses to a single column so mobile reads as a vertical
 * stack — matches the topbar/sidebar breakpoint elsewhere in AX.
 */
export function BentoGrid({ children, className }: BentoGridProps) {
  return <div className={cn('grid grid-cols-1 gap-4 lg:grid-cols-12', className)}>{children}</div>;
}

interface BentoCellProps {
  /** Number of columns the cell spans on `lg` and up (1–12). */
  span: ColSpan;
  children: ReactNode;
  className?: string;
}

const COL_SPAN_CLASS: Record<ColSpan, string> = {
  1: 'lg:col-span-1',
  2: 'lg:col-span-2',
  3: 'lg:col-span-3',
  4: 'lg:col-span-4',
  5: 'lg:col-span-5',
  6: 'lg:col-span-6',
  7: 'lg:col-span-7',
  8: 'lg:col-span-8',
  9: 'lg:col-span-9',
  10: 'lg:col-span-10',
  11: 'lg:col-span-11',
  12: 'lg:col-span-12',
};

/** A cell within `<BentoGrid>` that occupies `span` columns at `lg`+. */
export function BentoCell({ span, children, className }: BentoCellProps) {
  return <div className={cn(COL_SPAN_CLASS[span], className)}>{children}</div>;
}
