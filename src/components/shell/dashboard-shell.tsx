import type { ReactNode } from 'react';
import { MobileNavProvider } from './mobile-nav-context';
import { Sidebar } from './sidebar';
import { Topbar } from './topbar';

/**
 * 인증된 모든 라우트가 공유하는 대시보드 크롬(사이드바 + 토프바).
 *
 * 사이드바는 좌측 고정(데스크톱) / 슬라이드인 드로어(모바일), 본문은 독립
 * 스크롤 컨테이너로 동작한다.
 */
export function DashboardShell({ children }: { children: ReactNode }) {
  return (
    <MobileNavProvider>
      <div className="bg-background flex h-dvh flex-col md:flex-row">
        <Sidebar />
        <div
          data-dashboard-scroll="true"
          className="bg-surface relative flex min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-auto"
        >
          <Topbar />
          <main className="animate-page-enter relative z-0 flex min-h-0 flex-1 flex-col px-[var(--grid-gutter)] pt-10">
            {children}
            <div aria-hidden className="pointer-events-none h-24 w-full shrink-0" />
          </main>
        </div>
      </div>
    </MobileNavProvider>
  );
}
