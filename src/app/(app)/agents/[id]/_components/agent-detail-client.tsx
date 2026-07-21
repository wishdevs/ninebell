'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import {
  RiBugLine,
  RiArrowLeftSLine,
  RiArrowRightSLine,
  RiErrorWarningLine,
  RiCloseLine,
  RiPlayLine,
  RiRestartLine,
  RiSkipBackLine,
  RiStopLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { InlineConfirm } from '@/components/ui/inline-confirm';
import { cn } from '@/lib/utils';
import { type Agent, type StepStatus } from '@/lib/data/agents';
import { newRunId, useLiveRun } from '@/lib/live/use-live-run';
import {
  requestHitlNotificationPermission,
  useHitlNotification,
  useRunTerminalNotification,
} from '@/lib/live/use-hitl-notification';
import { PRE_RUN_FORMS } from '@/components/live/pre-run';
import { AgentSidePanel } from './agent-side-panel';
import { LiveBrowserStage, type StageEtaHint } from './live-browser-stage';
import { LiveSidePanel } from './live-side-panel';
import { SessionStatus } from './session-status';

/** 디버그 단계 이동 바 노출 여부. 필요할 때 true로. */
const SHOW_DEBUG = false;

function statusAt(pos: number, current: number): StepStatus {
  return pos < current ? 'done' : pos === current ? 'active' : 'pending';
}

/**
 * 디버그용 — 현재 단계를 `current`로 두었을 때의 에이전트 뷰를 만든다.
 * steps 노드 상태(완료/진행/대기)·진행률·현재 동작을 함께 재계산해
 * 모든 화면(간략 스텝퍼·브라우저·사이드패널)이 같이 움직이게 한다.
 */
function deriveAgentAtStep(agent: Agent, current: number): Agent {
  const steps = agent.steps.map((s, i) => {
    const st = statusAt(i, current);
    return {
      ...s,
      status: st,
      substeps: s.substeps?.map((ss) => ({ ...ss, status: st === 'active' ? ss.status : st })),
    };
  });
  const total = agent.steps.length;
  const progress = total <= 1 ? 100 : Math.round((current / (total - 1)) * 100);
  const label = agent.steps[current]?.label ?? '';
  return {
    ...agent,
    steps,
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
  // 실행 워크플로우 id 는 서버가 내려주는 agent.workflowId(단일 소스). 없으면 이 에이전트는
  // 실행 불가(하드코딩 매핑·demo-echo 폴백 제거) → 실행 컨트롤을 비활성화한다.
  const defaultWorkflow = agent.workflowId;
  const canRun = !!defaultWorkflow;
  // 실행 전 입력 폼 — 이 워크플로우가 폼 레지스트리에 있으면 idle 에서 폼으로 파라미터를
  // 받아 실행한다(card-chat 등 폼 없는 에이전트는 종전대로 바로 실행). 없으면 undefined.
  const PreRunForm = canRun ? PRE_RUN_FORMS[defaultWorkflow] : undefined;
  const usePreRun = !!PreRunForm;
  // runId 를 시작마다 새로 발급해 훅에 넘긴다 — 재마운트(StrictMode)·끊김 재접속은 같은
  // runId 로 세션을 재부착하고, "다시 실행"은 새 runId 라 새 흐름을 시작한다.
  const [session, setSession] = useState<{
    workflowId: string;
    runId: string;
    enabled: boolean;
    /** 실행 전 폼이 구성한 워크플로우 파라미터(그래프 state.params). 폼 없는 에이전트는 undefined. */
    params?: Record<string, unknown>;
  }>({
    workflowId: defaultWorkflow ?? '',
    runId: '',
    enabled: false,
  });
  const run = useLiveRun(session.workflowId, {
    runId: session.enabled ? session.runId : undefined,
    enabled: session.enabled,
    params: session.enabled ? session.params : undefined,
  });
  const startRun = (workflowId: string, params?: Record<string, unknown>) => {
    // 알림 권한은 사용자 제스처(실행 버튼 클릭) 컨텍스트에서 1회 요청해야 프롬프트가 뜬다.
    requestHitlNotificationPermission();
    setSession({ workflowId, runId: newRunId(), enabled: true, params });
  };
  // 실행 전 폼 제출 → 마지막 값을 폼 시드로 보관(종료 후 값 수정 재실행)하고 실행 시작.
  const [formSeed, setFormSeed] = useState<Record<string, unknown> | undefined>(undefined);
  const [formRunSeq, setFormRunSeq] = useState(0);
  const startFromForm = (params: Record<string, unknown>) => {
    setFormSeed(params);
    setFormRunSeq((n) => n + 1); // remount 키 — 시드가 폼 초기값으로 다시 반영되게.
    startRun(defaultWorkflow!, params);
  };
  // 세션 종료 시 실행 파라미터를 비운다(stale params 로 실저장 재발 방지). 폼 시드는 별도 유지.
  const stopRun = () => setSession((s) => ({ ...s, enabled: false, params: undefined }));
  const isLive = session.enabled;
  const terminal = run.status === 'succeeded' || run.status === 'failed';
  // 개입(HITL) 대기 중이면 우측 패널을 넓혀 개입 카드에 화면을 양보한다(브라우저 열은 축소).
  // 종류(chat/choice/grid) 무관하게 개입 자체에 적용 — 스테이지는 컨테이너 쿼리로 자가 적응한다.
  const interventionActive = isLive && run.hitl != null;
  // 실행 전 입력 폼(출장 등)도 개입과 동일하게 취급 — 미실행 상태에서 폼(표/그리드 입력)에 화면을
  // 양보하고 라이브 브라우저 열은 축소한다(사용자 요청: 최초 입력 시 입력창을 크게).
  const preRunActive = usePreRun && !isLive;
  const panelWide = interventionActive || preRunActive;
  // 개입 레이아웃 레벨(3) — 개입 콘텐츠(kind)별로 라이브화면 노출·크기 + 개입 패널 크기를 정한다.
  //  full : 라이브화면 숨김 + 개입 전체폭  — grid(카드처럼 입력 항목이 그리드일 때)
  //  split: 작은 라이브(좌측) + 넓은 개입   — choice·chat, 실행 전 입력 폼
  //  live : 라이브 크게 + 작은 패널          — 개입 없는 모니터링(읽기 전용 관찰)
  const layoutLevel: 'full' | 'split' | 'live' =
    interventionActive && run.hitl?.kind === 'grid' ? 'full' : panelWide ? 'split' : 'live';

  // AI 추천 계산 구간(skillKey='ai-recommend' 스텝이 running) — 화면 변화가 없어 멈춰 보이는
  // 긴 AI 콜을 라이브 화면에 눈에 띄게 오버레이한다(우측 패널만으론 잘 안 보인다는 피드백).
  // run.steps.step(라이브 상태 키)을 agent.steps.id(계획)와 매칭해 skillKey 를 확인한다.
  const aiWorkingLabel = useMemo(() => {
    if (!isLive) return null;
    const running = new Set(run.steps.filter((s) => s.status === 'running').map((s) => s.step));
    const step = agent.steps.find((p) => p.skillKey === 'ai-recommend' && running.has(p.id));
    return step?.label ?? null;
  }, [isLive, run.steps, agent.steps]);

  // 개입 대기 알림 — 탭 제목 접두 + (백그라운드 탭이면) 브라우저 알림. 해소·종료 시 원복.
  useHitlNotification(interventionActive ? (run.hitl?.id ?? null) : null);

  // 완료 알림 — 런이 종료(성공/실패)로 전환되면 동일 채널(탭 제목·토스트·브라우저 알림)로.
  useRunTerminalNotification(isLive && terminal ? (run.status as 'succeeded' | 'failed') : null);

  // 실행 전 소요 예고(ETA) — 이력 기반 expectedMs 가 모든 자동 스텝에 있을 때만 계산한다
  // (하나라도 없으면 null → 부분 데이터로 엉터리 합계를 만들지 않는다. 개입 스텝은 사람
  // 시간이라 예측에서 제외). 스테이지 CTA 아래 "약 N분 소요 · 첫 입력 요청까지 ~N초"에 쓴다.
  const etaHint = useMemo<StageEtaHint | null>(() => {
    const autos = agent.steps.filter((s) => !s.intervention);
    if (autos.length === 0 || autos.some((s) => s.expectedMs == null)) return null;
    const totalMs = autos.reduce((acc, s) => acc + (s.expectedMs ?? 0), 0);
    const firstInterventionIdx = agent.steps.findIndex((s) => s.intervention);
    const toFirstInterventionMs =
      firstInterventionIdx < 0
        ? null
        : agent.steps
            .slice(0, firstInterventionIdx)
            .reduce((acc, s) => (s.intervention ? acc : acc + (s.expectedMs ?? 0)), 0);
    return { totalMs, toFirstInterventionMs };
  }, [agent.steps]);

  // (템플릿 탭·'템플릿으로 저장'은 사용자 요청으로 제거 — 2026-07-06. 백엔드 템플릿
  //  API 는 유지되며 UI 진입점만 없다.)

  return (
    <div className="flex w-full flex-col gap-4 lg:min-h-0 lg:flex-1">
      {/* 헤더 */}
      <div className="flex flex-col gap-3">
        {/* 브레드크럼 — "에이전트 › 그룹명". 그룹 소속이면 상위(뒤로)는 그룹으로, 각 단계는 링크.
            그룹명이 링크라 에이전트 → 그룹(1단계 위)로 빠져나갈 수 있다(루트로 건너뛰지 않음). */}
        <div className="text-muted-foreground inline-flex w-fit items-center gap-1 text-[length:var(--text-body-sm)] font-medium">
          <RiArrowLeftSLine size={15} aria-hidden className="text-foreground-tertiary" />
          <Link href="/agents" className="hover:text-foreground transition-colors">
            에이전트
          </Link>
          {agent.group ? (
            <>
              <span aria-hidden className="text-foreground-tertiary">
                ›
              </span>
              <Link
                href={`/agents/groups/${agent.group.id}`}
                className="hover:text-foreground transition-colors"
              >
                {agent.group.name}
              </Link>
            </>
          ) : null}
        </div>

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
              canRun={canRun}
              // 실행 전 폼 에이전트는 헤더 실행을 막고 폼 제출로 시작하게 안내한다.
              preRunHint={usePreRun ? '아래 입력을 완료하고 실행하세요.' : undefined}
              // 무개입 실저장 에이전트는 원클릭 '다시 실행'을 막는다 — 종료 후 '닫기'로
              // 폼에 복귀해 값을 검토·수정하고 다시 실행(중복 저장 방지).
              hideRestart={usePreRun}
              onStartReal={() => defaultWorkflow && startRun(defaultWorkflow)}
              onRestart={() => startRun(session.workflowId, session.params)}
              onStop={stopRun}
            />
          </div>
        </div>
      </div>

      {/* 실패 사유 배너 — 종료(실패) 시 '왜 실패했고 무엇을 고칠지'를 메인 상단에 크게 노출한다.
          결과 탭에도 나오지만 그리드 개입/브라우저 스테이지를 보느라 놓치기 쉬워, 메인에 무조건
          보이게 둔다(사용자 피드백: 실패했는데 이유를 안 알려줌). error 는 여러 줄(사유+조치)일 수 있다. */}
      {isLive && terminal && run.status === 'failed' && run.error ? (
        <div className="border-danger/30 bg-danger/10 text-danger flex items-start gap-2.5 rounded-[var(--radius-md)] border px-4 py-3">
          <RiErrorWarningLine size={18} aria-hidden className="mt-0.5 shrink-0" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <p className="text-[length:var(--text-body-sm)] font-semibold">실행 실패 — 사유</p>
            <p className="text-foreground-secondary text-[length:var(--text-body-sm)] leading-relaxed whitespace-pre-line">
              {run.error}
            </p>
          </div>
        </div>
      ) : null}

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
      <div
        className={cn(
          'grid grid-cols-1 gap-4 transition-[grid-template-columns] duration-500 ease-out lg:min-h-0 lg:flex-1 lg:items-stretch',
          layoutLevel === 'full'
            ? 'lg:grid-cols-1' // 라이브 숨김 — 개입 패널이 전체폭
            : layoutLevel === 'split'
              ? 'lg:grid-cols-[minmax(280px,380px)_minmax(0,1fr)]'
              : 'lg:grid-cols-[clamp(320px,calc((100dvh-180px)*16/10),calc(100%-440px))_minmax(360px,1fr)]',
        )}
      >
        {/* 라이브 스테이지 — full 레벨(그리드 개입)에선 숨겨 개입 패널에 전체폭을 준다. 그 외엔
            미실행 시 idle 중립 대기 화면(가짜 LIVE 노출 안 함), idle/종료엔 중앙 대형 실행 CTA 겹침. */}
        {layoutLevel !== 'full' ? (
          <LiveBrowserStage
            targetUrl={agent.targetUrl}
            status={run.status}
            screenshots={run.screenshots}
            activeWindow={run.activeWindow}
            onSelectWindow={run.selectWindow}
            connected={run.connected}
            canRun={canRun}
            etaHint={etaHint}
            aiWorking={aiWorkingLabel}
            // 실행 전 폼 에이전트는 스테이지 중앙 CTA 를 항상 숨긴다(폼 제출이 유일한 실행
            // 진입점) — idle 은 폼이, 종료 후엔 '닫기'로 폼 복귀가 실행을 주도한다.
            onStart={
              usePreRun
                ? undefined
                : () => {
                    const workflowId =
                      (isLive ? session.workflowId : defaultWorkflow) || defaultWorkflow;
                    if (workflowId) startRun(workflowId, session.params);
                  }
            }
          />
        ) : null}
        {isLive ? (
          <LiveSidePanel run={run} planSteps={agent.steps} handoffNote={agent.handoffNote} />
        ) : PreRunForm ? (
          // key 로 remount 해 마지막 제출값(formSeed)을 폼 초기값으로 다시 시드한다(실패 후 수정 재실행).
          <PreRunForm
            key={formRunSeq}
            agent={agent}
            initialParams={formSeed}
            onStart={startFromForm}
          />
        ) : (
          <AgentSidePanel agent={view} />
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
  /** 실행 워크플로우가 매핑돼 있는지. false 면 '실행' 비활성화(이 에이전트는 실행 불가). */
  canRun: boolean;
  /**
   * 실행 전 입력 폼이 있는 에이전트면 헤더 '실행'을 비활성화하고 이 문구를 툴팁으로 보여준다
   * (실행은 폼 제출로 시작). 없으면(undefined) 종전 동작 그대로.
   */
  preRunHint?: string;
  /** true 면 종료 후 원클릭 '다시 실행'을 숨긴다(무개입 실저장 에이전트 — '닫기'로 폼 복귀만). */
  hideRestart?: boolean;
  onStartReal: () => void;
  onRestart: () => void;
  onStop: () => void;
}

/**
 * 라이브 실행 컨트롤. 브라우저 큐(헤드리스 세션 슬롯)가 한정돼 일시정지는 없다 —
 * 진행 중에는 "실행 중단"(슬롯 반납)만, 종료 후에는 "닫기/다시 실행". 시작 전에는 "실행".
 * 중단은 진행 중 작업이 끊기는 파괴적 동작이라 인라인 확인을 거친다(원클릭 즉시 종료 방지).
 */
function LiveControls({
  enabled,
  terminal,
  canRun,
  preRunHint,
  hideRestart,
  onStartReal,
  onRestart,
  onStop,
}: LiveControlsProps) {
  // 실행 중단 인라인 확인 — 개입학습 '전체 삭제'와 같은 패턴. 실행 상태가 바뀌면 초기화.
  const [confirmStop, setConfirmStop] = useState(false);
  useEffect(() => {
    setConfirmStop(false);
  }, [enabled, terminal]);

  if (!enabled) {
    const disabled = !canRun || !!preRunHint;
    const title = !canRun
      ? '실행 가능한 워크플로우가 연결되지 않은 에이전트입니다.'
      : (preRunHint ?? undefined);
    return (
      <Button size="sm" onClick={onStartReal} disabled={disabled} title={title}>
        <RiPlayLine size={14} aria-hidden />
        실행
      </Button>
    );
  }
  if (terminal) {
    return (
      <div className="flex items-center gap-2">
        <Button size="sm" variant={hideRestart ? 'primary' : 'secondary'} onClick={onStop}>
          <RiCloseLine size={14} aria-hidden />
          닫기
        </Button>
        {hideRestart ? null : (
          <Button size="sm" onClick={onRestart}>
            <RiRestartLine size={14} aria-hidden />
            다시 실행
          </Button>
        )}
      </div>
    );
  }
  if (confirmStop) {
    return (
      <InlineConfirm
        question="실행을 중단할까요? 진행 중 작업이 끊깁니다"
        confirmLabel="중단"
        onConfirm={() => {
          setConfirmStop(false);
          onStop();
        }}
        onCancel={() => setConfirmStop(false)}
      />
    );
  }
  return (
    <Button
      size="sm"
      variant="secondary"
      className="text-danger border-danger/30 hover:bg-danger/10 hover:text-danger"
      onClick={() => setConfirmStop(true)}
    >
      <RiStopLine size={13} aria-hidden />
      실행 중단
    </Button>
  );
}
