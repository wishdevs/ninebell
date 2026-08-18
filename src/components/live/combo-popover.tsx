'use client';

import { useEffect, type RefObject } from 'react';
import { cn } from '@/lib/utils';

/**
 * 검색형 콤보박스 패널 공용 셸 — md 미만은 딤 배경 + 하단 바텀시트, md 이상은 트리거 아래
 * 팝오버. BudgetCombobox·ProjectCombobox·OwnerCombobox 세 곳이 같은 패턴이라 여기서만
 * 관리한다. 호출부는 relative 래퍼 안에서 `{open ? <ComboPanel …> : null}` 로 쓴다.
 */

/** md(768px) 이상 뷰포트 여부 — 모바일에선 검색 input autoFocus·자동 포커스를 생략한다
 * (가상 키보드 즉시 팝업·스크롤 점프 방지). */
export function isDesktopViewport(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(min-width: 768px)').matches;
}

/** 바깥 pointerdown 시 닫기 — mousedown 대신 pointerdown(터치·마우스 통합). */
export function useOutsideClose(
  open: boolean,
  ref: RefObject<HTMLElement | null>,
  onClose: () => void,
) {
  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: PointerEvent) => {
      if (ref.current && !ref.current.contains(ev.target as Node)) onClose();
    };
    document.addEventListener('pointerdown', onDoc);
    return () => document.removeEventListener('pointerdown', onDoc);
  }, [open, ref, onClose]);
}

export function ComboPanel({
  onClose,
  className,
  children,
}: {
  /** 딤 배경(모바일) 탭으로 닫기. 바깥 클릭 닫기는 호출부의 useOutsideClose 가 담당한다. */
  onClose: () => void;
  /** md+ 팝오버 폭 등 추가 클래스 — 예: 'md:w-[min(320px,calc(100vw-2rem))]'. */
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <>
      {/* 딤 배경은 래퍼(wrapRef) 안에 렌더돼 문서 pointerdown 닫기에 안 걸린다 — 탭 핸들러 필수.
          touch-none: 딤 위 드래그가 뒤 페이지를 스크롤시키지 않게 차단. */}
      <div
        className="fixed inset-0 z-30 touch-none bg-black/40 md:hidden"
        onClick={onClose}
        aria-hidden
      />
      <div
        className={cn(
          // md 미만: 하단 시트 — 목록이 길면 시트 안(min-h-0 flex-1 자식)에서 스크롤한다.
          'border-border bg-surface fixed inset-x-0 bottom-0 z-40 flex max-h-[70dvh] flex-col rounded-t-[var(--radius-lg)] border-t p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-[var(--shadow-card)]',
          // md 이상: 기존 팝오버 그대로.
          'md:absolute md:inset-x-auto md:bottom-auto md:left-0 md:z-20 md:mt-1 md:max-h-none md:rounded-[var(--radius-md)] md:border md:p-2 md:pb-2',
          className,
        )}
      >
        {children}
      </div>
    </>
  );
}
