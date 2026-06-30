import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface ShowcaseProps {
  /** Uppercase eyebrow above the inset panel. Optional. */
  label?: string;
  children: ReactNode;
  className?: string;
}

/**
 * Inset showcase panel used inside the design-system SectionCards.
 *
 * Renders a labelled, bordered well on `bg-background` so demoed
 * components sit one layer below the surrounding `bg-surface` card —
 * giving the page a sense of depth instead of flat stacked rows.
 */
export function Showcase({ label, children, className }: ShowcaseProps) {
  return (
    <div className="flex flex-col gap-2">
      {label ? (
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          {label}
        </p>
      ) : null}
      <div
        className={cn(
          'border-border bg-background flex flex-wrap items-center gap-4 rounded-[var(--radius-md)] border p-5',
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}
