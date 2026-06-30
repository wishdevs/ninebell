import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface EmptyHintProps {
  /** Optional inline icon (recommended size 12). */
  icon?: ReactNode;
  /** Short heading line — `text-foreground text-xs font-medium`. */
  title?: ReactNode;
  /** Body line — `text-muted-foreground text-[11px]`. Falls back to the
   *  whole content when `title` is omitted. */
  description?: ReactNode;
  className?: string;
}

/**
 * Tight, inline empty-state hint for side panels and sub-cards.
 *
 * Sits at the small end of the empty-state spectrum:
 * - `EmptyHint` (this) — `px-3 py-4 text-[11px]` for nested rows.
 * - `EmptyState` (compact) — `px-4 py-8` for nested cards with icon + 2 lines.
 * - `EmptyState` (default) — `p-10` for page / section-level empties.
 *
 * Unlike `EmptyState` it has no action slot — hints are passive notes,
 * not call-to-action surfaces.
 */
export function EmptyHint({ icon, title, description, className }: EmptyHintProps) {
  return (
    <div
      role="status"
      className={cn(
        'border-border-subtle text-muted-foreground flex flex-col items-center gap-1 rounded-[var(--radius-md)] border border-dashed px-3 py-4 text-center text-[11px]',
        className,
      )}
    >
      {icon ? (
        <span aria-hidden className="text-muted-foreground">
          {icon}
        </span>
      ) : null}
      {title ? <p className="text-foreground text-xs font-medium">{title}</p> : null}
      {description ? <p className="leading-relaxed">{description}</p> : null}
    </div>
  );
}
