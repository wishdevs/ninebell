'use client';

import Link from 'next/link';
import { LogOut, Moon, Sun, User as UserIcon } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useTheme } from '@/components/theme-provider';
import { CURRENT_USER } from '@/lib/data/workspace';
import { cn } from '@/lib/utils';

const TRIGGER_DIM = 'h-7 w-7';
const PANEL_WIDTH = 'w-[280px]';

function avatarInitial(name: string): string {
  return name.trim() ? name.trim()[0].toUpperCase() : '?';
}

/**
 * 토프바 우측 사용자 메뉴 — 계정 설정 링크, 테마 토글, 로그아웃.
 * 기본형은 로그아웃이 로그인 페이지로 이동만 하고 세션 처리는 없다.
 */
export function UserMenu() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
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
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`${CURRENT_USER.fullName} (${CURRENT_USER.email})`}
        className={cn(
          'group relative flex shrink-0 items-center justify-center overflow-hidden rounded-full transition-[box-shadow] duration-[var(--duration-fast)]',
          TRIGGER_DIM,
          'focus-visible:outline-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2',
          open ? 'ring-border ring-2' : 'hover:ring-border hover:ring-2',
        )}
      >
        <span
          aria-hidden
          className="from-accent to-accent/70 text-accent-foreground flex h-full w-full items-center justify-center rounded-full bg-gradient-to-br text-xs font-semibold tracking-tight"
        >
          {avatarInitial(CURRENT_USER.fullName)}
        </span>
      </button>

      {open ? (
        <div
          id={panelId}
          role="menu"
          className={cn(
            'border-border bg-surface absolute top-full right-0 z-20 mt-1.5 flex flex-col overflow-hidden rounded-[var(--radius-md)] border shadow-[var(--shadow-card)]',
            PANEL_WIDTH,
          )}
        >
          <div className="flex items-center gap-2.5 px-3 py-3">
            <span
              aria-hidden
              className="from-accent to-accent/70 text-accent-foreground flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-xs font-semibold tracking-tight"
            >
              {avatarInitial(CURRENT_USER.fullName)}
            </span>
            <div className="min-w-0 flex-1">
              <p
                className="text-foreground truncate text-[length:var(--text-body)] leading-tight font-semibold"
                title={CURRENT_USER.fullName}
              >
                {CURRENT_USER.fullName}
              </p>
              <p
                className="text-foreground-tertiary truncate text-[length:var(--text-caption)] leading-tight"
                title={CURRENT_USER.email}
              >
                {CURRENT_USER.email}
              </p>
            </div>
            <ThemeToggleIcon />
          </div>

          <div className="border-border border-t" />

          <Link
            href="/settings"
            className="text-foreground hover:bg-muted flex items-center gap-2.5 px-3 py-2 text-[length:var(--text-body)] transition-colors duration-[var(--duration-fast)]"
          >
            <UserIcon
              size={16}
              strokeWidth={1.75}
              aria-hidden
              className="text-foreground-tertiary shrink-0"
            />
            <span>계정 설정</span>
          </Link>

          <div className="border-border border-t" />

          <Link
            href="/login"
            className="text-foreground hover:bg-muted flex w-full items-center gap-2.5 px-3 py-2 text-left text-[length:var(--text-body)] transition-colors duration-[var(--duration-fast)]"
          >
            <LogOut
              size={16}
              strokeWidth={1.75}
              aria-hidden
              className="text-foreground-tertiary shrink-0"
            />
            <span>로그아웃</span>
          </Link>
        </div>
      ) : null}
    </div>
  );
}

function ThemeToggleIcon() {
  const { resolvedTheme, setTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';
  return (
    <button
      type="button"
      aria-label="테마 전환"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      suppressHydrationWarning
      className="text-foreground-tertiary hover:bg-muted hover:text-foreground focus-visible:outline-accent flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] transition-colors duration-[var(--duration-fast)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <Sun size={14} aria-hidden className="hidden dark:block" />
      <Moon size={14} aria-hidden className="block dark:hidden" />
    </button>
  );
}
