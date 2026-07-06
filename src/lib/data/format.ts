/**
 * 표시용 포매터 모음 — 더미데이터를 한국어 UI에 맞게 렌더링한다.
 * 백엔드가 없으므로 모든 값은 클라이언트에서 계산된다.
 */

const NUMBER_FMT = new Intl.NumberFormat('ko-KR');

/**
 * 고정 기준 시각. 모든 더미 타임스탬프와 상대시간 계산의 기준점이다.
 *
 * 실제 `Date.now()`를 기준으로 삼으면 서버 렌더와 클라이언트 하이드레이션
 * 사이의 수 초 차이로 "12분 전" → "13분 전"처럼 분 경계가 어긋나 하이드레이션
 * 불일치가 발생한다. 기본형은 실시간 정확도가 필요 없으므로 고정 앵커로
 * 완전 결정적으로 렌더한다.
 */
export const NOW_ANCHOR = new Date('2026-06-30T14:00:00+09:00');

/** 정수 천단위 콤마. */
export function formatInteger(n: number): string {
  return NUMBER_FMT.format(Math.round(n));
}

/** 0..1 비율(또는 퍼센트 값)을 "62.1%" 형태로. */
export function formatPercent(value: number, fractionDigits = 1): string {
  if (!Number.isFinite(value)) return '—';
  return `${value.toFixed(fractionDigits)}%`;
}

/** 초 단위 시간을 "M분 SS초"로. */
export function formatSeconds(total: number): string {
  if (!Number.isFinite(total) || total < 0) return '0초';
  const whole = Math.round(total);
  const m = Math.floor(whole / 60);
  const s = whole % 60;
  if (m === 0) return `${s}초`;
  return `${m}분 ${s.toString().padStart(2, '0')}초`;
}

/**
 * 예상 소요(밀리초)를 근사 표기로 — 숫자는 항상 근사(~) + 10초 단위 반올림(승인 시안).
 * <60초 → "~40초", ≥60초 → "~1분 30초"(초가 0이면 "~2분"). 최소 "~10초"
 * ("~0초"는 무의미하므로 바닥을 둔다).
 */
export function formatEta(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '~10초';
  const sec = Math.max(Math.round(ms / 10_000) * 10, 10);
  if (sec < 60) return `~${sec}초`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s === 0 ? `~${m}분` : `~${m}분 ${s}초`;
}

/* ── 시간 표기 규칙 (비주얼 토론 합의) ────────────────────────────────────
 * 1. 목록·로그·피드: 상대시간("N분 전")을 본문으로, 절대시각은 `title` 툴팁으로.
 *    → formatRelativeWithTitle() 사용: <time title={title}>{relative}</time>
 * 2. 상세 화면·감사 기록: 절대시각("2026. 6. 29. 16:24")을 본문으로.
 *    → formatDateTime() 사용.
 * 같은 화면 안에서 상대/절대를 섞지 않는다 — 목록은 상대, 상세는 절대로 통일. */

/**
 * ISO 타임스탬프를 한국어 상대시간으로. 분/시간/일 단위로 거칠게 — 초 단위
 * 갱신은 하이드레이션 불일치를 유발하므로 피한다.
 */
export function formatRelativeKorean(iso: string, now: Date = NOW_ANCHOR): string {
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return '';
  const diffMs = now.getTime() - target;
  if (diffMs < 0) return '방금 전';
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return '방금 전';
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}일 전`;
  const weeks = Math.floor(days / 7);
  return `${weeks}주 전`;
}

/** "2026. 6. 30." 형태의 짧은 날짜. */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium' }).format(d);
}

/**
 * "2026. 6. 29. 16:24" 형태의 날짜+시간. timeZone을 Asia/Seoul로 고정해
 * 서버/클라이언트가 동일 문자열을 렌더한다(하이드레이션 안전).
 */
const DATETIME_FMT = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return DATETIME_FMT.format(d);
}

/**
 * 목록/로그용 페어 — 본문은 상대시간, `title`엔 절대시각(위 표기 규칙 1번).
 * 사용 예: `<time title={title}>{relative}</time>`
 */
export function formatRelativeWithTitle(
  iso: string,
  now: Date = NOW_ANCHOR,
): { relative: string; title: string } {
  return { relative: formatRelativeKorean(iso, now), title: formatDateTime(iso) };
}

interface Offset {
  minutes?: number;
  hours?: number;
  days?: number;
}

/**
 * 지금으로부터 `offset` 만큼 과거의 ISO 타임스탬프. 픽스처가 렌더 시점과
 * 무관하게 그럴듯한 상대시간("2시간 전")을 갖도록 한다.
 */
export function relativeFromNow(offset: Offset): string {
  const ms =
    (offset.minutes ?? 0) * 60_000 +
    (offset.hours ?? 0) * 3_600_000 +
    (offset.days ?? 0) * 86_400_000;
  return new Date(NOW_ANCHOR.getTime() - ms).toISOString();
}
