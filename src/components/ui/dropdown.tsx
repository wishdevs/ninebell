'use client';

import { useId, useState, type ReactNode } from 'react';
import { RiCheckLine, RiArrowDownSLine } from '@remixicon/react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

export interface DropdownItem {
  /** Stable identifier — passed to `onChange`. */
  value: string;
  /** Primary line shown in the trigger and the option row. */
  label: string;
  /**
   * Optional secondary line (rendered mono / dim under the label in the
   * option row, and inline next to the label in the trigger).
   */
  description?: string;
}

export interface DropdownProps {
  /** Small uppercase kicker shown above the selected label in the trigger. */
  kicker: string;
  items: ReadonlyArray<DropdownItem>;
  /** Currently selected value. Falls back to `items[0]` if no match. */
  value: string;
  onChange: (value: string) => void;
  /** Defaults to `${kicker} 선택`. */
  ariaLabel?: string;
  /**
   * Override the trigger's value-area renderer. Default: label + optional
   * inline description in mono. Useful when a caller wants a different
   * arrangement (e.g. icon prefix).
   */
  renderTriggerValue?: (item: DropdownItem) => ReactNode;
  /** Class applied to the trigger button wrapper. */
  className?: string;
  /** Class applied to the listbox container. Default min-w-[280px]. */
  listClassName?: string;
}

/**
 * Single-select dropdown — hand-rolled selectors (`ProjectSelector`,
 * `SiteSelector`) consolidated into one primitive. Uses Radix Popover
 * internally for portal + outside-click + ESC handling; keeps native
 * `role="listbox"` / `role="option"` semantics inline so screen readers
 * still announce it as a single-selection list rather than a generic menu.
 */
export function Dropdown({
  kicker,
  items,
  value,
  onChange,
  ariaLabel,
  renderTriggerValue,
  className,
  listClassName,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const listboxId = useId();
  const active = items.find((item) => item.value === value) ?? items[0];

  if (!active) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listboxId}
          className={cn(
            'border-border bg-surface hover:bg-muted/40 flex items-center gap-3 rounded-[var(--radius-md)] border px-4 py-2.5 text-sm transition-colors',
            className,
          )}
        >
          <span className="grid text-left leading-tight">
            <span className="text-foreground-tertiary text-[10px] tracking-[0.08em] uppercase">
              {kicker}
            </span>
            <span className="text-foreground font-medium">
              {renderTriggerValue ? (
                renderTriggerValue(active)
              ) : (
                <>
                  {active.label}
                  {active.description ? (
                    <span className="text-foreground-tertiary ml-2 font-mono text-xs font-normal">
                      {active.description}
                    </span>
                  ) : null}
                </>
              )}
            </span>
          </span>
          <RiArrowDownSLine
            size={16}
            aria-hidden
            className={cn('text-foreground-tertiary transition-transform', open && 'rotate-180')}
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={4}
        className={cn('w-auto p-1', listClassName ?? 'min-w-[280px]')}
      >
        <ul
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel ?? `${kicker} 선택`}
          className="grid gap-0.5"
        >
          {items.map((item) => {
            const isActive = item.value === active.value;
            return (
              <li key={item.value}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  onClick={() => {
                    onChange(item.value);
                    setOpen(false);
                  }}
                  className="hover:bg-muted/60 flex w-full items-center justify-between gap-3 rounded-[var(--radius-sm)] px-3 py-2 text-left text-sm"
                >
                  <span className="grid">
                    <span className="text-foreground">{item.label}</span>
                    {item.description ? (
                      <span className="text-foreground-tertiary font-mono text-[11px]">
                        {item.description}
                      </span>
                    ) : null}
                  </span>
                  {isActive ? (
                    <RiCheckLine size={14} aria-hidden className="text-success shrink-0" />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
