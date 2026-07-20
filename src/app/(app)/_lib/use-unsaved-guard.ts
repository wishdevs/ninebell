'use client';

import { useEffect } from 'react';

/**
 * 미저장 변경 이탈 가드. `active`(변경 있음)일 때만 동작한다.
 * - 브라우저 새로고침/닫기/외부 URL: `beforeunload` 네이티브 프롬프트.
 * - 앱 내 링크(Next `<Link>`=`<a>`) 이동: 캡처 단계 클릭 인터셉트 → `confirm` → 취소 시 이동 차단.
 * 프로그램적 router.push 는 대상이 아니다(사이드바 등 링크 이동을 커버).
 */
const MESSAGE = '저장하지 않은 변경사항이 있습니다. 이 페이지를 벗어나시겠어요?';

export function useUnsavedGuard(active: boolean): void {
  useEffect(() => {
    if (!active) return;

    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = ''; // 일부 브라우저는 returnValue 설정을 요구.
    };

    const onClickCapture = (event: MouseEvent) => {
      if (event.defaultPrevented) return;
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return; // 새 탭/보조 클릭은 통과.
      }
      const target = event.target as HTMLElement | null;
      const anchor = target?.closest?.('a');
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (!href || !href.startsWith('/') || anchor.target === '_blank') return;
      if (href === window.location.pathname) return; // 현재 페이지면 무시.
      if (!window.confirm(MESSAGE)) {
        event.preventDefault();
        event.stopPropagation(); // 캡처 단계에서 막아 Next 링크 네비게이션까지 차단.
      }
    };

    window.addEventListener('beforeunload', onBeforeUnload);
    document.addEventListener('click', onClickCapture, true);
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload);
      document.removeEventListener('click', onClickCapture, true);
    };
  }, [active]);
}
