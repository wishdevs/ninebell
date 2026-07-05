'use client';

import { RiLockLine, RiPlayCircleLine, RiPlayLine, RiRestartLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { LiveScreen } from '@/components/live/LiveScreen';
import type { LiveRunStatus } from '@/lib/live/types';
import { cn } from '@/lib/utils';

interface LiveBrowserStageProps {
  targetUrl: string;
  status: LiveRunStatus;
  screenshot: string | null;
  connected: boolean;
  /** 실행 워크플로우가 매핑돼 있는지 — false 면 스테이지 CTA 를 비활성화한다. */
  canRun?: boolean;
  /** 스테이지 중앙 CTA(실행/다시 실행) 클릭 — 상단 실행 컨트롤과 동일 동작. */
  onStart?: () => void;
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
  canRun = false,
  onStart,
}: LiveBrowserStageProps) {
  const live = LIVE_STATUSES.has(status);
  return (
    // 카드 폭 = min(셀폭, (셀높이 − 크롬)×16/9). 하단 바 제거로 비-화면 높이가 크롬(≈48px)만 남는다.
    <div className="[container-type:size] flex min-h-0 items-start justify-center lg:h-full">
      <section className="border-border bg-surface flex min-h-0 w-full max-w-full flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)] lg:w-[min(100cqw,calc((100cqh-48px)*16/10))]">
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
        {/* 스크린캐스트 종횡비(≈16:10, CDP 1280×800)에 맞춘 컨테이너 — LiveScreen 은 object-contain
            이라 잘림 없이 전체 프레임을 보여준다(종횡비를 맞춰 레터박스도 최소화). */}
        <div className="bg-muted/30 relative aspect-[16/10] w-full">
          <LiveScreen src={screenshot} live={live} />
          {/* 실행 CTA — 우상단 버튼이 안 보인다는 피드백에 따라, 세션이 없거나(idle)
              종료됐을 때 화면 중앙에 대형 실행 진입점을 겹쳐 보여준다(실행 중엔 숨김). */}
          {onStart && !live ? (
            <StageRunCta status={status} canRun={canRun} onStart={onStart} />
          ) : null}
        </div>
      </section>
    </div>
  );
}

/**
 * 스테이지 중앙 실행 CTA — idle 은 시작, succeeded/failed 는 재실행.
 * 종료 상태에서는 마지막 스크린샷 위에 살짝 어둡게 얹어 결과 화면 맥락을 유지한다.
 */
function StageRunCta({
  status,
  canRun,
  onStart,
}: {
  status: LiveRunStatus;
  canRun: boolean;
  onStart: () => void;
}) {
  const terminal = status === 'succeeded' || status === 'failed';
  const title =
    status === 'succeeded' ? '실행 완료' : status === 'failed' ? '실행 실패' : '에이전트 실행';
  const description = terminal
    ? '같은 워크플로우를 새 세션으로 다시 실행할 수 있습니다.'
    : '라이브 브라우저 세션을 시작해 워크플로우를 단계별로 실행합니다.';
  return (
    <div
      className={cn(
        'absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 px-6 text-center',
        // idle 은 불투명 배경 — 밑의 LiveScreen 플레이스홀더('라이브 화면 없음')와 글자 겹침 방지.
        // 종료 상태는 마지막 스크린샷 맥락을 살려 dim+blur 로만 얹는다.
        terminal ? 'bg-background/60 backdrop-blur-[2px]' : 'bg-surface',
      )}
    >
      <RiPlayCircleLine
        size={44}
        aria-hidden
        className={cn(
          status === 'failed'
            ? 'text-danger'
            : status === 'succeeded'
              ? 'text-success'
              : 'text-accent',
        )}
      />
      <div className="flex flex-col gap-1">
        <p className="text-foreground text-[length:var(--text-heading-sm)] font-semibold">
          {title}
        </p>
        <p className="text-muted-foreground max-w-[36ch] text-[length:var(--text-body-sm)] leading-relaxed">
          {description}
        </p>
      </div>
      <Button
        size="lg"
        onClick={onStart}
        disabled={!canRun}
        title={canRun ? undefined : '실행 가능한 워크플로우가 연결되지 않은 에이전트입니다.'}
        className="mt-1 min-w-40"
      >
        {terminal ? (
          <>
            <RiRestartLine size={16} aria-hidden />
            다시 실행
          </>
        ) : (
          <>
            <RiPlayLine size={16} aria-hidden />
            실행
          </>
        )}
      </Button>
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
