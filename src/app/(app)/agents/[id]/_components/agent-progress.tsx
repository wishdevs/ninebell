'use client';

import { useState } from 'react';
import { RiFullscreenExitLine, RiFullscreenLine } from '@remixicon/react';
import type { Agent } from '@/lib/data/agents';
import type { FlowGraph, FlowNodeStatus } from '@/lib/data/flows';
import type { LiveRunStatus, LiveStepState } from '@/lib/live/types';
import { AgentFlowGraph } from './agent-flow-graph';
import { WorkflowDetail } from './agent-side-panel';
import { LiveStepList } from './live-side-panel';

interface AgentProgressProps {
  agent: Agent;
  /** 라이브 세션이 활성일 때 true. */
  isLive: boolean;
  status: LiveRunStatus;
  /** 라이브 런의 단계(run.steps) — 그래프 노드 상태 오버레이/타임라인 폴백에 쓴다. */
  steps: readonly LiveStepState[];
}

/**
 * 상단 워크플로우 그래프 영역 — 상단에 단계를 죽 나열하지 않고, 작은 토글로만 접근한다.
 * - 접힘: "워크플로우 그래프 펼치기" 토글 버튼만(영역 최소).
 * - 펼침: flowGraph 있으면 React Flow 상세 그래프(라이브 시 run.steps 를 노드에 오버레이),
 *   없으면 상세 세로 타임라인(라이브=run.steps / 미실행=agent.steps).
 */
export function AgentProgress({ agent, isLive, status, steps }: AgentProgressProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="border-border bg-surface flex flex-col gap-3 rounded-[var(--radius-lg)] border px-4 py-3 shadow-[var(--shadow-card)]">
      <div className="flex items-center">
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
          {expanded ? '워크플로우 그래프 접기' : '워크플로우 그래프 펼치기'}
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
