import { cookies } from 'next/headers';
import Image from 'next/image';
import Link from 'next/link';
import AppLayout from '@/app/(app)/layout';
import { Button } from '@/components/ui/button';
import { DebugModeProvider } from '@/lib/debug-mode';

/**
 * /manual 전용 레이아웃 — (app) 라우트 그룹 밖에서 인증 여부에 따라 크롬을 나눈다.
 *
 * · `session` 쿠키 있음(로그인) → (app) 레이아웃을 그대로 재사용해 기존과 동일한
 *   앱 셸(UserProvider→DebugModeProvider→DashboardShell)로 감싼다 — 로그인 사용자의
 *   매뉴얼 UX 는 종전과 픽셀 단위 동일.
 * · 쿠키 없음(비로그인) → 가벼운 공개 크롬(로고 + 로그인 CTA). 프록시(proxy.ts)가
 *   개발환경에서만 /manual 을 비인증 통과시키므로, 운영에서는 이 분기에 도달하지 않는다.
 *
 * ⚠ 쿠키 존재 ≠ 유효 세션 — 만료/무효 쿠키면 (app) 분기로 들어가지만, UserProvider 의
 *   `GET /auth/me` 401 → `/login` 리다이렉트(기존 경로)가 그대로 처리한다.
 */
export default async function ManualLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();

  if (cookieStore.has('session')) {
    return <AppLayout>{children}</AppLayout>;
  }

  return (
    // DebugModeProvider — useDebugMode 는 localStorage 전용이라 비로그인에서도 동작한다
    // (디버그 전용 문서 필터가 로그인/비로그인 같은 규칙으로 걸리게 유지).
    <DebugModeProvider>
      <div className="bg-background flex min-h-dvh flex-col">
        <header className="border-border-subtle bg-surface flex items-center justify-between border-b px-6 py-4 sm:px-10">
          <Link href="/manual" className="flex items-center">
            {/* 나인벨 이미지 로고 — (auth) 레이아웃과 동일 규격(h-5). */}
            <Image
              src="/ninebell-logo.png"
              alt="NINEBELL"
              width={2303}
              height={350}
              priority
              className="h-5 w-auto"
            />
          </Link>
          <Button asChild variant="secondary" size="sm">
            <Link href="/login">로그인</Link>
          </Button>
        </header>

        <main className="mx-auto w-full max-w-[var(--content-max)] flex-1 px-6 py-8 sm:px-10">
          {children}
        </main>

        <footer className="text-foreground-tertiary px-6 pb-6 text-[length:var(--text-caption)] sm:px-10">
          © 2026 나인벨
        </footer>
      </div>
    </DebugModeProvider>
  );
}
