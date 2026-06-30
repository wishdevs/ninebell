'use client';

import { useEffect, useSyncExternalStore, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { RiCloseLine } from '@remixicon/react';
import { cn } from '@/lib/utils';

const noopSubscribe = () => () => {};

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  /** Sticky footer slot — pinned to the bottom of the dialog outside
   *  the scrolling body. Use this for action rows (확인/취소) so they
   *  stay visible regardless of how long the body content grows.
   *  When omitted, dialogs render exactly as before. */
  footer?: ReactNode;
}

const SIZE_CLASS: Record<NonNullable<DialogProps['size']>, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-xl',
  // xl is reserved for table-heavy review surfaces (e.g. CSV/paste import
  // preview) where the default lg width truncates content columns.
  xl: 'max-w-5xl',
};

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  size = 'md',
  footer,
}: DialogProps) {
  const mounted = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );

  useEffect(() => {
    if (!open) return;

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }

    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open || !mounted) return null;

  const node = (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div
        className="fixed inset-0 bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose();
        }}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        className={cn(
          'border-border bg-surface animate-page-enter relative flex max-h-[90vh] w-full flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-overlay)]',
          SIZE_CLASS[size],
        )}
      >
        <header className="border-border flex shrink-0 items-start justify-between border-b px-5 py-4">
          <div className="flex flex-col gap-1">
            <h2 id="dialog-title" className="text-sm font-semibold">
              {title}
            </h2>
            {description ? (
              <p className="text-muted-foreground text-[11px]">{description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground shrink-0 rounded-[var(--radius-sm)] p-1 transition-colors"
            aria-label="닫기"
          >
            <RiCloseLine size={16} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto">{children}</div>
        {footer ? (
          <div className="border-border bg-surface flex shrink-0 items-center justify-end gap-2 border-t px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );

  return createPortal(node, document.body);
}

interface DialogBodyProps {
  children: ReactNode;
  className?: string;
}

/**
 * Canonical body container for `Dialog`. Always applies `px-5 py-5` so
 * callers can't silently skip padding. The default `flex flex-col gap-5`
 * matches the most common dialog body layout; override via `className`
 * when a form needs its own grid/gap.
 */
export function DialogBody({ children, className }: DialogBodyProps) {
  return <div className={cn('flex flex-col gap-5 px-5 py-5', className)}>{children}</div>;
}
