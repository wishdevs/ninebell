'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { RiCloseLine, RiSparkling2Line } from '@remixicon/react';
import { cn } from '@/lib/utils';
import { ChatPanel } from './chat-panel';

/**
 * 우하단 플로팅 버블 — 도킹된 대화 패널을 연다. 전용 `/assistant` 화면에서는 숨긴다.
 * fixed 배치라 DOM 위치는 중요치 않지만, usePermissions/user 컨텍스트 접근을 위해
 * 인증 셸(UserProvider) 내부에 마운트한다.
 *
 * 패널은 첫 열림 이후 계속 마운트해 두고 `hidden` 으로만 숨긴다 — 닫아도 대화 내역과
 * 진행 중인 스트림이 보존되어 실수 클릭 한 번에 응답이 사라지지 않는다. 열기 전까지는
 * 마운트하지 않아 /agents·/runs 를 불필요하게 호출하지 않는다.
 */
export function ChatLauncher() {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();
  const panelRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) setMounted(true);
  }, [open]);

  // 열릴 때 패널로 포커스를 옮겨 키보드 사용자가 다이얼로그 안에 들어오게 한다(Escape·Tab 트랩이
  // 실제로 동작하려면 포커스가 패널 내부에 있어야 함). 첫 열림은 마운트 직후에 포커스한다.
  useEffect(() => {
    if (open && mounted) panelRef.current?.focus();
  }, [open, mounted]);

  const close = useCallback(() => {
    setOpen(false);
    toggleRef.current?.focus();
  }, []);

  if (pathname === '/assistant') return null;

  return (
    <>
      {mounted ? (
        <div
          ref={panelRef}
          id="assistant-panel"
          role="dialog"
          aria-modal="true"
          aria-label="AI 어시스턴트"
          tabIndex={-1}
          hidden={!open}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              close();
              return;
            }
            if (e.key === 'Tab') {
              const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
                'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])',
              );
              if (!focusables || focusables.length === 0) return;
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
          }}
          className="border-border bg-surface fixed right-4 bottom-20 z-40 flex h-[560px] w-[min(380px,calc(100vw-2rem))] flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-overlay)] outline-none"
        >
          <div className="border-border flex items-center justify-between border-b px-4 py-2.5">
            <span className="text-foreground flex items-center gap-2 text-[13px] font-semibold">
              <RiSparkling2Line size={16} aria-hidden className="text-accent" />
              AI 어시스턴트
            </span>
            <button
              type="button"
              onClick={close}
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
        ref={toggleRef}
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
