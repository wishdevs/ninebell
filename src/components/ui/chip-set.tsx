'use client';

import { X } from 'lucide-react';
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from 'react';
import { cn } from '@/lib/utils';

/**
 * ChipSet — flex-wrap container used to lay out a row of `Chip` /
 * `FilterChip` / domain-specific chip components. Single source of truth
 * for the "Notion-style chips" baseline gap and wrapping behaviour.
 */
export const ChipSet = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function ChipSet(
  { className, ...props },
  ref,
) {
  return (
    <div ref={ref} className={cn('flex flex-wrap items-center gap-1.5', className)} {...props} />
  );
});

type ChipShape = 'pill' | 'badge';

type ChipBaseProps = {
  shape?: ChipShape;
  /**
   * When true, the chip renders as a dashed empty-state placeholder
   * (used by `WorkPhaseCategoryChips` for "단계 없음" / "카테고리 없음").
   */
  dashed?: boolean;
  className?: string;
  children: ReactNode;
};

type ChipAsButton = ChipBaseProps & {
  /** When provided, the chip renders as `<button>` and fires this handler. */
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
  /**
   * Optional close handler — when supplied, an X icon is added at the
   * trailing edge that calls this and stops propagation so the chip's
   * own click handler doesn't fire.
   */
  onRemove?: (event: MouseEvent<HTMLButtonElement>) => void;
  /** Aria label for the X button. Defaults to "제거". */
  removeLabel?: string;
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onClick' | 'children' | 'className'>;

type ChipAsSpan = ChipBaseProps & {
  onClick?: undefined;
  onRemove?: undefined;
} & Omit<HTMLAttributes<HTMLSpanElement>, 'onClick' | 'children' | 'className'>;

export type ChipProps = ChipAsButton | ChipAsSpan;

const SHAPE_CLASS: Record<ChipShape, string> = {
  pill: 'rounded-full px-2 py-0.5 text-[11px]',
  badge: 'rounded-[var(--radius-md)] px-2 py-1 text-xs',
};

/**
 * Chip — atomic chip visual used by `WorkPhaseCategoryChips`,
 * `FilterChipBar`, and any future status / tag chip surfaces. Renders as
 * `<button>` when an `onClick` is supplied (interactive), otherwise as
 * `<span>`. When `onRemove` is also supplied, an inline X icon is
 * appended.
 *
 * The component intentionally does NOT own the popover/editor flow —
 * compound surfaces like `FilterChipBar` wrap their own popover state
 * around `Chip`.
 */
export const Chip = forwardRef<HTMLButtonElement | HTMLSpanElement, ChipProps>(
  function Chip(props, ref) {
    const { shape = 'pill', dashed, className, children } = props;

    const base = cn(
      'border-border inline-flex items-center gap-1 border font-medium transition-colors',
      SHAPE_CLASS[shape],
      dashed && 'border-border-subtle text-foreground-tertiary border-dashed bg-transparent',
      !dashed && 'bg-surface text-foreground',
      className,
    );

    if (typeof props.onClick === 'function') {
      const {
        onClick,
        onRemove,
        removeLabel = '제거',
        // Strip our custom props so they don't leak onto the <button>
        // and trip React's "non-boolean attribute" warning.
        shape: _shape,
        dashed: _dashed,
        className: _className,
        children: _children,
        ...rest
      } = props as ChipAsButton;
      void _shape;
      void _dashed;
      void _className;
      void _children;
      const interactive =
        'hover:bg-muted/60 cursor-pointer focus-visible:ring-accent/40 focus-visible:ring-2 focus-visible:outline-none';
      return (
        <span className="inline-flex">
          <button
            ref={ref as React.Ref<HTMLButtonElement>}
            type="button"
            onClick={onClick}
            className={cn(base, interactive, onRemove && 'rounded-r-none border-r-0 pr-1.5')}
            {...rest}
          >
            {children}
          </button>
          {onRemove ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onRemove(event);
              }}
              aria-label={removeLabel}
              className={cn(
                'border-border text-muted-foreground hover:text-foreground hover:bg-muted/60 inline-flex items-center border border-l-0 transition-colors',
                shape === 'pill' ? 'rounded-r-full px-1.5' : 'rounded-r-[var(--radius-md)] px-1.5',
              )}
            >
              <X size={12} strokeWidth={2} aria-hidden />
            </button>
          ) : null}
        </span>
      );
    }

    const {
      onClick: _omit,
      onRemove: _omitRemove,
      // Strip our custom props for the same reason as the button branch.
      shape: _shape,
      dashed: _dashed,
      className: _className,
      children: _children,
      ...rest
    } = props as ChipAsSpan & {
      onClick?: undefined;
      onRemove?: undefined;
    };
    void _omit;
    void _omitRemove;
    void _shape;
    void _dashed;
    void _className;
    void _children;
    return (
      <span ref={ref as React.Ref<HTMLSpanElement>} className={base} {...rest}>
        {children}
      </span>
    );
  },
);
