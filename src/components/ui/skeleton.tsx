import { cn } from '@/lib/utils';

type SkeletonShape = 'rect' | 'circle' | 'text';

interface SkeletonProps {
  /** `rect` (default) for blocks, `circle` for avatars, `text` for inline lines. */
  shape?: SkeletonShape;
  /**
   * Tailwind classes that set the width/height for this skeleton —
   * e.g. `'h-3 w-24'` for a text line, `'h-9 w-9'` for an avatar.
   *
   * Pass full Tailwind class names (not template-string fragments) so
   * the v4 scanner picks them up at build time.
   */
  className?: string;
}

const SHAPE_CLASS: Record<SkeletonShape, string> = {
  rect: 'rounded',
  circle: 'rounded-full',
  text: 'h-3 rounded',
};

/**
 * Pulsing placeholder for content that hasn't loaded yet. Locks in the
 * `bg-muted animate-pulse` styling so every skeleton in AX shares the
 * same rhythm and tone.
 *
 * The component itself is purely decorative — wrap a group of
 * skeletons in a container with `role="status"` and `aria-busy` if SR
 * users need to know the surrounding region is loading.
 */
export function Skeleton({ shape = 'rect', className }: SkeletonProps) {
  return (
    <span
      aria-hidden
      className={cn('bg-muted block animate-pulse', SHAPE_CLASS[shape], className)}
    />
  );
}
