'use client';

import { RiMenuLine } from '@remixicon/react';
import { useEffect, useState } from 'react';
import { useMobileNav } from './mobile-nav-context';

const TIME_FMT = new Intl.DateTimeFormat('ko-KR', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

/**
 * 모바일 전용 슬림 바 — 데스크톱에서는 숨긴다(공간 절약). 사이드바가 드로어로
 * 숨겨지는 모바일에서만 햄버거 + 간단한 시계를 노출한다.
 */
export function Topbar() {
  const { openDrawer } = useMobileNav();
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="border-border/40 bg-surface/70 sticky top-0 z-40 flex h-12 shrink-0 items-center justify-between gap-2 border-b px-[var(--grid-gutter)] backdrop-blur-xl md:hidden">
      <button
        type="button"
        onClick={openDrawer}
        className="border-border text-foreground hover:bg-muted -ml-1 inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] border transition-colors"
        aria-label="메뉴 열기"
      >
        <RiMenuLine size={16} aria-hidden />
      </button>
      <span
        suppressHydrationWarning
        className="text-foreground-secondary inline-flex items-center gap-1.5 text-[length:var(--text-body-sm)] font-semibold tabular-nums"
      >
        <span aria-hidden className="bg-success size-1.5 animate-pulse rounded-full" />
        {now ? TIME_FMT.format(now) : '--:--'}
      </span>
    </header>
  );
}
