/**
 * 백엔드(FastAPI) 호출용 경량 fetch 래퍼.
 *
 * 세션은 백엔드가 발급한 httpOnly 쿠키 `session`으로 유지되므로 모든 요청에
 * `credentials: 'include'`를 붙인다(브라우저가 쿠키를 자동 첨부/수신).
 * 베이스 URL은 `NEXT_PUBLIC_API_BASE`(기본 http://localhost:8010 — 로컬 백엔드 포트).
 *
 * 토큰을 코드에서 직접 다루지 않는다 — 쿠키는 브라우저가 관리한다.
 */

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
    throw new ApiError(response.status, parseErrorDetail(parsed));
  }

  return parsed as T;
}

export const api = {
  get: <T>(path: string): Promise<T> => request<T>('GET', path),
  post: <T>(path: string, body?: Json): Promise<T> => request<T>('POST', path, body),
  patch: <T>(path: string, body?: Json): Promise<T> => request<T>('PATCH', path, body),
  delete: <T>(path: string): Promise<T> => request<T>('DELETE', path),
};

/** `GET /auth/me` — 현재 사용자 + 평탄화된 권한. 미인증 시 ApiError(401). */
export function getMe(): Promise<CurrentUser> {
  return api.get<CurrentUser>('/auth/me');
}

export interface UpdateMeInput {
  displayName: string;
  department: string | null;
  email: string | null;
}

/** `PATCH /auth/me` — 본인 프로필(이름/부서/이메일) 수정. 로그인 식별자·롤은 불변. */
export function updateMe(input: UpdateMeInput): Promise<CurrentUser> {
  return api.patch<CurrentUser>('/auth/me', { ...input });
}
