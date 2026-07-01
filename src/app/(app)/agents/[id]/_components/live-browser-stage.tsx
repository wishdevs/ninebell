'use client';

import { RiLockLine } from '@remixicon/react';
import { LiveScreen } from '@/components/live/LiveScreen';
import type { LiveRunStatus } from '@/lib/live/types';
import { cn } from '@/lib/utils';

interface LiveBrowserStageProps {
  targetUrl: string;
  status: LiveRunStatus;
  screenshot: string | null;
  connected: boolean;
}

const LIVE_STATUSES: ReadonlySet<LiveRunStatus> = new Set([
  'connecting',
  'running',
  'waiting_input',
]);

/**
 * 라이브 브라우저 스테이지 — 브라우저 크롬(URL·상태 배지) + 스크린캐스트(LiveScreen)만.
 *
 * 하단 두 바(입력 대기 캡션 바 · 단계 진행 바)는 제거했다: 단계 진행은 상단 라이브 스텝퍼로,
 * 대화 입력은 우측 개입 탭으로 옮겨 중복이었다. 브라우징 화면에 집중되게 한다.
 */
export function LiveBrowserStage({
  targetUrl,
  status,
  screenshot,
  connected,
}: LiveBrowserStageProps) {
  const live = LIVE_STATUSES.has(status);
  return (
    // 카드 폭 = min(셀폭, (셀높이 − 크롬)×16/9). 하단 바 제거로 비-화면 높이가 크롬(≈48px)만 남는다.
    <div className="[container-type:size] flex min-h-0 items-start justify-center lg:h-full">
      <section className="border-border bg-surface flex min-h-0 w-full max-w-full flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)] lg:w-[min(100cqw,calc((100cqh-48px)*16/9))]">
        {/* 브라우저 크롬 */}
        <div className="border-border bg-surface-raised flex items-center gap-3 border-b px-3 py-2.5">
          <div className="flex shrink-0 items-center gap-1.5" aria-hidden>
            <span className="bg-danger/70 size-2.5 rounded-full" />
            <span className="bg-warning/70 size-2.5 rounded-full" />
            <span className="bg-success/70 size-2.5 rounded-full" />
          </div>
          <div className="border-border bg-surface text-foreground-secondary flex min-w-0 flex-1 items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1 text-[11px]">
            <RiLockLine size={11} aria-hidden className="text-foreground-tertiary shrink-0" />
            <span className="truncate font-mono">{targetUrl}</span>
          </div>
          <StatusBadge status={status} connected={connected} />
        </div>

        {/* 스크린캐스트 — 카드 폭이 곧 16:9 폭이므로 화면은 풀폭 + 16:9. */}
        <div className="bg-muted/30 relative aspect-[16/9] w-full">
          <LiveScreen src={screenshot} live={live} />
        </div>
      </section>
    </div>
  );
}

function StatusBadge({ status, connected }: { status: LiveRunStatus; connected: boolean }) {
  if (status === 'idle') {
    return (
      <Badge className="border-border bg-muted text-muted-foreground">
        <span className="bg-muted-foreground size-1.5 rounded-full" aria-hidden />
        대기
      </Badge>
    );
  }
  if (status === 'succeeded') {
    return (
      <Badge className="border-success/30 bg-success/10 text-success">
        <span className="bg-success size-1.5 rounded-full" aria-hidden />
        완료
      </Badge>
    );
  }
  if (status === 'failed') {
    return (
      <Badge className="border-danger/30 bg-danger/10 text-danger">
        <span className="bg-danger size-1.5 rounded-full" aria-hidden />
        실패
      </Badge>
    );
  }
  if (!connected && (status === 'running' || status === 'waiting_input')) {
    return (
      <Badge className="border-warning/30 bg-warning/10 text-warning">
        <span className="bg-warning size-1.5 animate-pulse rounded-full" aria-hidden />
        재연결 중
      </Badge>
    );
  }
  return (
    <Badge className="border-danger/30 bg-danger/10 text-danger">
      <span className="bg-danger size-1.5 animate-pulse rounded-full" aria-hidden />
      LIVE
    </Badge>
  );
}

function Badge({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider',
        className,
      )}
    >
      {children}
    </span>
  );
}
