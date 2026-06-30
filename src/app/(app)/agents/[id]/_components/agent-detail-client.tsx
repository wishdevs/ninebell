'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import {
  RiBugLine,
  RiArrowLeftSLine,
  RiArrowRightSLine,
  RiRestartLine,
  RiSkipBackLine,
  RiStopLine,
} from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { type Agent, type StepStatus } from '@/lib/data/agents';
import { AgentSidePanel } from './agent-side-panel';
import { AgentWorkflow } from './agent-workflow';
import { BrowserStage } from './browser-stage';
import { SessionTimer } from './session-timer';

/** 디버그 단계 이동 바 노출 여부. 필요할 때 true로. */
const SHOW_DEBUG = false;

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
            <SessionTimer agent={agent} />
            <Controls agent={agent} />
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

      {/* 상단: 단계 진행(단순화 기본 · 펼치기 시 React Flow) */}
      <AgentWorkflow agent={view} />

      {/* 하단: 브라우저 열 폭을 16:9(높이 기준)로 잡고, 남는 가로는 우측 패널이 흡수해 넓어진다.
          브라우저 열 ≈ (가용 높이 − 크롬·푸터) × 16/9. 패널 최소 360px. */}
      <div className="grid grid-cols-1 gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-[clamp(320px,calc((100dvh-416px)*16/9),calc(100%-376px))_minmax(360px,1fr)] lg:items-stretch">
        <BrowserStage agent={view} />
        <AgentSidePanel agent={view} />
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

function Controls({ agent }: { agent: Agent }) {
  // 브라우저 큐(헤드리스 세션 슬롯)가 한정돼 있어 일시정지는 허용하지 않는다.
  // 라이브 세션을 점유한 상태에서는 "종료"만 — 세션을 닫고 큐를 반납한다.
  // 강하게 강조하지 않도록(빨강 채움 대신) 차분한 아웃라인 danger 톤으로 둔다.
  const isLive =
    agent.status === 'running' || agent.status === 'waiting_input' || agent.status === 'paused';
  if (isLive) {
    return (
      <Button
        size="sm"
        variant="secondary"
        className="text-danger border-danger/30 hover:bg-danger/10 hover:text-danger"
        onClick={() =>
          toast.warning('에이전트를 종료했습니다 — 세션을 닫고 브라우저 큐를 반납합니다.')
        }
      >
        <RiStopLine size={13} aria-hidden />
        종료
      </Button>
    );
  }
  return (
    <Button size="sm" onClick={() => toast.success('새 실시간 세션을 시작했습니다.')}>
      <RiRestartLine size={14} aria-hidden />
      다시 실행
    </Button>
  );
}
