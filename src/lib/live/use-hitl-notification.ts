'use client';

import { useEffect, useRef } from 'react';
import { toast } from 'sonner';

/** 개입 대기 중 탭 제목 접두어 — 백그라운드 탭에서도 입력 대기가 보이게 한다. */
const TITLE_PREFIX = '● 입력 필요 — ';

/**
 * 브라우저 알림 권한 1회 요청. 실행 시작 버튼 클릭 등 사용자 제스처 컨텍스트에서
 * 호출해야 브라우저가 프롬프트를 띄운다. 미지원/이미 결정(granted·denied)이면 무시.
 */
export function requestHitlNotificationPermission(): void {
  if (typeof window === 'undefined' || !('Notification' in window)) return;
  if (Notification.permission !== 'default') return;
  try {
    void Notification.requestPermission().catch(() => {
      /* denied 등은 조용히 무시 */
    });
  } catch {
    /* 구형 콜백 시그니처 등 — 조용히 무시 */
  }
}

/** 탭이 실제로 보이는 포커스 상태인지 — 이때는 브라우저 알림이 불필요하다. */
function isTabFocused(): boolean {
  return document.visibilityState === 'visible' && document.hasFocus();
}

/**
 * 개입(HITL) 대기 알림 훅 — 개입이 도착해 사용자 입력을 기다리면:
 * - 탭 제목 앞에 "● 입력 필요 — " 접두(해소·세션 종료 시 원제목 복원).
 * - 탭이 백그라운드면 브라우저 알림 1회(권한 granted 일 때만, denied/미지원 무시).
 *
 * @param hitlId 대기 중인 개입 id. 없으면(해소·미실행) null — 새 개입마다 재알림한다.
 */
export function useHitlNotification(hitlId: string | null): void {
  // 접두어를 붙이기 직전의 원제목. Next 가 라우트별로 title 을 관리하므로
  // cleanup 에서 반드시 이 값으로 되돌린다(접두어가 눌어붙는 것 방지).
  const originalTitle = useRef<string | null>(null);

  useEffect(() => {
    if (hitlId == null || typeof document === 'undefined') return;

    // 탭 제목 접두 — 연속 개입(A→B)으로 이미 붙어 있으면 원제목을 덮어쓰지 않는다.
    if (originalTitle.current == null) originalTitle.current = document.title;
    document.title = TITLE_PREFIX + originalTitle.current;

    // 인앱 토스트 — 포커스 여부와 무관하게 항상(화면을 보고 있어도 개입 도착을 명확히 인지,
    // 사용자 피드백 2026-07-05: "개입 시점인데 알람이 안 온다").
    toast.info('입력이 필요합니다', { description: '개입 탭에서 입력을 완료해 주세요.' });

    // 브라우저 알림 — 탭이 백그라운드일 때(권한 granted). 포커스 중엔 토스트가 대신한다.
    if (!isTabFocused() && 'Notification' in window && Notification.permission === 'granted') {
      try {
        new Notification('입력이 필요합니다', {
          body: '결의서 그리드 입력을 기다리는 중입니다.',
        });
      } catch {
        /* 알림 생성 실패는 치명적이지 않다 — 조용히 무시 */
      }
    }

    return () => {
      if (originalTitle.current != null) {
        document.title = originalTitle.current;
        originalTitle.current = null;
      }
    };
  }, [hitlId]);
}
