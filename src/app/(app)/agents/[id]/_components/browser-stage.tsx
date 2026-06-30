import { RiLockLine, RiTvLine } from '@remixicon/react';
import type { Agent } from '@/lib/data/agents';
import { cn } from '@/lib/utils';

const LIVE_STATUSES: ReadonlySet<Agent['status']> = new Set(['running', 'waiting_input']);

/**
 * 라이브 브라우저 영역. 실제 브라우저는 아직 연결하지 않고 "비율만 잡아"
 * 더존 옴니솔 화면이 들어올 자리를 잡는다(16:10). 상단 크롬 + 하단 단계
 * 진행 바로 구동 맥락을 보여준다.
 */
export function BrowserStage({ agent }: { agent: Agent }) {
  const isLive = LIVE_STATUSES.has(agent.status);
  const steps = agent.steps;
  const activeIndex = steps.findIndex((s) => s.status === 'active');
  const doneCount = steps.filter((s) => s.status === 'done').length;
  const currentIndex = activeIndex >= 0 ? activeIndex : Math.min(doneCount, steps.length - 1);
  const currentStep = steps[currentIndex];

  return (
    // 셀을 컨테이너로 삼아, 카드(크롬+화면+푸터) 폭을 16:9 화면 폭에 맞춰 잡고
    // 셀 안에서 가운데 정렬한다. 카드 폭 = min(셀폭, (셀높이 − 크롬·푸터)×16/9).
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
            <span className="truncate font-mono">{agent.targetUrl}</span>
          </div>
          {isLive ? (
            <span className="border-danger/30 bg-danger/10 text-danger inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider">
              <span className="bg-danger size-1.5 animate-pulse rounded-full" aria-hidden />
              LIVE
            </span>
          ) : null}
        </div>

        {/* 라이브 화면 영역 — 카드 폭이 곧 16:9 폭이므로 화면은 풀폭 + 16:9. */}
        <div className="bg-muted/30 relative aspect-[16/9] w-full">
          <div className="border-border-strong/60 absolute inset-3 flex flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed text-center">
            <RiTvLine size={26} aria-hidden className="text-foreground-tertiary" />
            <p className="text-foreground-secondary text-[length:var(--text-body-sm)] font-medium">
              라이브 화면 영역
            </p>
            <p className="text-foreground-tertiary max-w-xs text-[11px] leading-relaxed">
              에이전트가 더존 옴니솔 화면을 조작하는 과정이 이 영역에 실시간으로 표시됩니다.
            </p>
          </div>
          {/* 현재 동작 캡션 */}
          <div className="bg-surface/85 border-border absolute inset-x-3 bottom-3 flex items-center gap-2 rounded-[var(--radius-sm)] border px-3 py-2 backdrop-blur-sm">
            <span
              aria-hidden
              className={cn(
                'size-1.5 shrink-0 rounded-full',
                isLive ? 'bg-accent animate-pulse' : 'bg-muted-foreground',
              )}
            />
            <span className="text-foreground-secondary truncate text-[11px]">
              {agent.currentAction}
            </span>
          </div>
        </div>

        {/* 단계 진행 바 */}
        <div className="border-border flex flex-col gap-1.5 border-t px-4 py-3">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-foreground-tertiary">
              단계{' '}
              <span className="text-foreground-secondary font-semibold tabular-nums">
                {currentIndex + 1}/{steps.length}
              </span>
              {currentStep ? (
                <span className="text-foreground-secondary"> · {currentStep.label}</span>
              ) : null}
            </span>
            <span className="text-foreground-secondary font-semibold tabular-nums">
              {agent.progress}%
            </span>
          </div>
          <div className="bg-muted h-1.5 overflow-hidden rounded-full">
            <div
              className={cn(
                'h-full rounded-full transition-[width] duration-500',
                agent.status === 'waiting_input'
                  ? 'bg-warning'
                  : agent.status === 'failed'
                    ? 'bg-danger'
                    : 'bg-accent',
              )}
              style={{ width: `${agent.progress}%` }}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
