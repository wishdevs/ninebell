import Image from 'next/image';
import Link from 'next/link';

/**
 * 인증 화면 레이아웃 — 좌측 폼 패널 + 우측 히어로 이미지(데스크톱).
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-background relative z-0 grid min-h-dvh grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <section className="bg-background relative flex flex-col">
        <header className="flex items-center px-6 py-6 sm:px-10 lg:px-12 lg:py-8">
          <Link href="/login" className="flex items-center">
            {/* 나인벨 이미지 로고 — 미니멀 사이즈(h-5). */}
            <Image
              src="/ninebell-logo.png"
              alt="NINEBELL"
              width={2303}
              height={350}
              priority
              className="h-5 w-auto"
            />
          </Link>
        </header>

        <div className="flex flex-1 items-center justify-center px-6 pb-12 sm:px-10 lg:px-12">
          <div className="w-full max-w-md">{children}</div>
        </div>

        <footer className="text-foreground-tertiary px-6 pb-6 text-[length:var(--text-caption)] sm:px-10 lg:px-12 lg:pb-8">
          © 2026 나인벨
        </footer>
      </section>

      <aside className="border-border-subtle relative hidden overflow-hidden border-l lg:block">
        <HeroPanel />
      </aside>
    </div>
  );
}

function HeroPanel() {
  return (
    <div className="bg-surface-raised relative h-full w-full overflow-hidden">
      {/* 세로로 긴 크리스탈 타워 아트워크 — 풀하이트 컬럼을 object-cover로 채운다(NINEBELL 블루 톤). */}
      <Image
        src="/login-hero.webp"
        alt=""
        fill
        priority
        sizes="(min-width: 1024px) 55vw, 0px"
        className="object-cover"
      />
      {/* 은은한 오로라 드리프트 — 정적 아트워크 위에 미세한 생동감을 더하는 앰비언스(reduced-motion 시 자동 정지). */}
      <div aria-hidden className="animate-aurora-a" />
      <div aria-hidden className="animate-aurora-b" />
      {/* 좌측 경계 seam 을 아주 옅게 블렌딩(브랜드 톤 유지, 과하지 않게). */}
      <div
        aria-hidden
        className="to-background/15 absolute inset-0 bg-gradient-to-l from-transparent"
      />
    </div>
  );
}
