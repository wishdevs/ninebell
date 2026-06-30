import { cn } from '@/lib/utils';

interface EmptyStateProps {
  /** Optional icon rendered above the title (e.g. lucide icon). */
  icon?: React.ReactNode;
  /** Main message — should explain *what* is empty in one short sentence. */
  title: string;
  /** Optional secondary line — tone-down explanation or hint. */
  description?: React.ReactNode;
  /** Action slot — typically a `<Button>` (or several). */
  action?: React.ReactNode;
  /** Override the dashed-surface variant for nested or compact contexts. */
  variant?: 'dashed' | 'solid';
  /** Tightens vertical padding for nested cards / table-bound empty states. */
  compact?: boolean;
  className?: string;
}

/**
 * Canonical empty-state container.
 *
 * Visual language follows the design-system showcase: dashed border,
 * surface background, centered text, generous vertical padding. Use this
 * any time a list / grid / page has zero rows so the look stays consistent.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  variant = 'dashed',
  compact = false,
  className,
}: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn(
        'border-border bg-surface flex flex-col items-center gap-3 rounded-[var(--radius-lg)] border text-center',
        variant === 'dashed' ? 'border-dashed' : '',
        compact ? 'px-4 py-8' : 'p-10',
        className,
      )}
    >
      {icon ? (
        <span
          aria-hidden
          className="bg-muted text-muted-foreground flex h-10 w-10 items-center justify-center rounded-full"
        >
          {icon}
        </span>
      ) : null}
      <p className="text-foreground text-sm font-medium">{title}</p>
      {description ? (
        <p className="text-muted-foreground max-w-prose text-xs leading-relaxed">{description}</p>
      ) : null}
      {action ? (
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">{action}</div>
      ) : null}
    </div>
  );
}
