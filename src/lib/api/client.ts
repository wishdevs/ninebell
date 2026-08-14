/**
 * 백엔드(FastAPI) 호출용 경량 fetch 래퍼.
 *
 * 세션은 백엔드가 발급한 httpOnly 쿠키 `session`으로 유지되므로 모든 요청에
 * `credentials: 'include'`를 붙인다(브라우저가 쿠키를 자동 첨부/수신).
 * 베이스 URL은 `NEXT_PUBLIC_API_BASE`(기본 http://localhost:8010 — 로컬 백엔드 포트).
 *
 * 토큰을 코드에서 직접 다루지 않는다 — 쿠키는 브라우저가 관리한다.
 */

import { currentReturnPath, loginUrlWithReturn } from '@/lib/auth/return-url';
import type { CurrentUser } from '@/lib/auth/types';

/**
 * 백엔드 베이스 URL(단일 소스). REST/SSE 클라이언트가 모두 이 상수를 import 한다
 * (이전엔 3개 파일에 중복 정의·기본값 8000 오폴백이었다).
 */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8010';

type Json = Record<string, unknown> | unknown[] | string | number | boolean | null;

/** 백엔드 에러를 status와 함께 전달한다. UI는 status로 401(미인증) 등을 분기. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * 임의 예외를 ApiError 로 정규화한다. fetch 자체 실패(네트워크/CORS)는 status=0.
 * (이전엔 use-api-resource·logs·audit 3곳에 동일 복제돼 있었다.)
 */
export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(0, err instanceof Error ? err.message : '네트워크 오류');
}

/**
 * 사용자 표시용 에러 메시지 매핑(권한/네트워크 공통 처리). ApiError 가 아니면 fallback.
 * (이전엔 members·organizations·account 3곳에 복제돼 있었다.)
 */
export function errorMessage(err: unknown, fallback = '요청을 처리하지 못했습니다.'): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return '이 작업을 수행할 권한이 없습니다.';
    if (err.status === 0) return '서버에 연결할 수 없습니다.';
    return err.message;
  }
  return fallback;
}

/**
 * FastAPI는 `detail`을 문자열(HTTPException) 또는
 * `{type, loc, msg, ...}` 배열(pydantic 422)로 반환한다.
 * 배열을 그대로 문자열화하면 "[object Object]"가 되므로 첫 msg를 추출한다.
 */
function parseErrorDetail(parsed: unknown): string {
  if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
    const detail = (parsed as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (Array.isArray(detail)) {
      const first = detail[0];
      if (first && typeof first === 'object' && 'msg' in first) {
        const msg = (first as { msg: unknown }).msg;
        if (typeof msg === 'string') {
          return msg;
        }
      }
    }
  }
  return 'Request failed';
}

async function parseBody(response: Response): Promise<unknown> {
  // 204/빈 본문(예: logout, delete)은 json 파싱이 실패하므로 안전하게 null 처리.
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/**
 * 401 을 '세션 만료'로 보지 **않는** 경로 — 인증 자체를 시도하는 엔드포인트.
 *
 * ⚠ `/auth/login` 은 **비밀번호가 틀려도 401** 을 준다(backend auth.py). 여기서 걸러내지
 *   않으면 오타 한 번에 화면이 로그인으로 튕겨 오류 메시지가 사라진다.
 * ⚠ `/auth/me` 는 최초 진입 인증 판정이라 호출부(user-provider)가 직접 처리한다 —
 *   중앙에서 리다이렉트하면 '로딩 중 화면'이 그려지기도 전에 이동해 깜빡인다.
 */
const NO_SESSION_REDIRECT = new Set(['/auth/login', '/auth/logout', '/auth/me']);

/** 동시 다발 401(한 화면이 API 여러 개를 병렬 호출)에 리다이렉트가 겹치지 않게 하는 1회 래치. */
let sessionExpiredHandled = false;

/**
 * 세션 만료(401) 공통 처리 — 로그인 화면으로 보내되 **보던 경로를 next 로 실어** 복귀시킨다
 * (사용자 요청 2026-08-14: 종전엔 메뉴만 이동하고 '안 된다'는 메시지만 떴다).
 *
 * router 가 아니라 `location.replace` 를 쓰는 이유: 여기는 컴포넌트 밖(모듈)이라 라우터를 쓸 수
 * 없고, 죽은 세션의 클라이언트 상태(캐시된 사용자·목록)를 통째로 버리는 편이 안전하다.
 * replace 라 뒤로가기로 만료된 화면에 되돌아가지 않는다.
 */
function handleSessionExpired(path: string): void {
  if (typeof window === 'undefined') return; // SSR/빌드 시 no-op.
  if (NO_SESSION_REDIRECT.has(path)) return;
  if (sessionExpiredHandled) return;
  if (window.location.pathname.startsWith('/login')) return; // 이미 로그인 화면.
  sessionExpiredHandled = true;
  window.location.replace(loginUrlWithReturn(currentReturnPath()));
}

async function request<T>(method: string, path: string, body?: Json): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: 'include',
    headers: body !== undefined ? { 'content-type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: 'no-store',
  });

  const parsed = await parseBody(response);

  if (!response.ok) {
    if (response.status === 401) handleSessionExpired(path);
    throw new ApiError(response.status, parseErrorDetail(parsed));
  }

  return parsed as T;
}

export const api = {
  get: <T>(path: string): Promise<T> => request<T>('GET', path),
  post: <T>(path: string, body?: Json): Promise<T> => request<T>('POST', path, body),
  put: <T>(path: string, body?: Json): Promise<T> => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: Json): Promise<T> => request<T>('PATCH', path, body),
  delete: <T>(path: string): Promise<T> => request<T>('DELETE', path),
};

/** `GET /auth/me` — 현재 사용자 + 평탄화된 권한. 미인증 시 ApiError(401). */
export function getMe(): Promise<CurrentUser> {
  return api.get<CurrentUser>('/auth/me');
}

export interface UpdateMeInput {
  email: string | null;
}

/** `PATCH /auth/me` — 본인 이메일 수정. 이름/부서(ERP 동기화값)·로그인 식별자·롤은 불변. */
export function updateMe(input: UpdateMeInput): Promise<CurrentUser> {
  return api.patch<CurrentUser>('/auth/me', { ...input });
}
