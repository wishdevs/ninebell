'use client';

import { Fragment, useState } from 'react';
import {
  RiCheckLine,
  RiCloseLine,
  RiFullscreenExitLine,
  RiFullscreenLine,
  RiLoader4Line,
} from '@remixicon/react';
import type { Agent, WorkflowStep } from '@/lib/data/agents';
import type { FlowGraph, FlowNodeStatus } from '@/lib/data/flows';
import type { LiveRunStatus, LiveStepState, LiveStepStatus } from '@/lib/live/types';
import { cn } from '@/lib/utils';
import { AgentFlowGraph } from './agent-flow-graph';
import { WorkflowDetail } from './agent-side-panel';
import { LiveStepList } from './live-side-panel';

interface AgentProgressProps {
  agent: Agent;
  /** 라이브 세션이 활성일 때 true — 라이브 단계로 그린다. */
  isLive: boolean;
  status: LiveRunStatus;
  /** 라이브 런의 단계(run.steps). */
  steps: readonly LiveStepState[];
}

/**
 * 상단 단계 진행 — 기본은 컴팩트 1줄 스텝퍼(+ 라이브 진행률), 우측 "펼치기"로 상세 뷰 전환.
 * - 미실행: 이 에이전트의 단계 목록(`agent.steps`)을 중립으로 항상 노출(무슨 단계를 하는지).
 *   펼치면 각 단계의 상태·설명·하위단계까지 세로 타임라인으로.
 * - 라이브: `run.steps` 로 진행/완료/실패를 오버레이 + 진행률. 펼치면 단계별 타이밍 타임라인.
 */
export function AgentProgress({ agent, isLive, status, steps }: AgentProgressProps) {
  const [expanded, setExpanded] = useState(false);
  const done = steps.filter((s) => s.status === 'done').length;
  const progress = steps.length === 0 ? 0 : Math.round((done / steps.length) * 100);

  return (
    <section className="border-border bg-surface flex flex-col gap-3 rounded-[var(--radius-lg)] border px-4 py-3 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          {isLive ? (
            <LiveStepper steps={steps} status={status} />
          ) : (
            <PlanStepper steps={agent.steps} />
          )}
        </div>
        {isLive ? <ProgressMeter progress={progress} status={status} /> : null}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="border-border text-foreground-secondary hover:bg-muted hover:text-foreground inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1 text-[length:var(--text-body-sm)] font-medium transition-colors"
        >
          {expanded ? (
            <RiFullscreenExitLine size={14} aria-hidden />
          ) : (
            <RiFullscreenLine size={14} aria-hidden />
          )}
          {expanded ? '접기' : '펼치기'}
        </button>
      </div>

      {expanded ? (
        <div className="border-border border-t pt-3">
          {agent.flowGraph ? (
            // flowGraph 가 있으면 React Flow 그래프(노드·엣지·브랜치). 라이브면 run.steps 상태를
            // 노드에 오버레이(title 매칭), 미실행이면 중립 그래프 그대로.
            <AgentFlowGraph
              graph={isLive ? overlayFlow(agent.flowGraph, steps) : agent.flowGraph}
            />
          ) : (
            // 없으면 상세 세로 타임라인으로 폴백(라이브=run.steps, 미실행=agent.steps).
            <div className="max-h-[42vh] overflow-y-auto">
              {isLive ? (
                <LiveStepList steps={steps} status={status} />
              ) : (
                <WorkflowDetail steps={agent.steps} />
              )}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

/**
 * 라이브 run.steps 상태를 그래프 노드에 오버레이한다(노드 title ↔ 단계명 매칭).
 * 매칭되는 단계가 없으면 노드는 그대로(pending) — 즉, 최소한 그래프 구조는 항상 표시된다.
 */
function overlayFlow(graph: FlowGraph, steps: readonly LiveStepState[]): FlowGraph {
  if (steps.length === 0) return graph;
  const byTitle = new Map(steps.map((s) => [s.step, s.status]));
  return {
    ...graph,
    nodes: graph.nodes.map((n) => {
      const st = byTitle.get(n.title);
      if (!st) return n;
      const status: FlowNodeStatus =
        st === 'running' ? 'active' : st === 'failed' ? 'error' : 'done';
      return { ...n, status };
    }),
  };
}

function ProgressMeter({ progress, status }: { progress: number; status: LiveRunStatus }) {
  return (
    <div className="flex shrink-0 items-center gap-2">
      <div className="bg-muted h-1.5 w-24 overflow-hidden rounded-full">
        <div
          className={cn(
            'h-full rounded-full transition-[width] duration-500',
            status === 'failed'
              ? 'bg-danger'
              : status === 'succeeded'
                ? 'bg-success'
                : status === 'waiting_input'
                  ? 'bg-warning'
                  : 'bg-accent',
          )}
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="text-foreground text-[length:var(--text-body-sm)] font-semibold tabular-nums">
        {progress}%
      </span>
    </div>
  );
}

// ── 미실행 계획 스텝퍼(중립, 진행상태 없음) ──────────────────────────

function PlanStepper({ steps }: { steps: readonly WorkflowStep[] }) {
  if (steps.length === 0) {
    return (
      <span className="text-foreground-tertiary text-[length:var(--text-body-sm)]">
        등록된 단계가 없습니다.
      </span>
    );
  }
  return (
    <div className="no-scrollbar flex items-center gap-1 overflow-x-auto py-1">
      {steps.map((step, i) => (
        <Fragment key={step.id}>
          <div className="border-border bg-surface flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1">
            <span className="bg-muted text-muted-foreground flex size-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold tabular-nums">
              {i + 1}
            </span>
            <span className="text-foreground-secondary text-[length:var(--text-body-sm)] whitespace-nowrap">
              {step.label}
            </span>
          </div>
          {i < steps.length - 1 ? (
            <span aria-hidden className="bg-border-strong/60 h-px w-5 shrink-0" />
          ) : null}
        </Fragment>
      ))}
    </div>
  );
}

// ── 라이브 스텝퍼(진행/완료/실패) ────────────────────────────────────

const DOT: Record<LiveStepStatus, string> = {
  running: 'bg-accent/15 text-accent',
  done: 'bg-success/15 text-success',
  failed: 'bg-danger/15 text-danger',
};

const LABEL_TONE: Record<LiveStepStatus, string> = {
  running: 'text-foreground font-semibold',
  done: 'text-foreground-secondary',
  failed: 'text-danger font-semibold',
};

function LiveStepper({
  steps,
  status,
}: {
  steps: readonly LiveStepState[];
  status: LiveRunStatus;
}) {
  if (steps.length === 0) {
    return (
      <span className="text-foreground-secondary flex items-center gap-2 text-[length:var(--text-body-sm)]">
        <RiLoader4Line size={14} className="text-accent animate-spin" aria-hidden />
        {status === 'connecting' ? '라이브 세션에 연결하는 중…' : '첫 단계를 기다리는 중…'}
      </span>
    );
  }
  return (
    <div className="no-scrollbar flex items-center gap-1 overflow-x-auto py-1">
      {steps.map((step, i) => (
        <Fragment key={step.step}>
          <div
            className={cn(
              'flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1',
              step.status === 'running'
                ? 'border-accent bg-accent/5'
                : step.status === 'failed'
                  ? 'border-danger/40 bg-danger/5'
                  : 'border-border bg-surface',
            )}
          >
            <StepDot step={step} />
            <span
              className={cn(
                'text-[length:var(--text-body-sm)] whitespace-nowrap',
                LABEL_TONE[step.status],
              )}
            >
              {step.step}
            </span>
          </div>
          {i < steps.length - 1 ? (
            <span aria-hidden className="bg-accent h-px w-5 shrink-0" />
          ) : null}
        </Fragment>
      ))}
    </div>
  );
}

function StepDot({ step }: { step: LiveStepState }) {
  const base =
    'flex size-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold tabular-nums';
  if (step.status === 'done')
    return (
      <span className={cn(base, DOT.done)}>
        <RiCheckLine size={11} aria-hidden />
      </span>
    );
  if (step.status === 'failed')
    return (
      <span className={cn(base, DOT.failed)}>
        <RiCloseLine size={11} aria-hidden />
      </span>
    );
  return (
    <span className={cn(base, DOT.running)}>
      <RiLoader4Line size={11} className="animate-spin" aria-hidden />
    </span>
  );
}
