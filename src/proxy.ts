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
