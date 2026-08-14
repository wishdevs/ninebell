'use client';

import { useEffect } from 'react';

/**
 * 미저장 변경 이탈 가드. `active`(변경 있음)일 때만 동작한다.
 * - 브라우저 새로고침/닫기/외부 URL: `beforeunload` 네이티브 프롬프트.
 * - 앱 내 링크(Next `<Link>`=`<a>`) 이동: 캡처 단계 클릭 인터셉트 → `confirm` → 취소 시 이동 차단.
 * - 브라우저 뒤로/앞으로(SPA back/forward): sentinel 트랩 + `popstate` `confirm`(최선노력 —
 *   App Router 는 정식 네비게이션 가드 API 가 없어 히스토리 훅으로 우회한다).
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

    // 뒤로가기 가드(최선노력 App Router 핵) — beforeunload 는 같은-오리진 SPA back/forward 엔
    // 발화하지 않는다. active 되면 현재 URL 로 히스토리 항목을 하나 더 쌓아 '트랩'을 놓고, popstate 가
    // 뜨면 confirm 으로 확인한다. 남으면(취소) sentinel 을 재적재해 다시 트랩하고, 떠나면(확인) 실제
    // back() 으로 이전 페이지로 보낸다. 브라우저별 편차가 있어 완벽하진 않다(트랩 항목 1개가 남을 수 있음).
    window.history.pushState(null, '', window.location.href);
    const onPopState = () => {
      if (window.confirm(MESSAGE)) {
        window.removeEventListener('popstate', onPopState); // back() 재진입 방지 후 실제 이동.
        window.history.back();
      } else {
        window.history.pushState(null, '', window.location.href); // 남음 — 트랩 재적재.
      }
    };

    window.addEventListener('beforeunload', onBeforeUnload);
    document.addEventListener('click', onClickCapture, true);
    window.addEventListener('popstate', onPopState);
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload);
      document.removeEventListener('click', onClickCapture, true);
      window.removeEventListener('popstate', onPopState);
    };
  }, [active]);
}
