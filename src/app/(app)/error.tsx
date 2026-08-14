'use client';

import Link from 'next/link';
import { RiErrorWarningLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';

/**
 * (app) 세그먼트 에러 바운더리 — 화면 렌더 예외가 전체 크래시 화면으로 번지는
 * 것을 막는다. 앱 셸 레이아웃과 로그인 세션은 그대로 유지되므로, 사용자에게
 * "세션은 살아 있고 재시도하면 된다"를 명확히 안내한다(라이브 실행 중 특히 중요).
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <EmptyState
        icon={<RiErrorWarningLine size={20} aria-hidden />}
        title="화면을 표시하는 중 문제가 발생했습니다"
        description={
          <>
            로그인 세션과 진행 중인 작업은 그대로 유지됩니다. 다시 시도해도 반복되면 홈으로 이동해
            주세요.
            {error.digest ? (
              <>
                {' '}
                <span className="font-mono text-[11px]">오류 코드: {error.digest}</span>
              </>
            ) : null}
          </>
        }
        action={
          <>
            <Button size="sm" onClick={reset}>
              다시 시도
            </Button>
            <Button size="sm" variant="secondary" asChild>
              <Link href="/">홈으로</Link>
            </Button>
          </>
        }
      />
    </div>
  );
}
