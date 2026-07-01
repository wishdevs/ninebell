'use client';

import { RiLockLine } from '@remixicon/react';
import { LiveScreen } from '@/components/live/LiveScreen';
import type { LiveRunStatus, LiveStepState } from '@/lib/live/types';
import { cn } from '@/lib/utils';

interface LiveBrowserStageProps {
  targetUrl: string;
  status: LiveRunStatus;
  steps: readonly LiveStepState[];
  screenshot: string | null;
  connected: boolean;
  /** 현재 동작 캡션(없으면 단계에서 파생). */
  caption?: string;
}

const LIVE_STATUSES: ReadonlySet<LiveRunStatus> = new Set([
  'connecting',
  'running',
  'waiting_input',
]);

/**
 * 라이브 브라우저 스테이지 — 정적 BrowserStage 의 라이브판.
 * 크롬 + 스크린캐스트(LiveScreen) + 라이브 단계 진행 바로 구성한다. 실제 스크린캐스트
 * dataURL 을 LiveScreen 이 렌더하고(메모), 나머지(단계/캡션)는 라이브 상태에서 파생한다.
 */
export function LiveBrowserStage({
  targetUrl,
  status,
  steps,
  screenshot,
  connected,
  caption,
}: LiveBrowserStageProps) {
  const live = LIVE_STATUSES.has(status);
  const total = steps.length;
  const doneCount = steps.filter((s) => s.status === 'done').length;
  const activeIndex = steps.findIndex((s) => s.status === 'running');
  const currentIndex = activeIndex >= 0 ? activeIndex : Math.max(0, doneCount - 1);
  const currentStep = steps[currentIndex];
  const progress = total === 0 ? 0 : Math.round((doneCount / total) * 100);
  const captionText = caption ?? deriveCaption(status, currentStep?.step);

  return (
    <div className="[container-type:size] flex min-h-0 items-start justify-center lg:h-full">
      <section className="border-border bg-surface flex min-h-0 w-full max-w-full flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)] lg:w-[min(100cqw,calc((100cqh-104px)*16/9))]">
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

        {/* 스크린캐스트 영역 — 카드 폭이 곧 16:9 폭이므로 화면은 풀폭 + 16:9. */}
        <div className="bg-muted/30 relative aspect-[16/9] w-full">
          <LiveScreen src={screenshot} live={live} />
          <div className="bg-surface/85 border-border absolute inset-x-3 bottom-3 flex items-center gap-2 rounded-[var(--radius-sm)] border px-3 py-2 backdrop-blur-sm">
            <span
              aria-hidden
              className={cn(
                'size-1.5 shrink-0 rounded-full',
                live ? 'bg-accent animate-pulse' : 'bg-muted-foreground',
              )}
            />
            <span className="text-foreground-secondary truncate text-[11px]">{captionText}</span>
          </div>
        </div>

        {/* 라이브 단계 진행 바 */}
        <div className="border-border flex flex-col gap-1.5 border-t px-4 py-3">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-foreground-tertiary">
              단계{' '}
              <span className="text-foreground-secondary font-semibold tabular-nums">
                {total === 0 ? 0 : currentIndex + 1}/{total}
              </span>
              {currentStep ? (
                <span className="text-foreground-secondary"> · {currentStep.step}</span>
              ) : null}
            </span>
            <span className="text-foreground-secondary font-semibold tabular-nums">
              {progress}%
            </span>
          </div>
          <div className="bg-muted h-1.5 overflow-hidden rounded-full">
            <div
              className={cn(
                'h-full rounded-full transition-[width] duration-500',
                status === 'waiting_input'
                  ? 'bg-warning'
                  : status === 'failed'
                    ? 'bg-danger'
                    : status === 'succeeded'
                      ? 'bg-success'
                      : 'bg-accent',
              )}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      </section>
    </div>
  );
}

function deriveCaption(status: LiveRunStatus, step?: string): string {
  switch (status) {
    case 'connecting':
      return '라이브 세션에 연결하는 중…';
    case 'waiting_input':
      return '사용자 입력을 기다리는 중 — 오른쪽에서 응답하세요';
    case 'succeeded':
      return '실행이 완료되었습니다.';
    case 'failed':
      return '실행이 중단되었습니다.';
    case 'running':
      return step ? `${step} 단계를 수행하는 중…` : '에이전트가 화면을 조작하는 중…';
    default:
      return '대기 중';
  }
}

function StatusBadge({ status, connected }: { status: LiveRunStatus; connected: boolean }) {
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
