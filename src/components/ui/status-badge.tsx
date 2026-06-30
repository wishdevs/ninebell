import { RiLoader4Line } from '@remixicon/react';
import { cn } from '@/lib/utils';

/**
 * Shared status vocabulary for GEO batch + run lifecycle surfaces.
 *
 * The tone maps below translate each status into a design-token pairing so
 * the badge stays theme-safe — the underlying `--success` / `--warning` /
 * `--danger` / `--accent` / `--muted` tokens are already branched for
 * light/dark in ``globals.css``.
 */
export type StatusBadgeStatus =
  'completed' | 'failed' | 'cancelled' | 'running' | 'pending' | 'paused' | 'batch_submitted';

type Tone = 'success' | 'warning' | 'danger' | 'info' | 'accent' | 'muted';

const TONE_CLASSES: Record<Tone, string> = {
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  danger: 'bg-danger/10 text-danger',
  info: 'bg-info/10 text-info',
  accent: 'bg-accent/10 text-accent',
  muted: 'bg-muted text-muted-foreground',
};

const STATUS_TONE: Record<StatusBadgeStatus, Tone> = {
  completed: 'success',
  failed: 'danger',
  cancelled: 'muted',
  running: 'info',
  pending: 'muted',
  paused: 'warning',
  batch_submitted: 'info',
};

const STATUS_LABEL: Record<StatusBadgeStatus, string> = {
  completed: '완료',
  failed: '실패',
  cancelled: '취소',
  running: '실행 중',
  pending: '대기',
  paused: '일시정지',
  // Provider Batch API typically returns within 24h. Surface that
  // expectation directly so the user does not assume the run is stuck.
  batch_submitted: '처리 중 — 24시간 내 완료 예정',
};

export function getStatusLabel(status: string): string {
  return (STATUS_LABEL as Record<string, string>)[status] ?? status;
}

/**
 * Terminal lifecycle statuses — once a batch lands here it never moves
 * again, so consumers (delete-buttons, polling loops) can stop watching.
 */
export const TERMINAL_BATCH_STATUSES: ReadonlyArray<StatusBadgeStatus> = [
  'completed',
  'failed',
  'cancelled',
];

export function isTerminalBatchStatus(status: string): boolean {
  return (TERMINAL_BATCH_STATUSES as readonly string[]).includes(status);
}

export interface StatusBadgeProps {
  /**
   * Canonical lifecycle status. Unknown values fall back to the `pending`
   * tone + the raw string as the label so new backend-side states don't
   * render as blank.
   */
  status: string;
  /**
   * When true the badge swaps in a spinner + the caller-provided "running"
   * label, regardless of the `status` prop — used by `batch-detail` to
   * surface a live worker's heartbeat while the row is still PENDING.
   */
  isRunning?: boolean;
  /**
   * Optional N/M counter appended after the "실행 중" label when
   * `isRunning` is set. Hidden when `totalRuns <= 0`.
   */
  completedRuns?: number;
  totalRuns?: number;
  /** Tailwind size tokens — defaults match the original inline styles. */
  size?: 'sm' | 'md';
  className?: string;
}

/**
 * StatusBadge — batch / run lifecycle indicator
 * (completed / failed / cancelled / running / pending / paused /
 * batch_submitted). Renders a tone-mapped colored badge with optional
 * spinner + N/M counter while running. Used in GEO batch and work-sync run
 * surfaces. For ad-hoc info / warning chips (e.g. "이메일 미인증") use
 * `StatusPill` from `status-pill.tsx` instead.
 */
export function StatusBadge({
  status,
  isRunning = false,
  completedRuns,
  totalRuns,
  size = 'sm',
  className,
}: StatusBadgeProps) {
  const normalized = (status in STATUS_TONE ? status : 'pending') as StatusBadgeStatus;
  const tone: Tone = isRunning ? STATUS_TONE.running : STATUS_TONE[normalized];
  const label = isRunning ? STATUS_LABEL.running : getStatusLabel(status);

  const sizeClass =
    size === 'md'
      ? 'px-2.5 py-1 text-[11px] leading-none font-semibold gap-1.5'
      : 'px-2 py-0.5 text-[10px] leading-none font-semibold';

  const showCounter = isRunning && typeof totalRuns === 'number' && totalRuns > 0;

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full',
        sizeClass,
        TONE_CLASSES[tone],
        className,
      )}
    >
      {isRunning ? <RiLoader4Line size={11} className="animate-spin" /> : null}
      {label}
      {showCounter ? (
        <span className="font-mono tabular-nums">
          {' '}
          {completedRuns ?? 0}/{totalRuns}
        </span>
      ) : null}
    </span>
  );
}
