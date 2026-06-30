import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface SpinnerProps {
  /** Pixel size of the spinner. Defaults to 14 to match the most common AX inline use. */
  size?: number;
  /** Override stroke width. Defaults to lucide's `2`. */
  strokeWidth?: number;
  /**
   * `aria-label` announced by screen readers. When omitted the spinner
   * is hidden from assistive tech via `aria-hidden`, which is the
   * right call when adjacent text already conveys the loading state
   * (e.g. "저장 중…").
   */
  label?: string;
  className?: string;
}

/**
 * Indeterminate progress indicator. Wraps lucide `Loader2` to lock in
 * the `animate-spin` animation and the right ARIA wiring.
 *
 * - With `label`: rendered as `role="status"` so SR users hear the
 *   announcement on its own.
 * - Without `label`: rendered as `aria-hidden` decoration — the
 *   surrounding text is expected to convey the state.
 */
export function Spinner({ size = 14, strokeWidth, label, className }: SpinnerProps) {
  return (
    <Loader2
      size={size}
      strokeWidth={strokeWidth}
      role={label ? 'status' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn('animate-spin', className)}
    />
  );
}
