'use client';

import { useEffect } from 'react';
import { toast } from 'sonner';

import { startTabAttention } from './tab-attention';

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

/** 탭이 실제로 보이는 포커스 상태인지 — 이때는 브라우저 알림·플래싱이 불필요하다. */
function isTabFocused(): boolean {
  return document.visibilityState === 'visible' && document.hasFocus();
}

/** 백그라운드 탭에 OS 알림 — 권한 granted 일 때만. */
function notify(title: string, body: string): void {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  try {
    // requireInteraction 은 쓰지 않는다 — macOS 알림 스타일이 '배너'면 지속 요청과 충돌해
    // 알림이 아예 안 뜨는 사례가 있다. 지속성은 탭 제목·파비콘 플래싱이 대신한다.
    new Notification(title, { body });
  } catch {
    /* 알림 생성 실패는 치명적이지 않다 — 조용히 무시 */
  }
}

/**
 * 개입(HITL) 대기 알림 훅 — 개입이 도착해 사용자 입력을 기다리면:
 * - 인앱 토스트(포커스 여부 무관 항상).
 * - 탭이 백그라운드면: 탭 제목·파비콘 **플래싱**(탭 복귀 시 자동 정지·원복) + OS 알림.
 *
 * @param hitlId 대기 중인 개입 id. 없으면(해소·미실행) null — 새 개입마다 재알림한다.
 */
export function useHitlNotification(hitlId: string | null): void {
  useEffect(() => {
    if (hitlId == null || typeof document === 'undefined') return;

    // 인앱 토스트 — 화면을 보고 있어도 개입 도착을 명확히 인지(사용자 피드백 2026-07-05).
    toast.info('입력이 필요합니다', { description: '개입 탭에서 입력을 완료해 주세요.' });

    if (isTabFocused()) return; // 보고 있으면 토스트로 충분.
    notify('입력이 필요합니다', '결의서 그리드 입력을 기다리는 중입니다.');
    return startTabAttention('🔔 입력 필요!');
  }, [hitlId]);
}

// ── 완료 알림 ────────────────────────────────────────────────────────

const TERMINAL_MESSAGE = {
  succeeded: '실행 완료 — 결과를 확인하세요',
  failed: '실행 실패 — 원인을 확인하세요',
} as const;

const TERMINAL_FLASH = {
  succeeded: '✅ 실행 완료!',
  failed: '❌ 실행 실패!',
} as const;

/**
 * 런 종료(terminal) 알림 훅 — 완료/실패를 HITL 대기와 동일 채널로 알린다:
 * - 인앱 토스트(항상).
 * - 백그라운드면: 탭 제목·파비콘 플래싱(복귀 시 자동 정지·원복) + OS 알림.
 *
 * @param status 종료 상태. 실행 중·미실행이면 null — 새 런의 종료마다 재알림한다.
 */
export function useRunTerminalNotification(status: 'succeeded' | 'failed' | null): void {
  useEffect(() => {
    if (status == null || typeof document === 'undefined') return;

    const toastFn = status === 'succeeded' ? toast.success : toast.error;
    toastFn(TERMINAL_MESSAGE[status]);

    if (isTabFocused()) return;
    notify(status === 'succeeded' ? '실행 완료' : '실행 실패', TERMINAL_MESSAGE[status]);
    return startTabAttention(TERMINAL_FLASH[status]);
  }, [status]);
}
