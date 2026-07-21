'use client';

import {
  RiExternalLinkLine,
  RiLockLine,
  RiPlayCircleLine,
  RiPlayLine,
  RiRestartLine,
  RiSparkling2Fill,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { LiveScreen } from '@/components/live/LiveScreen';
import { RunStatusBadge, type RunBadgeStatus } from '@/components/ui/run-status-badge';
import { formatEta } from '@/lib/data/format';
import type { LiveRunStatus, LiveWindow } from '@/lib/live/types';
import { cn } from '@/lib/utils';

/**
 * 실행 전 소요 예고 — 이력 기반 expectedMs 합(agent-detail-client 가 계산해 내려준다).
 * null 이면(이력 없는 스텝 존재) 예고를 숨기고 기존 문구만 보여준다.
 */
export interface StageEtaHint {
  /** 전 자동 스텝 expectedMs 합(ms). */
  totalMs: number;
  /** 첫 개입(intervention) 스텝 앞까지의 자동 스텝 합(ms). 개입 없는 에이전트면 null. */
  toFirstInterventionMs: number | null;
}

interface LiveBrowserStageProps {
  targetUrl: string;
  status: LiveRunStatus;
  /** 창별 최신 스크린캐스트 dataURL. child 가 있으면 부모/자식 탭 토글을 노출한다. */
  screenshots: { parent: string | null; child: string | null };
  /** 라이브 뷰에 현재 표시할 창 — 자식 창(팝업)이 열리면 자동 활성화된다. */
  activeWindow: LiveWindow;
  /** 부모창/자식창 탭 클릭 — 활성 창 수동 전환. */
  onSelectWindow?: (window: LiveWindow) => void;
  connected: boolean;
  /** 실행 워크플로우가 매핑돼 있는지 — false 면 스테이지 CTA 를 비활성화한다. */
  canRun?: boolean;
  /** 스테이지 중앙 CTA(실행/다시 실행) 클릭 — 상단 실행 컨트롤과 동일 동작. */
  onStart?: () => void;
  /** 실행 전 CTA 아래 소요 예고("약 2분 소요 · 첫 입력 요청까지 ~30초"). null=미표시. */
  etaHint?: StageEtaHint | null;
  /** AI 추천 계산 구간이면 그 단계 라벨 — 화면 위에 'AI가 계산하는 중…' 오버레이. null=미표시. */
  aiWorking?: string | null;
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
  screenshots,
  activeWindow,
  onSelectWindow,
  connected,
  canRun = false,
  onStart,
  etaHint = null,
  aiWorking = null,
}: LiveBrowserStageProps) {
  const live = LIVE_STATUSES.has(status);
  // 진짜 두 번째 브라우저 창(SSO 전자결재 팝업 등)이 열려 자식 화면이 있으면 탭 토글을 노출한다.
  const hasChild = screenshots.child != null;
  // 자식창은 부모를 덮는 게 아니라 부모 위로 뜨는 PIP 카드로 표현한다(실제 팝업 멘탈모델).
  // 부모는 항상 베이스에 유지, 자식 탭이 활성일 때만 그 위에 결제창 카드를 얹는다.
  const showChildPip = hasChild && activeWindow === 'child';
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
          {hasChild ? <WindowTabs active={activeWindow} onSelect={onSelectWindow} /> : null}
          <StatusBadge status={status} connected={connected} />
        </div>

        {/* 스크린캐스트 — 카드 폭이 곧 16:9 폭이므로 화면은 풀폭 + 16:9. */}
        {/* 스크린캐스트 종횡비(≈16:10, CDP 1280×800)에 맞춘 컨테이너 — LiveScreen 은 object-contain
            이라 잘림 없이 전체 프레임을 보여준다(종횡비를 맞춰 레터박스도 최소화). */}
        <div className="bg-muted/30 relative aspect-[16/10] w-full">
          {/* 베이스 = 항상 부모창(자식창이 떠도 뒤에 유지된다). */}
          <LiveScreen src={screenshots.parent} live={live} />
          {/* 자식창(전자결재 결제창) — 부모를 살짝 어둡게 깔고 그 위로 별도 카드로 띄운다. */}
          {showChildPip ? <ChildPipCard src={screenshots.child as string} /> : null}
          {/* AI 추천 계산 오버레이 — 화면 변화가 없는 긴 AI 콜 구간이 멈춰 보이지 않게, 라이브
              화면 중앙에 눈에 띄게 표시(우측 패널만으론 잘 안 보인다는 피드백). */}
          {aiWorking ? (
            <div className="bg-surface/70 absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 px-6 text-center backdrop-blur-[2px]">
              <RiSparkling2Fill size={30} aria-hidden className="animate-ai-sparkle text-accent" />
              <p className="ai-working-text text-sm font-semibold">
                {aiWorking} — AI가 계산하는 중…
              </p>
              <p className="text-foreground-tertiary text-xs">건수에 따라 수십 초 걸릴 수 있어요</p>
            </div>
          ) : null}
          {/* 실행 CTA — 우상단 버튼이 안 보인다는 피드백에 따라, 세션이 없거나(idle)
              종료됐을 때 화면 중앙에 대형 실행 진입점을 겹쳐 보여준다(실행 중엔 숨김). */}
          {onStart && !live ? (
            <StageRunCta status={status} canRun={canRun} onStart={onStart} etaHint={etaHint} />
          ) : null}
        </div>
      </section>
    </div>
  );
}

/**
 * 자식창 PIP 카드 — 전자결재 결제창(window.open 팝업)을 부모 화면 위에 뜨는 별도 창처럼 표현한다.
 *
 * 카드는 스테이지를 거의 꽉 채우는 고정 크기라 프레임 비율과 무관하게 좌우 여백(디밍된 부모)이
 * 최소화된다. 결제 폼은 카드 안에서 상단 고정 object-contain 으로 얹어, 세로가 길어도 잘리지 않고
 * 전체가 보인다. 부모는 뒤에서 dim 처리돼 "두 번째 창이 열렸다"는 맥락이 유지된다.
 */
function ChildPipCard({ src }: { src: string }) {
  return (
    <div className="bg-background/50 absolute inset-0 z-20 flex items-center justify-center p-2 backdrop-blur-[1.5px]">
      {/* 카드는 스테이지를 거의 꽉 채우는 고정 크기 — 프레임 비율과 무관하게 항상 넓게 유지해
          좌우 여백(디밍된 부모)을 최소화한다. 결제 폼은 카드 안에서 상단 고정 object-contain 으로
          전체를 보여준다(세로가 길면 하단 여백만 생기고 잘리지 않는다). */}
      <div className="animate-pip-in border-border bg-surface flex h-[97%] w-[98%] flex-col overflow-hidden rounded-[var(--radius-md)] border shadow-[var(--shadow-overlay)]">
        {/* 결제창 타이틀바 — 실제 창 크롬 느낌 */}
        <div className="border-border bg-surface-raised text-foreground-secondary flex shrink-0 items-center gap-1.5 border-b px-3 py-1.5 text-[11px] font-medium">
          <RiExternalLinkLine size={12} aria-hidden className="text-accent shrink-0" />
          전자결재 결제창
          <span className="text-foreground-tertiary ml-auto text-[10px] font-normal">자식 창</span>
        </div>
        <div className="relative min-h-0 flex-1">
          {/* eslint-disable-next-line @next/next/no-img-element -- dataURL 스트림이라 next/image 부적합 */}
          <img
            src={src}
            alt="전자결재 결제창"
            className="bg-surface-raised absolute inset-0 h-full w-full object-contain object-top"
          />
        </div>
      </div>
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
  etaHint,
}: {
  status: LiveRunStatus;
  canRun: boolean;
  onStart: () => void;
  etaHint: StageEtaHint | null;
}) {
  const terminal = status === 'succeeded' || status === 'failed';
  const title =
    status === 'succeeded' ? '실행 완료' : status === 'failed' ? '실행 실패' : '에이전트 실행';
  const description = terminal
    ? '같은 워크플로우를 새 세션으로 다시 실행할 수 있습니다.'
    : '라이브 브라우저 세션을 시작해 워크플로우를 단계별로 실행합니다.';
  // 소요 예고(실행 전에만) — "약 2분 소요 · 첫 입력 요청까지 ~30초"(승인 마이크로카피).
  // formatEta 는 "~2분" 형태라 총 소요는 접두 '~'를 '약 '으로 바꿔 카피를 맞춘다.
  const etaLine =
    !terminal && etaHint
      ? `약 ${formatEta(etaHint.totalMs).replace(/^~/, '')} 소요` +
        (etaHint.toFirstInterventionMs != null
          ? ` · 첫 입력 요청까지 ${formatEta(etaHint.toFirstInterventionMs)}`
          : '')
      : null;
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
        {etaLine ? (
          <p className="text-foreground-tertiary text-[11px] tracking-[0.04em] tabular-nums">
            {etaLine}
          </p>
        ) : null}
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

/**
 * 상태 배지 — 공용 RunStatusBadge 에 위임한다(색 의미는 domain-vocab-sections.tsx 기준).
 * 소켓 미연결(재연결 시도)만 이 컴포넌트가 로컬로 얹는 예외 — 런 상태값이 아니라
 * 연결성 표시이므로 status 를 'reconnecting' 으로 바꿔치기해 같은 배지를 재사용한다.
 */
function StatusBadge({ status, connected }: { status: LiveRunStatus; connected: boolean }) {
  const reconnecting = !connected && (status === 'running' || status === 'waiting_input');
  const effective: RunBadgeStatus = reconnecting ? 'reconnecting' : status;
  const dot: 'static' | 'pulse' =
    effective === 'idle' || effective === 'succeeded' || effective === 'failed'
      ? 'static'
      : 'pulse';
  return <RunStatusBadge status={effective} dot={dot} />;
}

/**
 * 부모창/자식창 세그먼트 토글 — 진짜 두 번째 브라우저 창(SSO 전자결재 팝업 등)이 열렸을 때만
 * 크롬 바 우측(상태 배지 옆)에 노출한다. 활성 창은 accent 로 채워 명확히, 비활성은 muted hover.
 */
function WindowTabs({
  active,
  onSelect,
}: {
  active: LiveWindow;
  onSelect?: (window: LiveWindow) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="브라우저 창 선택"
      className="border-border bg-surface flex shrink-0 items-center gap-0.5 rounded-[var(--radius-sm)] border p-0.5"
    >
      <WindowTab
        label="부모창"
        selected={active === 'parent'}
        onClick={() => onSelect?.('parent')}
      />
      <WindowTab label="자식창" selected={active === 'child'} onClick={() => onSelect?.('child')} />
    </div>
  );
}

function WindowTab({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      onClick={onClick}
      className={cn(
        'focus-visible:ring-accent rounded-[3px] px-2 py-0.5 text-[11px] font-medium transition-colors outline-none focus-visible:ring-2',
        selected
          ? 'bg-accent text-accent-foreground shadow-sm'
          : 'text-foreground-tertiary hover:bg-muted hover:text-foreground-secondary',
      )}
    >
      {label}
    </button>
  );
}
