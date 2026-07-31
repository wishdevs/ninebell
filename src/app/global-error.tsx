'use client';

import './globals.css';

/**
 * 최상위(루트 레이아웃 포함) 에러 바운더리 — 루트 레이아웃 자체가 무너졌을 때의
 * 최후 방어선이라 `<html>`/`<body>`를 직접 렌더해야 한다. 폰트 로더(레이아웃)가
 * 대체되므로 시스템 폰트 폴백으로 표시된다. 토큰(globals.css)은 그대로 사용해
 * 라이트/다크 모두 앱과 같은 표면 언어를 유지한다.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="ko">
      <body className="bg-background text-foreground min-h-dvh antialiased">
        <div className="flex min-h-dvh items-center justify-center p-6">
          <div className="border-border bg-surface flex w-full max-w-md flex-col items-center gap-3 rounded-[var(--radius-lg)] border border-dashed p-10 text-center shadow-[var(--shadow-card)]">
            <span
              aria-hidden
              className="bg-danger/10 text-danger flex h-10 w-10 items-center justify-center rounded-full text-lg font-semibold"
            >
              !
            </span>
            <p className="text-foreground text-sm font-medium">
              앱을 표시하는 중 문제가 발생했습니다
            </p>
            <p className="text-muted-foreground max-w-prose text-xs leading-relaxed">
              일시적인 오류일 수 있습니다. 다시 시도해도 반복되면 페이지를 새로 고침해 주세요.
              {error.digest ? (
                <>
                  {' '}
                  <span className="font-mono text-[11px]">오류 코드: {error.digest}</span>
                </>
              ) : null}
            </p>
            <button
              type="button"
              onClick={reset}
              className="bg-accent text-accent-foreground hover:bg-accent/90 mt-2 inline-flex h-8 items-center justify-center rounded-sm px-3 text-xs font-medium shadow-sm transition-all"
            >
              다시 시도
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
