'use client';

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { ChipSet } from '@/components/ui/chip-set';
import { cn } from '@/lib/utils';
import { RiCloseLine } from '@remixicon/react';

/**
 * Minimal contract for a filter that can be rendered as a removable chip
 * with an inline editor popover. Compatible with `works/filter-types`'s
 * `FilterDefinition` shape — that one extends this with no extra fields,
 * so callers in the works package can pass their `FilterDefinition[]`
 * directly without conversion.
 */
export interface FilterChipDefinition {
  /** Stable identifier (URL query key etc.). */
  key: string;
  label: string;
  /** Whether this filter is currently applied. Inactive filters are skipped. */
  isActive: boolean;
  /** Short text shown after `${label}: ` on the chip body. */
  summary: string;
  /** Called when the chip's X button is clicked — should clear the filter. */
  onClear: () => void;
  /** Editor rendered inside the popover when the chip body is clicked. */
  renderEditor: () => ReactNode;
}

interface FilterChipBarProps {
  filters: ReadonlyArray<FilterChipDefinition>;
  /** Optional hint text shown when no filters are active. */
  emptyHint?: string;
}

/**
 * Notion-style filter chip row. Renders only `isActive=true` filters as
 * label+value chips with a click-to-edit popover and a trailing X to
 * clear. Lives at `components/ui/` so non-works surfaces (admin tables,
 * audit log filters, etc.) can adopt the same idiom without re-rolling
 * outside-click + ESC handling.
 */
export function FilterChipBar({ filters, emptyHint }: FilterChipBarProps) {
  const activeFilters = filters.filter((f) => f.isActive);

  if (activeFilters.length === 0) {
    if (emptyHint) {
      return <p className="text-foreground-tertiary text-xs">{emptyHint}</p>;
    }
    return null;
  }

  return (
    <ChipSet>
      {activeFilters.map((filter) => (
        <FilterChip key={filter.key} filter={filter} />
      ))}
    </ChipSet>
  );
}

interface FilterChipProps {
  filter: FilterChipDefinition;
}

function FilterChip({ filter }: FilterChipProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative inline-flex">
      <span
        className={cn(
          'border-border bg-surface-raised inline-flex items-center gap-1 rounded-[var(--radius-md)] border text-xs',
          open && 'border-foreground/20',
        )}
      >
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={panelId}
          className="text-foreground hover:bg-muted/60 inline-flex items-center gap-1 rounded-l-[var(--radius-md)] px-2 py-1 transition-colors"
        >
          <span className="text-muted-foreground">{filter.label}</span>
          <span aria-hidden className="text-muted-foreground">
            :
          </span>
          <span className="text-foreground max-w-[14rem] truncate">{filter.summary}</span>
        </button>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            filter.onClear();
          }}
          aria-label={`${filter.label} 필터 제거`}
          className="text-muted-foreground hover:text-foreground hover:bg-muted/60 inline-flex h-full items-center rounded-r-[var(--radius-md)] px-1.5 transition-colors"
        >
          <RiCloseLine size={12} aria-hidden />
        </button>
      </span>

      {open ? (
        <div
          id={panelId}
          role="dialog"
          aria-label={`${filter.label} 편집`}
          className="border-border bg-surface absolute top-full left-0 z-20 mt-1.5 min-w-[260px] rounded-[var(--radius-md)] border p-2 shadow-[var(--shadow-overlay)]"
        >
          {filter.renderEditor()}
        </div>
      ) : null}
    </div>
  );
}
