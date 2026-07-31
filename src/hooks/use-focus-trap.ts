'use client';

import { useEffect, type RefObject } from 'react';

/**
 * 모달 오버레이(Dialog/Drawer) 공용 포커스 트랩 — aria-modal 계약 충족.
 *
 * active 동안:
 *  · 열릴 때 패널로 초기 포커스 이동(다음 틱 — 포털 마운트 후). 패널에는
 *    `tabIndex={-1}` 이 필요하다.
 *  · Tab/Shift+Tab 을 패널 안에서 순환시켜 키보드 포커스가 배경으로 빠지지 않게 한다.
 *  · 닫힐 때 열기 직전 포커스(트리거)로 되돌린다.
 * Escape·스크롤 잠금은 각 컴포넌트가 종전대로 관리한다(트랩과 독립).
 */
export function useFocusTrap(panelRef: RefObject<HTMLElement | null>, active: boolean) {
  useEffect(() => {
    if (!active) return;
    // 열기 직전 포커스를 잡아 닫을 때 트리거로 되돌린다(오버레이 뒤로 포커스가 빠지지 않게).
    const restoreFocus = document.activeElement as HTMLElement | null;

    // Tab/Shift+Tab을 패널 안에서 순환시키는 포커스 트랩.
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
      if (e.key === 'Tab') trapTab(e);
    }

    document.addEventListener('keydown', onKey);
    // 열릴 때 패널로 초기 포커스 이동(다음 틱 — 포털 마운트 후).
    const focusTimer = window.setTimeout(() => panelRef.current?.focus(), 0);

    return () => {
      document.removeEventListener('keydown', onKey);
      window.clearTimeout(focusTimer);
      restoreFocus?.focus?.();
    };
  }, [active, panelRef]);
}
