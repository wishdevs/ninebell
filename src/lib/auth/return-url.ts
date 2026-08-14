/**
 * 로그인 후 되돌아갈 경로(`?next=`) — 만들기·읽기의 단일 소스.
 *
 * 세션이 끊겨 401 이 나면 로그인으로 보내되, 보던 화면을 잃지 않도록 현재 경로를 실어 보낸다
 * (사용자 요청 2026-08-14). 로그인 성공 시 그 경로로 복귀한다.
 *
 * ⚠ **오픈 리다이렉트 차단**: next 는 외부에서 조작 가능한 값이다(주소창·피싱 링크). 같은 출처의
 *   절대경로만 허용하고, 그 밖(`https://evil.com`, `//evil.com`, `/\evil.com`)은 전부 버린다.
 */

const PARAM = 'next';

/** 로그인 이후 되돌아가면 안 되는 경로 — 인증 화면으로 되돌리면 순환한다. */
const DENY_PREFIXES = ['/login', '/signup'];

/**
 * next 로 쓸 수 있는 값인지 — **같은 출처의 절대경로**만 통과.
 * `//host`·`/\host` 는 브라우저가 프로토콜 상대 URL(외부)로 해석하므로 거른다.
 */
export function isSafeReturnPath(value: string | null | undefined): value is string {
  if (!value || !value.startsWith('/')) return false;
  if (value.startsWith('//') || value.startsWith('/\\')) return false;
  return !DENY_PREFIXES.some((p) => value === p || value.startsWith(`${p}/`) || value.startsWith(`${p}?`));
}

/** 현재 위치(경로+쿼리)를 next 값으로. 브라우저 밖(SSR)이면 null. */
export function currentReturnPath(): string | null {
  if (typeof window === 'undefined') return null;
  const path = window.location.pathname + window.location.search;
  return isSafeReturnPath(path) ? path : null;
}

/** `/login` 또는 `/login?next=…` — next 가 안전하지 않거나 없으면 파라미터를 붙이지 않는다. */
export function loginUrlWithReturn(next: string | null | undefined): string {
  return isSafeReturnPath(next) ? `/login?${PARAM}=${encodeURIComponent(next)}` : '/login';
}

/** 로그인 성공 후 이동할 경로 — 안전하면 next, 아니면 홈. */
export function resolveReturnPath(next: string | null | undefined): string {
  return isSafeReturnPath(next) ? next : '/';
}
