'use client';

import { Fragment, useEffect, useRef, useState } from 'react';
import {
  RiCheckLine,
  RiLoader4Line,
  RiFullscreenLine,
  RiFullscreenExitLine,
  RiCloseLine,
} from '@remixicon/react';
import type { Agent, StepStatus, WorkflowStep } from '@/lib/data/agents';
import { cn } from '@/lib/utils';
import { AgentFlow } from './agent-flow';
import { AgentFlowGraph } from './agent-flow-graph';

/**
 * 워크플로우 진행 영역.
 * - 기본: 단순화된 한 줄 스텝퍼(단계 점 + 라벨 + 연결선).
 * - "펼치기": React Flow 기반 상세 플로우(노드/엣지)로 확장.
 */
export function AgentWorkflow({ agent }: { agent: Agent }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="border-border bg-surface flex flex-col gap-3 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)]">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="grid gap-0.5">
          <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
            워크플로우
          </p>
          <h2 className="text-base font-semibold tracking-tight">단계 진행</h2>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="bg-muted h-1.5 w-28 overflow-hidden rounded-full">
              <div
                className={cn(
                  'h-full rounded-full',
                  agent.status === 'waiting_input' ? 'bg-warning' : 'bg-accent',
                )}
                style={{ width: `${agent.progress}%` }}
              />
            </div>
            <span className="text-foreground text-[length:var(--text-body-sm)] font-semibold tabular-nums">
              {agent.progress}%
            </span>
          </div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="border-border text-foreground-secondary hover:bg-muted hover:text-foreground inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-[length:var(--text-body-sm)] font-medium transition-colors"
          >
            {expanded ? (
              <RiFullscreenExitLine size={14} aria-hidden />
            ) : (
              <RiFullscreenLine size={14} aria-hidden />
            )}
            {expanded ? '접기' : '펼치기'}
          </button>
        </div>
      </header>

      {expanded ? (
        agent.flowGraph ? (
          <AgentFlowGraph graph={agent.flowGraph} />
        ) : (
          <AgentFlow steps={agent.steps} />
        )
      ) : (
        <SimplifiedSteps steps={agent.steps} />
      )}

      <p className="text-foreground-tertiary text-[11px]">
        {agent.flowGraph && expanded ? (
          <>
            분기·루프를 포함한 실제 업무 플로우입니다. 드래그로 이동, 좌하단 버튼으로 확대/축소할 수
            있습니다. 단순 보기는 주요 단계만 선형으로 요약합니다.
          </>
        ) : (
          <>
            구동 방식은 브라우저 조작·API 호출·하이브리드를 상정하지만, 현재는{' '}
            <span className="text-foreground-secondary font-medium">
              브라우저 조작(더존 옴니솔)
            </span>
            만 구현되어 있습니다.
          </>
        )}
      </p>
    </section>
  );
}

const DOT: Record<StepStatus, string> = {
  done: 'bg-success/15 text-success',
  active: 'bg-accent/15 text-accent',
  pending: 'bg-muted text-muted-foreground',
  error: 'bg-danger/15 text-danger',
};

const LABEL_TONE: Record<StepStatus, string> = {
  done: 'text-foreground-secondary',
  active: 'text-foreground font-semibold',
  pending: 'text-foreground-tertiary',
  error: 'text-danger font-semibold',
};

/** 단순화 기본 보기 — 한 줄 스텝퍼. 좁은 화면에서는 가로 스크롤하며,
 *  활성 단계를 컨테이너 가운데로 스크롤한다(이전/다음 이동 시 따라옴). */
function SimplifiedSteps({ steps }: { steps: readonly WorkflowStep[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);
  const activeId = steps.find((s) => s.status === 'active')?.id;

  useEffect(() => {
    const c = containerRef.current;
    const a = activeRef.current;
    if (!c || !a) return;
    const target = a.offsetLeft - (c.clientWidth - a.clientWidth) / 2;
    c.scrollTo({ left: Math.max(0, target), behavior: 'smooth' });
  }, [activeId]);

  return (
    <div ref={containerRef} className="no-scrollbar flex items-center gap-1 overflow-x-auto py-1">
      {steps.map((step, i) => (
        <Fragment key={step.id}>
          <div
            ref={step.status === 'active' ? activeRef : undefined}
            className={cn(
              'flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1',
              step.status === 'active'
                ? 'border-accent bg-accent/5'
                : step.status === 'error'
                  ? 'border-danger/40 bg-danger/5'
                  : 'border-border bg-surface',
            )}
          >
            <StepDot step={step} index={i} />
            <span
              className={cn(
                'text-[length:var(--text-body-sm)] whitespace-nowrap',
                LABEL_TONE[step.status],
              )}
            >
              {step.label}
            </span>
          </div>
          {i < steps.length - 1 ? (
            <span
              aria-hidden
              className={cn(
                'h-px w-5 shrink-0',
                steps[i + 1].status !== 'pending' ? 'bg-accent' : 'bg-border-strong/60',
              )}
            />
          ) : null}
        </Fragment>
      ))}
    </div>
  );
}

function StepDot({ step, index }: { step: WorkflowStep; index: number }) {
  const base =
    'flex size-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold tabular-nums';
  if (step.status === 'done')
    return (
      <span className={cn(base, DOT.done)}>
        <RiCheckLine size={11} aria-hidden />
      </span>
    );
  if (step.status === 'active')
    return (
      <span className={cn(base, DOT.active)}>
        <RiLoader4Line size={11} className="animate-spin" aria-hidden />
      </span>
    );
  if (step.status === 'error')
    return (
      <span className={cn(base, DOT.error)}>
        <RiCloseLine size={11} aria-hidden />
      </span>
    );
  return <span className={cn(base, DOT.pending)}>{index + 1}</span>;
}
