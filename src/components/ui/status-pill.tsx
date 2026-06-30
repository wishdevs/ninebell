import { cn } from '@/lib/utils';

interface StatusDotPillProps {
  active: boolean;
  labelActive?: string;
  labelInactive?: string;
  className?: string;
}

/**
 * StatusDotPill — binary on/off indicator (활성 / 비활성) with a leading dot.
 * Use for boolean account / record state where a lifecycle vocabulary is
 * overkill. For run / batch lifecycle use `StatusBadge` from `status-badge.tsx`.
 */
export function StatusDotPill({
  active,
  labelActive = '활성',
  labelInactive = '비활성',
  className,
}: StatusDotPillProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
        active ? 'bg-success/10 text-success' : 'bg-muted text-muted-foreground',
        className,
      )}
    >
      <span
        aria-hidden
        className={cn('h-1.5 w-1.5 rounded-full', active ? 'bg-success' : 'bg-muted-foreground')}
      />
      {active ? labelActive : labelInactive}
    </span>
  );
}

interface StatusPillProps {
  label: string;
  variant: 'warn' | 'info' | 'success' | 'danger';
  className?: string;
}

const STATUS_PILL_VARIANTS: Record<StatusPillProps['variant'], string> = {
  warn: 'bg-warning/10 text-warning',
  info: 'bg-accent/10 text-accent',
  success: 'bg-success/10 text-success',
  danger: 'bg-danger/10 text-danger',
};

/**
 * StatusPill — generic small chip for ad-hoc info / warnings (e.g. "이메일
 * 미인증", "승인 대기"). Caller supplies the `label` and a tone `variant`.
 * For canonical run / batch lifecycle states use `StatusBadge` from
 * `status-badge.tsx` instead — that component owns the lifecycle vocabulary
 * (completed / failed / running / pending / paused / batch_submitted) and
 * adds spinner + counter affordances.
 */
export function StatusPill({ label, variant, className }: StatusPillProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        STATUS_PILL_VARIANTS[variant],
        className,
      )}
    >
      {label}
    </span>
  );
}
