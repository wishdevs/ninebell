import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface PageHeaderProps {
  /** Required page title rendered as `<h1>`. */
  title: ReactNode;
  /** Optional eyebrow caption above the title (rendered uppercase, tracked). */
  caption?: ReactNode;
  /** Optional supporting description below the title. */
  description?: ReactNode;
  /** Optional right-aligned action slot — e.g. a primary button. */
  action?: ReactNode;
  /** Override the outer `<header>` className when callers need extra spacing. */
  className?: string;
}

/**
 * Canonical page header for AX surfaces.
 *
 * Two layouts in one component:
 * - When `action` is provided: responsive flex (column on mobile, row with
 *   `items-end justify-between` from `md` up). The text group uses
 *   `grid gap-1.5` so caption, title, and description sit tight.
 * - When `action` is omitted: plain `grid gap-2` block — same visual rhythm
 *   the boilerplate has used since v1.0.0.
 *
 * Typography tokens are pinned to the design system: caption uses
 * `var(--text-caption)`, title uses `var(--text-section)`. Description
 * defaults to `text-sm leading-relaxed` and clamps at `max-w-2xl` so long
 * paragraphs stay scannable. Pass a styled `ReactNode` for the rare cases
 * that need a wider/narrower clamp.
 */
export function PageHeader({ title, caption, description, action, className }: PageHeaderProps) {
  const text = (
    <div className={cn('grid', action ? 'gap-1.5' : 'gap-2')}>
      {caption ? (
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          {caption}
        </p>
      ) : null}
      <h1 className="text-[length:var(--text-section)] leading-tight font-semibold tracking-tight">
        {title}
      </h1>
      {description ? (
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">{description}</p>
      ) : null}
    </div>
  );

  if (action) {
    return (
      <header
        className={cn('flex flex-col gap-4 md:flex-row md:items-end md:justify-between', className)}
      >
        {text}
        <div className="shrink-0">{action}</div>
      </header>
    );
  }

  return <header className={className}>{text}</header>;
}
