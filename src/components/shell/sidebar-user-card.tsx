'use client';

import Link from 'next/link';
import {
  RiExpandUpDownLine,
  RiLogoutBoxRLine,
  RiMoonLine,
  RiSunLine,
  RiUserLine as UserIcon,
} from '@remixicon/react';
import { useEffect, useId, useRef, useState } from 'react';
import { useTheme } from '@/components/theme-provider';
import { useCurrentUser } from '@/app/(app)/providers/user-provider';
import { cn } from '@/lib/utils';

function avatarInitial(name: string): string {
  return name.trim() ? name.trim()[0].toUpperCase() : '?';
}

/**
 * 사이드바 하단 사용자 카드 — 토프바에 있던 아바타/사용자 메뉴를 카드 형태로
 * 옮긴 것. 카드를 누르면 위쪽으로 메뉴(계정 설정 · 테마 전환 · 로그아웃)가 열린다.
 */
export function SidebarUserCard() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const user = useCurrentUser();

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="border-border relative shrink-0 border-t p-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={panelId}
        className={cn(
          'border-border bg-surface-raised flex w-full items-center gap-2.5 rounded-[var(--radius-md)] border px-2.5 py-2 text-left shadow-[var(--shadow-card)] transition-colors duration-[var(--duration-fast)]',
          open ? 'bg-muted ring-accent/30 ring-2' : 'hover:bg-muted/60',
        )}
      >
        <span
          aria-hidden
          className="from-accent to-accent/70 text-accent-foreground flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-xs font-semibold tracking-tight"
        >
          {avatarInitial(user.displayName)}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className="text-foreground block truncate text-[length:var(--text-body)] leading-tight font-semibold"
            title={user.displayName}
          >
            {user.displayName}
          </span>
          <span
            className="text-foreground-tertiary block truncate text-[length:var(--text-caption)] leading-tight"
            title={user.email ?? user.omnisolUserid}
          >
            {user.email ?? user.omnisolUserid}
          </span>
        </span>
        <RiExpandUpDownLine size={13} aria-hidden className="text-foreground-tertiary shrink-0" />
      </button>

      {open ? (
        <div
          id={panelId}
          role="menu"
          className="border-border bg-surface absolute right-3 bottom-full left-3 z-30 mb-2 flex flex-col overflow-hidden rounded-[var(--radius-md)] border shadow-[var(--shadow-overlay)]"
        >
          <Link
            href="/account"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="text-foreground hover:bg-muted flex items-center gap-2.5 px-3 py-2 text-[length:var(--text-body)] transition-colors duration-[var(--duration-fast)]"
          >
            <UserIcon size={16} aria-hidden className="text-foreground-tertiary shrink-0" />
            <span>계정 설정</span>
          </Link>

          <ThemeToggleItem />

          <div className="border-border border-t" />

          <Link
            href="/login"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="text-foreground hover:bg-muted flex items-center gap-2.5 px-3 py-2 text-[length:var(--text-body)] transition-colors duration-[var(--duration-fast)]"
          >
            <RiLogoutBoxRLine size={16} aria-hidden className="text-foreground-tertiary shrink-0" />
            <span>로그아웃</span>
          </Link>
        </div>
      ) : null}
    </div>
  );
}

function ThemeToggleItem() {
  const { resolvedTheme, setTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';
  return (
    <button
      type="button"
      role="menuitem"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      suppressHydrationWarning
      className="text-foreground hover:bg-muted flex items-center gap-2.5 px-3 py-2 text-left text-[length:var(--text-body)] transition-colors duration-[var(--duration-fast)]"
    >
      <span className="text-foreground-tertiary shrink-0">
        <RiSunLine size={16} aria-hidden className="hidden dark:block" />
        <RiMoonLine size={16} aria-hidden className="block dark:hidden" />
      </span>
      <span suppressHydrationWarning>{isDark ? '라이트 모드' : '다크 모드'}</span>
    </button>
  );
}
