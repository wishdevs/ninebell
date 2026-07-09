'use client';

import * as SelectPrimitive from '@radix-ui/react-select';
import { RiArrowDownSLine } from '@remixicon/react';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

/**
 * Custom (non-native) dropdown Select built on @radix-ui/react-select.
 *
 * Use this whenever the trigger lives in a visually-dense surface (toolbars,
 * chip rails, filter bars) where opening a native OS dropdown would feel
 * jarring. For long forms, `ui/select.tsx` (native wrapper) is still the
 * right choice — it inherits OS conventions like mobile sheet pickers.
 *
 * Visual tokens come from `globals.css`: surface / border / shadow-card-raised
 * for the popover, radius-md for both trigger and content.
 */

export const Select = SelectPrimitive.Root;
export const SelectGroup = SelectPrimitive.Group;
export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = forwardRef<
  ElementRef<typeof SelectPrimitive.Trigger>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      'border-border bg-surface text-foreground inline-flex h-7 cursor-pointer items-center justify-between gap-1.5 overflow-hidden rounded-[var(--radius-md)] border px-2.5 text-[length:var(--text-body-sm)] whitespace-nowrap tabular-nums',
      'hover:bg-surface-raised hover:border-border-strong transition-colors',
      'data-[state=open]:bg-surface-raised data-[state=open]:border-border-strong',
      'focus-visible:ring-accent/40 focus-visible:ring-2 focus-visible:outline-none',
      'disabled:cursor-not-allowed disabled:opacity-50',
      className,
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <RiArrowDownSLine className="text-foreground-tertiary h-3 w-3 shrink-0" aria-hidden />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = 'SelectTrigger';

export const SelectContent = forwardRef<
  ElementRef<typeof SelectPrimitive.Content>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = 'popper', sideOffset = 6, ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      position={position}
      sideOffset={sideOffset}
      className={cn(
        'border-border bg-surface text-foreground z-50 min-w-[8rem] overflow-hidden rounded-[var(--radius-md)] border shadow-[var(--shadow-card-raised)]',
        'data-[state=open]:animate-in data-[state=closed]:animate-out',
        'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
        'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
        'data-[side=bottom]:slide-in-from-top-1 data-[side=top]:slide-in-from-bottom-1',
        className,
      )}
      {...props}
    >
      <SelectPrimitive.Viewport className="p-1">{children}</SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = 'SelectContent';

export const SelectItem = forwardRef<
  ElementRef<typeof SelectPrimitive.Item>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Item> & {
    /** 목록에만 보이는 보조 표기(트리거 SelectValue 엔 ItemText 만 반영). 예: 연비·단가. */
    hint?: ReactNode;
  }
>(({ className, children, hint, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      'text-foreground relative flex w-full cursor-pointer items-center rounded-[var(--radius-sm)] px-2 py-1 text-[length:var(--text-body-sm)] tabular-nums select-none',
      'focus:bg-muted focus:outline-none',
      'data-[state=checked]:bg-accent/10 data-[state=checked]:text-accent data-[state=checked]:font-medium',
      'data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
      className,
    )}
    {...props}
  >
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    {hint != null ? (
      <span className="text-foreground-tertiary ml-2 text-[length:var(--text-caption)] tabular-nums">
        {hint}
      </span>
    ) : null}
  </SelectPrimitive.Item>
));
SelectItem.displayName = 'SelectItem';

export const SelectLabel = forwardRef<
  ElementRef<typeof SelectPrimitive.Label>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn(
      'text-foreground-tertiary px-2 py-1.5 text-[length:var(--text-caption)] font-medium tracking-[0.04em] uppercase',
      className,
    )}
    {...props}
  />
));
SelectLabel.displayName = 'SelectLabel';

export const SelectSeparator = forwardRef<
  ElementRef<typeof SelectPrimitive.Separator>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn('bg-border-subtle -mx-1 my-1 h-px', className)}
    {...props}
  />
));
SelectSeparator.displayName = 'SelectSeparator';
