'use client';

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { RiCloseLine } from '@remixicon/react';
import { cn } from '@/lib/utils';

const noopSubscribe = () => () => {};

/** 닫힘 애니메이션 지속(ms) — globals.css `--duration-normal`·`.animate-drawer-out-right`와 일치. */
const CLOSE_MS = 200;

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  /** Sticky footer slot — pinned to the bottom of the drawer outside the scrolling body. */
  footer?: ReactNode;
}

const SIZE_CLASS: Record<NonNullable<DrawerProps['size']>, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
};

/**
 * Right-edge floating panel — mirrors `Dialog`'s mechanics (portal, SSR mount
 * guard, Escape + body scroll lock) but docks to the right edge with visible
 * top/bottom/right margins instead of centering, and plays a slide **in and
 * out** (stays mounted CLOSE_MS while the exit animation runs, unlike Dialog's
 * hard unmount). Use for entity detail views (member/row detail) opened from a list.
 */
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  size = 'md',
  footer,
}: DrawerProps) {
  const mounted = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
  // open=false 여도 닫힘 애니메이션이 끝날 때까지 마운트를 유지한다(팍 사라지지 않게).
  const [rendered, setRendered] = useState(open);
  const panelRef = useRef<HTMLDivElement>(null);
  // 열기 직전 포커스를 잡아 닫을 때 트리거로 되돌린다(오버레이 뒤로 포커스가 빠지지 않게).
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  // 마운트 수명 관리: 열리면 즉시 유지, 닫히면 CLOSE_MS 뒤 언마운트(그 사이 exit 애니메이션 재생).
  useEffect(() => {
    if (open) {
      setRendered(true);
      return;
    }
    if (!rendered) return;
    const t = window.setTimeout(() => setRendered(false), CLOSE_MS);
    return () => window.clearTimeout(t);
  }, [open, rendered]);

  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current = document.activeElement as HTMLElement | null;

    // Tab/Shift+Tab을 패널 안에서 순환시키는 포커스 트랩 — aria-modal 계약 충족.
    function trapTab(e: KeyboardEvent) {
      const panel = panelRef.current;
      if (!panel) return;
      const focusables = panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'Tab') trapTab(e);
    }

    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // 열릴 때 패널로 초기 포커스 이동(다음 틱 — 포털 마운트 후).
    const focusTimer = window.setTimeout(() => panelRef.current?.focus(), 0);

    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
      window.clearTimeout(focusTimer);
      restoreFocusRef.current?.focus?.();
    };
  }, [open, onClose]);

  if ((!open && !rendered) || !mounted) return null;

  // rendered 이지만 open=false → 닫히는 중(exit 애니메이션 재생 후 언마운트).
  const closing = !open;

  const node = (
    <div className="fixed inset-0 z-[100] flex justify-end p-3 sm:p-4">
      <div
        className={cn(
          'fixed inset-0 bg-black/40 backdrop-blur-[2px]',
          closing ? 'animate-overlay-out' : 'animate-overlay-in',
        )}
        onClick={onClose}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose();
        }}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        tabIndex={-1}
        className={cn(
          'border-border bg-surface relative flex h-full w-full max-w-[92vw] flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-overlay)] focus:outline-none',
          closing ? 'animate-drawer-out-right' : 'animate-drawer-in-right',
          SIZE_CLASS[size],
        )}
      >
        <header className="border-border flex shrink-0 items-start justify-between gap-4 border-b px-5 py-4">
          <div className="flex flex-col gap-1">
            <h2 id="drawer-title" className="text-sm font-semibold">
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
          <div className="border-border bg-surface flex shrink-0 items-center border-t px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );

  return createPortal(node, document.body);
}

interface DrawerBodyProps {
  children: ReactNode;
  className?: string;
}

/** Canonical body container for `Drawer` — mirrors `DialogBody`. */
export function DrawerBody({ children, className }: DrawerBodyProps) {
  return <div className={cn('flex flex-col gap-5 px-5 py-5', className)}>{children}</div>;
}
