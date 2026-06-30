'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { RiCheckLine, RiLoader4Line, RiCloseLine } from '@remixicon/react';
import { useTheme } from '@/components/theme-provider';
import type { StepStatus, WorkflowStep } from '@/lib/data/agents';
import { cn } from '@/lib/utils';

interface StepNodeData extends Record<string, unknown> {
  step: WorkflowStep;
  index: number;
}

const NODE_W = 168;
const NODE_GAP = 56;

const STATUS_RING: Record<StepStatus, string> = {
  done: 'border-success/50 bg-success/5',
  active: 'border-accent bg-accent/5 ring-2 ring-accent/30',
  pending: 'border-border bg-surface',
  error: 'border-danger/50 bg-danger/5',
};

function StepNode({ data }: NodeProps<Node<StepNodeData>>) {
  const { step, index } = data;
  return (
    <div
      className={cn(
        'flex w-[168px] flex-col gap-1 rounded-[var(--radius-md)] border px-3 py-2.5 shadow-[var(--shadow-card)] transition-colors',
        STATUS_RING[step.status],
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />
      <div className="flex items-center gap-1.5">
        <StepStatusDot status={step.status} index={index} />
        <span className="text-foreground truncate text-[length:var(--text-body-sm)] font-semibold">
          {step.label}
        </span>
      </div>
      {step.skill ? (
        <span className="text-foreground-tertiary truncate pl-6 text-[10px]">{step.skill}</span>
      ) : null}
      <Handle
        type="source"
        position={Position.Right}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />
    </div>
  );
}

function StepStatusDot({ status, index }: { status: StepStatus; index: number }) {
  const base =
    'flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold';
  if (status === 'done')
    return (
      <span className={cn(base, 'bg-success/15 text-success')}>
        <RiCheckLine size={11} aria-hidden />
      </span>
    );
  if (status === 'active')
    return (
      <span className={cn(base, 'bg-accent/15 text-accent')}>
        <RiLoader4Line size={11} className="animate-spin" aria-hidden />
      </span>
    );
  if (status === 'error')
    return (
      <span className={cn(base, 'bg-danger/15 text-danger')}>
        <RiCloseLine size={11} aria-hidden />
      </span>
    );
  return (
    <span className={cn(base, 'bg-muted text-muted-foreground tabular-nums')}>{index + 1}</span>
  );
}

const nodeTypes = { step: StepNode };

/**
 * 상단 간략 워크플로우 시각화(React Flow). 단계 노드를 좌→우로 배치하고
 * 상태별로 색을 입힌다. 정적 표시이므로 드래그/줌은 비활성화한다.
 */
export function AgentFlow({ steps }: { steps: readonly WorkflowStep[] }) {
  const { resolvedTheme } = useTheme();
  // next-themes는 서버에서 테마를 모르므로, 첫 렌더는 항상 'light'로 SSR과
  // 일치시키고 마운트 이후에만 실제 테마를 반영한다(하이드레이션 안전).
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const colorMode = mounted && resolvedTheme === 'dark' ? 'dark' : 'light';

  const nodes = useMemo<Node<StepNodeData>[]>(
    () =>
      steps.map((step, index) => ({
        id: step.id,
        type: 'step',
        position: { x: index * (NODE_W + NODE_GAP), y: 0 },
        data: { step, index },
        draggable: false,
        selectable: false,
      })),
    [steps],
  );

  const edges = useMemo<Edge[]>(
    () =>
      steps.slice(1).map((step, i) => {
        const prev = steps[i];
        const reached = step.status !== 'pending';
        const isActiveEdge = step.status === 'active';
        const stroke =
          step.status === 'error'
            ? 'var(--color-danger)'
            : reached
              ? 'var(--color-accent)'
              : 'var(--color-border-strong)';
        return {
          id: `${prev.id}-${step.id}`,
          source: prev.id,
          target: step.id,
          animated: isActiveEdge,
          style: { stroke, strokeWidth: 1.75 },
          markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 16, height: 16 },
        };
      }),
    [steps],
  );

  return (
    <div className="h-[150px] w-full">
      <ReactFlow
        colorMode={colorMode}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnDoubleClick={false}
        zoomOnPinch={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        className="!bg-transparent"
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={18}
          size={1}
          color="var(--color-border)"
        />
      </ReactFlow>
    </div>
  );
}
