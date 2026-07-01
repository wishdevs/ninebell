'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import {
  RiBugLine,
  RiArrowLeftSLine,
  RiArrowRightSLine,
  RiCloseLine,
  RiPlayLine,
  RiRestartLine,
  RiSkipBackLine,
  RiStopLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { type Agent, type StepStatus } from '@/lib/data/agents';
import { newRunId, useLiveRun } from '@/lib/live/use-live-run';
import type { RunsPanelProps } from './agent-runs-panel';
import { AgentSidePanel } from './agent-side-panel';
import { LiveBrowserStage } from './live-browser-stage';
import { LiveSidePanel } from './live-side-panel';
import { SaveTemplateButton } from './save-template-button';
import { SessionStatus } from './session-status';

/** 디버그 단계 이동 바 노출 여부. 필요할 때 true로. */
const SHOW_DEBUG = false;

/**
 * 상세 에이전트 id → 엔진에 등록된 라이브 워크플로우 id.
 * 현재 등록분: `demo-echo`(P2, 자격증명 불필요) · `expense-card-chat`(P3, 실 옴니솔/Gemini 필요).
 * 매핑 없으면 라이브 레이어를 검증할 수 있게 demo-echo 로 폴백한다.
 */
const WORKFLOW_BY_AGENT: Record<string, string> = {
  'card-chat': 'expense-card-chat',
};

function resolveWorkflow(agentId: string): string {
  return WORKFLOW_BY_AGENT[agentId] ?? 'demo-echo';
}

function statusAt(pos: number, current: number): StepStatus {
  return pos < current ? 'done' : pos === current ? 'active' : 'pending';
}

/**
 * 디버그용 — 현재 단계를 `current`로 두었을 때의 에이전트 뷰를 만든다.
 * steps와 flowGraph 노드 상태(완료/진행/대기)·진행률·현재 동작을 함께 재계산해
 * 모든 화면(간략 스텝퍼·그래프·브라우저·사이드패널)이 같이 움직이게 한다.
 */
function deriveAgentAtStep(agent: Agent, current: number): Agent {
  const idxById = new Map(agent.steps.map((s, i) => [s.id, i] as const));
  const steps = agent.steps.map((s, i) => {
    const st = statusAt(i, current);
    return {
      ...s,
      status: st,
      substeps: s.substeps?.map((ss) => ({ ...ss, status: st === 'active' ? ss.status : st })),
    };
  });
  const flowGraph = agent.flowGraph
    ? {
        ...agent.flowGraph,
        nodes: agent.flowGraph.nodes.map((n) => ({
          ...n,
          status: statusAt(idxById.get(n.id) ?? 0, current),
        })),
      }
    : undefined;
  const total = agent.steps.length;
  const progress = total <= 1 ? 100 : Math.round((current / (total - 1)) * 100);
  const label = agent.steps[current]?.label ?? '';
  return {
    ...agent,
    steps,
    flowGraph,
    progress,
    currentAction: `[디버그] ${label} 단계로 이동 (${current + 1}/${total})`,
  };
}

export function AgentDetailClient({ agent }: { agent: Agent }) {
  const total = agent.steps.length;
  const initial = useMemo(() => {
    const active = agent.steps.findIndex((s) => s.status === 'active');
    if (active >= 0) return active;
    const done = agent.steps.filter((s) => s.status === 'done').length;
    return Math.min(done, Math.max(0, total - 1));
  }, [agent.steps, total]);

  const [step, setStep] = useState(initial);
  // 디버그가 꺼져 있으면 픽스처 그대로(원래 currentAction 유지), 켜져 있으면 단계 파생.
  const view = useMemo(() => (SHOW_DEBUG ? deriveAgentAtStep(agent, step) : agent), [agent, step]);

  // 라이브 세션 — 실행 컨트롤(시작/종료)로 enabled 를 토글한다. 카드에 머무는 동안만
  // 세션(헤드리스 브라우저 슬롯)을 점유하고, 언마운트/종료 시 useLiveRun 이 abort 로 반납한다.
  const defaultWorkflow = useMemo(() => resolveWorkflow(agent.id), [agent.id]);
  // runId 를 시작마다 새로 발급해 훅에 넘긴다 — 재마운트(StrictMode)·끊김 재접속은 같은
  // runId 로 세션을 재부착하고, "다시 실행"은 새 runId 라 새 흐름을 시작한다.
  const [session, setSession] = useState<{
    workflowId: string;
    runId: string;
    enabled: boolean;
    /** 지정되면 이 런은 템플릿 AUTO 재생(대화 없이 저장된 selections 적용). */
    templateId?: string;
  }>({
    workflowId: defaultWorkflow,
    runId: '',
    enabled: false,
  });
  const run = useLiveRun(session.workflowId, {
    runId: session.enabled ? session.runId : undefined,
    enabled: session.enabled,
    templateId: session.enabled ? session.templateId : undefined,
  });
  const startRun = (workflowId: string, templateId?: string) =>
    setSession({ workflowId, runId: newRunId(), enabled: true, templateId });
  const stopRun = () => setSession((s) => ({ ...s, enabled: false }));
  const isLive = session.enabled;
  const terminal = run.status === 'succeeded' || run.status === 'failed';

  // 이력·템플릿 새로고침 트리거 — 런이 끝나거나 템플릿을 저장하면 올려서 재조회한다.
  const [refreshKey, setRefreshKey] = useState(0);
  const bumpRefresh = () => setRefreshKey((k) => k + 1);
  useEffect(() => {
    if (terminal) setRefreshKey((k) => k + 1);
  }, [terminal]);

  // 대화형 런이 성공적으로 끝났을 때만 '템플릿으로 저장'을 노출(재생/데모는 selections 없음).
  const canSaveTemplate =
    isLive && run.status === 'succeeded' && !session.templateId && !!run.runId;

  // 실행 이력·템플릿 — 우측 사이드 패널의 탭으로 주입(하단 별도 패널에서 이동).
  const runsPanel: RunsPanelProps = {
    agentId: defaultWorkflow,
    refreshKey,
    onReplay: (templateId) => startRun(defaultWorkflow, templateId),
    replayDisabled: isLive && !terminal,
  };

  return (
    <div className="flex w-full flex-col gap-4 lg:min-h-0 lg:flex-1">
      {/* 헤더 */}
      <div className="flex flex-col gap-3">
        <Link
          href="/agents"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-[length:var(--text-body-sm)] font-medium transition-colors"
        >
          <RiArrowLeftSLine size={15} aria-hidden />
          에이전트
        </Link>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-2.5">
            <h1 className="text-foreground text-[length:var(--text-heading)] leading-tight font-semibold tracking-tight">
              {agent.name}
            </h1>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2">
            <SessionStatus isLive={isLive} status={run.status} />
            <LiveControls
              enabled={isLive}
              terminal={terminal}
              showRealStart={defaultWorkflow !== 'demo-echo'}
              onStartReal={() => startRun(defaultWorkflow)}
              onStartDemo={() => startRun('demo-echo')}
              onRestart={() => startRun(session.workflowId)}
              onStop={stopRun}
            />
          </div>
        </div>
      </div>

      {/* 디버그 — 단계 이동(이전/다음). 현재는 숨김(SHOW_DEBUG로 토글). */}
      {SHOW_DEBUG ? (
        <DebugStepper
          step={step}
          total={total}
          label={agent.steps[step]?.label ?? ''}
          progress={view.progress}
          onPrev={() => setStep((s) => Math.max(0, s - 1))}
          onNext={() => setStep((s) => Math.min(total - 1, s + 1))}
          onFirst={() => setStep(0)}
        />
      ) : null}

      {/* 상단 단계 섹션은 제거 — 세로 공간을 브라우저에 양보한다. 워크플로우 그래프는 우측
          '워크플로우' 탭에서 크게 본다(브라우저와 세로 공간 경쟁을 피함). */}

      {/* 브라우저 + 우측 패널. 상단 섹션이 없어 그리드가 남는 높이를 전부 쓴다. 브라우저 열 폭은
          스크린캐스트 종횡비(≈16:10)에 맞춰 (가용 높이)×16/10 로 잡아 화면이 잘리지 않고 꽉
          차게(레터박스 최소), 좌우로 과하게 넓지 않게 하고 패널 최소폭(≈440px)은 유지한다. */}
      <div className="grid grid-cols-1 gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-[clamp(320px,calc((100dvh-180px)*16/10),calc(100%-440px))_minmax(360px,1fr)] lg:items-stretch">
        {/* 브라우저는 항상 라이브 스테이지 — 미실행 시 run 은 idle 상태라 중립 대기 화면을
            보여준다(정적 목업의 가짜 LIVE/진행률을 노출하지 않는다). */}
        <LiveBrowserStage
          targetUrl={agent.targetUrl}
          status={run.status}
          screenshot={run.screenshot}
          connected={run.connected}
        />
        {isLive ? (
          <LiveSidePanel
            run={run}
            runsPanel={runsPanel}
            workflowId={session.workflowId}
            resultAction={
              canSaveTemplate && run.runId ? (
                <SaveTemplateButton
                  runId={run.runId}
                  agentId={defaultWorkflow}
                  onSaved={bumpRefresh}
                />
              ) : undefined
            }
          />
        ) : (
          <AgentSidePanel agent={view} runsPanel={runsPanel} />
        )}
      </div>
    </div>
  );
}

interface DebugStepperProps {
  step: number;
  total: number;
  label: string;
  progress: number;
  onPrev: () => void;
  onNext: () => void;
  onFirst: () => void;
}

function DebugStepper({
  step,
  total,
  label,
  progress,
  onPrev,
  onNext,
  onFirst,
}: DebugStepperProps) {
  const atStart = step <= 0;
  const atEnd = step >= total - 1;
  return (
    <div className="border-warning/40 bg-warning/5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[var(--radius-md)] border border-dashed px-3 py-2">
      <span className="bg-warning/15 text-warning inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wider uppercase">
        <RiBugLine size={11} aria-hidden />
        디버그
      </span>
      <span className="text-foreground-secondary text-[length:var(--text-body-sm)]">단계 이동</span>

      <div className="flex items-center gap-1.5">
        <Button
          size="sm"
          variant="secondary"
          onClick={onFirst}
          disabled={atStart}
          aria-label="첫 단계로"
        >
          <RiSkipBackLine size={13} aria-hidden />
          처음
        </Button>
        <Button size="sm" variant="secondary" onClick={onPrev} disabled={atStart}>
          <RiArrowLeftSLine size={14} aria-hidden />
          이전
        </Button>
        <Button size="sm" onClick={onNext} disabled={atEnd}>
          다음
          <RiArrowRightSLine size={14} aria-hidden />
        </Button>
      </div>

      <span className="text-foreground-tertiary text-[length:var(--text-body-sm)]">
        단계{' '}
        <span className="text-foreground font-semibold tabular-nums">
          {step + 1}/{total}
        </span>
        {label ? <span className="text-foreground-secondary"> · {label}</span> : null}
      </span>

      <span className="text-foreground-tertiary ml-auto text-[11px]">
        진행률{' '}
        <span className="text-foreground-secondary font-semibold tabular-nums">{progress}%</span>
      </span>
    </div>
  );
}

interface LiveControlsProps {
  enabled: boolean;
  terminal: boolean;
  /** demo-echo 외에 매핑된 실 워크플로우가 있으면 별도 "실행" 버튼을 노출. */
  showRealStart: boolean;
  onStartReal: () => void;
  onStartDemo: () => void;
  onRestart: () => void;
  onStop: () => void;
}

/**
 * 라이브 실행 컨트롤. 브라우저 큐(헤드리스 세션 슬롯)가 한정돼 일시정지는 없다 —
 * 진행 중에는 "종료"(슬롯 반납)만, 종료 후에는 "닫기/다시 실행". 시작 시 실 워크플로우가
 * 있으면 "실행"과 함께, demo-echo 로 라이브 레이어를 검증할 "데모 실행"을 항상 제공한다.
 */
function LiveControls({
  enabled,
  terminal,
  showRealStart,
  onStartReal,
  onStartDemo,
  onRestart,
  onStop,
}: LiveControlsProps) {
  if (!enabled) {
    return (
      <div className="flex items-center gap-2">
        {showRealStart ? (
          <Button size="sm" onClick={onStartReal}>
            <RiPlayLine size={14} aria-hidden />
            실행
          </Button>
        ) : null}
        <Button size="sm" variant={showRealStart ? 'secondary' : 'primary'} onClick={onStartDemo}>
          <RiPlayLine size={14} aria-hidden />
          데모 실행
        </Button>
      </div>
    );
  }
  if (terminal) {
    return (
      <div className="flex items-center gap-2">
        <Button size="sm" variant="secondary" onClick={onStop}>
          <RiCloseLine size={14} aria-hidden />
          닫기
        </Button>
        <Button size="sm" onClick={onRestart}>
          <RiRestartLine size={14} aria-hidden />
          다시 실행
        </Button>
      </div>
    );
  }
  return (
    <Button
      size="sm"
      variant="secondary"
      className="text-danger border-danger/30 hover:bg-danger/10 hover:text-danger"
      onClick={onStop}
    >
      <RiStopLine size={13} aria-hidden />
      종료
    </Button>
  );
}
