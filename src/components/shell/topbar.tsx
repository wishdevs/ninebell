'use client';

import { Menu } from 'lucide-react';
import { useMobileNav } from './mobile-nav-context';
import { UserMenu } from './user-menu';

/**
 * 상단 고정 바 — 모바일 햄버거 + 우측 사용자 메뉴.
 * 원본의 알림 벨/페르소나 칩 등 백엔드 의존 요소는 제거.
 */
export function Topbar() {
  const { openDrawer } = useMobileNav();

  return (
    <header className="border-border/40 bg-surface/70 sticky top-0 z-40 flex h-14 shrink-0 items-center justify-between gap-2 border-b px-[var(--grid-gutter)] shadow-sm saturate-[1.2] backdrop-blur-xl transition-all duration-[var(--duration-normal)]">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={openDrawer}
          className="border-border text-foreground hover:bg-muted -ml-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border transition-colors md:hidden"
          aria-label="메뉴 열기"
        >
          <Menu size={16} strokeWidth={1.75} aria-hidden />
        </button>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <UserMenu />
      </div>
    </header>
  );
}
