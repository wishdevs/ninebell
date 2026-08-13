import { NextResponse, type NextRequest } from 'next/server';

/**
 * 라우트 보호 프록시 (Next 16 `proxy` 컨벤션 — 구 middleware).
 *
 * `session` 쿠키(백엔드 발급 httpOnly JWT)가 없는 요청은 `/login`으로
 * 리다이렉트한다. `/login`과 정적 자원은 통과시킨다.
 *
 * (app)/(auth) 라우트 그룹은 URL에 드러나지 않으므로 경로 그룹이 아닌
 * 실제 경로(`/login` 등)로 공개 여부를 판단한다.
 */

// `/signup`은 세션 이전 단계(로그인 응답으로 받은 signupToken이 인증 수단)라 공개.
const PUBLIC_PATHS = ['/login', '/signup'];

// 매뉴얼 비인증 공개는 개발환경 전용(2026-08-13 사용자 지정) — 운영 공개 전 스크린샷
// 내부정보 정리 선행. NODE_ENV 는 빌드 시 인라인되므로 프로덕션 빌드에서는 이 분기가
// 제거되어 /manual 도 로그인 필수(현행 유지)다.
if (process.env.NODE_ENV !== 'production') {
  PUBLIC_PATHS.push('/manual');
}

export function proxy(req: NextRequest): NextResponse {
  const { pathname } = req.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  if (isPublic || req.cookies.has('session')) {
    return NextResponse.next();
  }

  const loginUrl = req.nextUrl.clone();
  loginUrl.pathname = '/login';
  return NextResponse.redirect(loginUrl);
}

export const config = {
  // _next 내부 자원과 흔한 정적 파일 확장자는 미들웨어에서 제외한다.
  matcher: [
    '/((?!_next|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|woff|woff2|ttf|otf|css|js|map)$).*)',
  ],
};
