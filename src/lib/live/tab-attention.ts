'use client';

/**
 * 탭 주의 환기 — 백그라운드 탭에서 완료/개입 대기 시 **탭 제목·파비콘을 깜빡여** 시선을 끈다.
 * 탭이 다시 보이면(focus / visibilitychange) 자동으로 멈추고 원복한다. 한 번에 하나만 활성(싱글턴).
 *
 * 브라우저 크롬(도크 튐·작업표시줄 깜빡임)은 웹 API가 없어 제어 불가 → 페이지가 제어 가능한
 * 제목/파비콘 플래싱으로 대체한다. OS 알림(Notification)과 함께 쓰면 효과가 크다.
 */

const FLASH_INTERVAL_MS = 900;

// 빨간 점 파비콘(alert) — SVG data URI(외부 파일/캔버스 불필요).
const ALERT_FAVICON = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="13" fill="#ef4444"/></svg>',
)}`;

let timer: number | null = null;
let cleanup: (() => void) | null = null;

function iconLink(): HTMLLinkElement | null {
  return document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
}

/** 활성 플래싱을 멈추고 제목·파비콘을 원복한다(멱등 — 활성 아니면 no-op). */
export function stopTabAttention(): void {
  cleanup?.();
}

/**
 * 제목·파비콘 플래싱 시작. 반환값은 정지 함수(effect cleanup 에 그대로 반환하면 된다).
 * 이미 활성이면 이전 것을 먼저 정리한다(싱글턴).
 */
export function startTabAttention(flashTitle: string): () => void {
  if (typeof document === 'undefined') return () => {};
  stopTabAttention();

  const originalTitle = document.title;
  const link = iconLink();
  const originalFavicon = link?.getAttribute('href') ?? null;
  let on = false;

  const tick = () => {
    on = !on;
    document.title = on ? flashTitle : originalTitle;
    if (link) link.setAttribute('href', on ? ALERT_FAVICON : (originalFavicon ?? ''));
  };
  tick(); // 즉시 첫 프레임(대기 없이 바로 표시)
  timer = window.setInterval(tick, FLASH_INTERVAL_MS);

  const onVisible = () => {
    if (document.visibilityState === 'visible' && document.hasFocus()) stopTabAttention();
  };
  window.addEventListener('focus', onVisible);
  document.addEventListener('visibilitychange', onVisible);

  cleanup = () => {
    if (timer != null) {
      window.clearInterval(timer);
      timer = null;
    }
    window.removeEventListener('focus', onVisible);
    document.removeEventListener('visibilitychange', onVisible);
    document.title = originalTitle;
    if (link && originalFavicon != null) link.setAttribute('href', originalFavicon);
    cleanup = null;
  };
  return stopTabAttention;
}
