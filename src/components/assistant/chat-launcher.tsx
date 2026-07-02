'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { RiCloseLine, RiSparkling2Line } from '@remixicon/react';
import { cn } from '@/lib/utils';
import { ChatPanel } from './chat-panel';

/**
 * 우하단 플로팅 버블 — 도킹된 대화 패널을 연다. 전용 `/assistant` 화면에서는 숨긴다.
 * fixed 배치라 DOM 위치는 중요치 않지만, usePermissions/user 컨텍스트 접근을 위해
 * 인증 셸(UserProvider) 내부에 마운트한다.
 */
export function ChatLauncher() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  if (pathname === '/assistant') return null;

  return (
    <>
      {open ? (
        <div
          id="assistant-panel"
          role="dialog"
          aria-label="AI 어시스턴트"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              setOpen(false);
            }
          }}
          className="border-border bg-surface fixed right-4 bottom-20 z-40 flex h-[560px] w-[min(380px,calc(100vw-2rem))] flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-overlay)]"
        >
          <div className="border-border flex items-center justify-between border-b px-4 py-2.5">
            <span className="text-foreground flex items-center gap-2 text-[13px] font-semibold">
              <RiSparkling2Line size={16} aria-hidden className="text-accent" />
              AI 어시스턴트
            </span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-muted-foreground hover:bg-muted grid size-7 place-items-center rounded-[var(--radius-sm)] transition-colors"
              aria-label="닫기"
            >
              <RiCloseLine size={16} aria-hidden />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            <ChatPanel layout="docked" />
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="assistant-panel"
        className={cn(
          'bg-accent text-accent-foreground fixed right-4 bottom-4 z-40 grid size-12 place-items-center rounded-full shadow-[var(--shadow-overlay)] transition-transform hover:scale-105',
        )}
        aria-label="AI 어시스턴트 열기"
      >
        {open ? <RiCloseLine size={20} aria-hidden /> : <RiSparkling2Line size={20} aria-hidden />}
      </button>
    </>
  );
}
