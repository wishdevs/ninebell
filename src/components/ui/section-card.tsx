import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

type SectionCardDensity = 'compact' | 'comfortable';

interface SectionCardProps {
  /** Eyebrow above the title (uppercase, tracked). Optional. */
  caption?: ReactNode;
  /** Section title rendered as an `<h2>`. Optional — omit for headerless cards. */
  title?: ReactNode;
  /** Optional right-aligned slot in the header — e.g. legend, filter chip. */
  action?: ReactNode;
  /** Optional supporting line below the title. */
  description?: ReactNode;
  /** `aria-labelledby` target id when callers need to label the section explicitly. */
  titleId?: string;
  /**
   * `compact` (default) matches the GA bento blocks (`gap-4 p-5`).
   * `comfortable` matches the wider org settings sections (`gap-5 p-6`).
   */
  density?: SectionCardDensity;
  /** Card body. */
  children: ReactNode;
  /** Override the outer `<section>` className when callers need extra layout. */
  className?: string;
}

/**
 * Canonical surface for a self-contained card. Locks in the design
 * tokens so every card across GA, monitoring, organization, and
 * playbook surfaces shares the same border, radius, shadow.
 *
 * The header slot is optional — when caption/title/action/description
 * are all omitted, only the body renders so this can wrap totally
 * custom interiors without forcing an empty `<header>`.
 *
 * Density is the one knob that varies in the wild:
 * - `compact` (default): `gap-4 p-5` — fits dashboard bento blocks.
 * - `comfortable`: `gap-5 p-6` — fits long-form settings sections.
 */
export function SectionCard({
  caption,
  title,
  action,
  description,
  titleId,
  density = 'compact',
  children,
  className,
}: SectionCardProps) {
  const hasHeader = Boolean(caption || title || action || description);
  return (
    <section
      aria-labelledby={titleId && title ? titleId : undefined}
      className={cn(
        'border-border bg-surface flex flex-col rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]',
        density === 'compact' ? 'gap-4 p-5' : 'gap-5 p-6',
        className,
      )}
    >
      {hasHeader ? (
        <header className="flex items-baseline justify-between gap-3">
          <div className="grid gap-1">
            {caption ? (
              <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
                {caption}
              </p>
            ) : null}
            {title ? (
              <h2
                id={titleId}
                className={cn(
                  'font-semibold tracking-tight',
                  density === 'comfortable' ? 'text-lg' : 'text-base',
                )}
              >
                {title}
              </h2>
            ) : null}
            {description ? (
              <p
                className={cn(
                  'text-muted-foreground',
                  density === 'comfortable' ? 'text-sm' : 'text-xs',
                )}
              >
                {description}
              </p>
            ) : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </header>
      ) : null}
      <div
        className={cn(
          'flex min-h-0 flex-1 flex-col',
          density === 'comfortable' ? 'gap-5' : 'gap-4',
        )}
      >
        {children}
      </div>
    </section>
  );
}
