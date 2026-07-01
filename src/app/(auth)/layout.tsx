import Link from 'next/link';

/**
 * 인증 화면 레이아웃 — 좌측 폼 패널 + 우측 오로라 히어로(데스크톱).
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-background relative z-0 grid min-h-dvh grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <section className="bg-background relative flex flex-col">
        <header className="flex items-center px-6 py-6 sm:px-10 lg:px-12 lg:py-8">
          <Link href="/login" className="flex items-center gap-3">
            <span className="font-display text-base font-semibold tracking-tight">NINEBELL</span>
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
      <div
        aria-hidden
        className="animate-aurora-a absolute -inset-[20%] opacity-40 blur-3xl will-change-transform dark:opacity-30"
        style={{
          background: 'radial-gradient(closest-side, oklch(0.7 0.18 258 / 0.55), transparent 70%)',
        }}
      />
      <div
        aria-hidden
        className="animate-aurora-b absolute -inset-[20%] opacity-30 blur-3xl will-change-transform dark:opacity-25"
        style={{
          background: 'radial-gradient(closest-side, oklch(0.74 0.14 200 / 0.45), transparent 70%)',
        }}
      />
    </div>
  );
}
