'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { RiCheckLine, RiLoader4Line } from '@remixicon/react';
import { useTheme } from '@/components/theme-provider';
import type { FlowGraph, FlowGraphNode, FlowNodeKind, FlowNodeStatus } from '@/lib/data/flows';
import { cn } from '@/lib/utils';

interface GraphNodeData extends Record<string, unknown> {
  node: FlowGraphNode;
}

// 노드 종류별 색(시작·완료=green, 단계=blue/accent, 분기=amber/warning).
const KIND_CLASS: Record<FlowNodeKind, string> = {
  start: 'border-success/50 bg-success/10',
  end: 'border-success/50 bg-success/10',
  step: 'border-accent/40 bg-accent/5',
  decision: 'border-warning/50 bg-warning/10',
};

function GraphNode({ data }: NodeProps<Node<GraphNodeData>>) {
  const { node } = data;
  const pending = node.status === 'pending';
  return (
    <div
      className={cn(
        'relative w-[164px] rounded-[var(--radius-md)] border px-3 py-2 text-center shadow-[var(--shadow-card)] transition-opacity',
        KIND_CLASS[node.kind],
        node.status === 'active' && 'ring-accent/40 ring-2',
        pending && 'opacity-55',
      )}
    >
      {/* 가로 스파인: 좌(입력) → 우(출력). 루프는 상단 핸들로 위로 오버패스.
          되돌이 대상(증빙유형)은 두 상단 타깃(ta/tb)으로 받아 중첩을 피한다. */}
      <Handle
        id="l"
        type="target"
        position={Position.Left}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />
      <Handle
        id="ts"
        type="source"
        position={Position.Top}
        style={{ left: '50%' }}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />
      <Handle
        id="ta"
        type="target"
        position={Position.Top}
        style={{ left: '38%' }}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />
      <Handle
        id="tb"
        type="target"
        position={Position.Top}
        style={{ left: '62%' }}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />

      <StatusMark status={node.status} />
      <p className="text-foreground text-[length:var(--text-body-sm)] leading-tight font-semibold">
        {node.title}
      </p>
      {node.sub ? (
        <p className="text-foreground-tertiary mt-0.5 text-[10px] leading-tight">{node.sub}</p>
      ) : null}

      <Handle
        id="r"
        type="source"
        position={Position.Right}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />
      {/* 스킵 분기(한 종류일 때 분리등록 건너뜀)는 스파인 아래로 우회. */}
      <Handle
        id="bs"
        type="source"
        position={Position.Bottom}
        style={{ left: '44%' }}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />
      <Handle
        id="bt"
        type="target"
        position={Position.Bottom}
        style={{ left: '56%' }}
        className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
      />
    </div>
  );
}

function StatusMark({ status }: { status: FlowNodeStatus }) {
  if (status === 'done')
    return (
      <span className="bg-success text-background absolute -top-1.5 -right-1.5 flex size-4 items-center justify-center rounded-full">
        <RiCheckLine size={10} aria-hidden />
      </span>
    );
  if (status === 'active')
    return (
      <span className="bg-accent text-accent-foreground absolute -top-1.5 -right-1.5 flex size-4 items-center justify-center rounded-full">
        <RiLoader4Line size={10} className="animate-spin" aria-hidden />
      </span>
    );
  return null;
}

const nodeTypes = { graph: GraphNode };

// 펼치기 최초 배율 — 기본보다 두 단계(줌 스텝 ×1.2씩) 더 크게: 0.82 × 1.2² ≈ 1.18.
const VIEW_ZOOM = 1.18;
const NODE_W = 164;
const NODE_H = 56;

export function AgentFlowGraph({ graph }: { graph: FlowGraph }) {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const colorMode = mounted && resolvedTheme === 'dark' ? 'dark' : 'light';

  // 활성(진행 중) 노드를 뷰 가운데로 — 이전/다음으로 단계가 바뀌면 따라 이동한다.
  const rfRef = useRef<ReactFlowInstance<Node<GraphNodeData>, Edge> | null>(null);
  const activeNode = useMemo(() => graph.nodes.find((n) => n.status === 'active'), [graph.nodes]);
  const activeId = activeNode?.id;

  const centerOn = useCallback((node: FlowGraphNode | undefined, duration: number) => {
    if (!rfRef.current || !node) return;
    rfRef.current.setCenter(node.x + NODE_W / 2, node.y + NODE_H / 2, {
      zoom: VIEW_ZOOM,
      duration,
    });
  }, []);

  useEffect(() => {
    centerOn(activeNode, 450);
    // activeId가 바뀔 때만 — 노드 객체 동일성은 무시.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  const reached = useMemo(() => {
    const set = new Set<string>();
    for (const n of graph.nodes) if (n.status !== 'pending') set.add(n.id);
    return set;
  }, [graph.nodes]);

  const nodes = useMemo<Node<GraphNodeData>[]>(
    () =>
      graph.nodes.map((node) => ({
        id: node.id,
        type: 'graph',
        position: { x: node.x, y: node.y },
        data: { node },
        draggable: false,
        selectable: false,
      })),
    [graph.nodes],
  );

  // 루프 엣지는 스팬(되돌이 거리)이 짧은 것부터 안쪽(낮은 오버패스)에 배치해
  // 두 루프가 겹치지 않고 중첩(nesting)되도록 핸들/높이를 분배한다.
  const loopMeta = useMemo(() => {
    const xById = new Map(graph.nodes.map((n) => [n.id, n.x] as const));
    const loops = graph.edges
      .filter((e) => e.kind === 'loop')
      .map((e) => ({
        id: e.id,
        span: Math.abs((xById.get(e.source) ?? 0) - (xById.get(e.target) ?? 0)),
      }))
      .sort((a, b) => a.span - b.span);
    const meta = new Map<string, { handle: 'ta' | 'tb'; offset: number }>();
    loops.forEach((l, i) => meta.set(l.id, { handle: i === 0 ? 'tb' : 'ta', offset: 24 + i * 30 }));
    return meta;
  }, [graph.nodes, graph.edges]);

  const edges = useMemo<Edge[]>(
    () =>
      graph.edges.map((e) => {
        const isLoop = e.kind === 'loop';
        const isSkip = e.kind === 'skip';
        const isReached = reached.has(e.target) || (!isLoop && !isSkip && reached.has(e.source));
        const stroke = isLoop
          ? 'var(--color-warning)'
          : isSkip
            ? 'var(--color-border-strong)'
            : isReached
              ? 'var(--color-accent)'
              : 'var(--color-border-strong)';
        const loop = loopMeta.get(e.id);
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          // 메인/분기: 우→좌(스파인). 루프: 상단 오버패스(중첩). 스킵: 하단 우회.
          sourceHandle: isLoop ? 'ts' : isSkip ? 'bs' : 'r',
          targetHandle: isLoop ? (loop?.handle ?? 'ta') : isSkip ? 'bt' : 'l',
          type: 'smoothstep',
          pathOptions: isLoop
            ? { offset: loop?.offset ?? 24, borderRadius: 10 }
            : isSkip
              ? { offset: 26, borderRadius: 10 }
              : { borderRadius: 8 },
          label: e.label,
          labelShowBg: true,
          labelBgPadding: [5, 2] as [number, number],
          labelBgBorderRadius: 4,
          labelStyle: { fill: 'var(--color-foreground-secondary)', fontSize: 10, fontWeight: 600 },
          labelBgStyle: {
            fill: 'var(--color-surface)',
            stroke: 'var(--color-border)',
            strokeWidth: 1,
          },
          style: { stroke, strokeWidth: 1.75, strokeDasharray: isLoop ? '5 4' : undefined },
          markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 14, height: 14 },
        };
      }),
    [graph.edges, reached, loopMeta],
  );

  return (
    <div className="bg-muted/20 border-border h-[360px] w-full overflow-hidden rounded-[var(--radius-md)] border">
      <ReactFlow
        colorMode={colorMode}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={(inst) => {
          rfRef.current = inst;
          centerOn(activeNode, 0);
        }}
        defaultViewport={{ x: 28, y: 34, zoom: VIEW_ZOOM }}
        minZoom={0.4}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        zoomOnDoubleClick={false}
        panOnDrag
        proOptions={{ hideAttribution: true }}
        className="!bg-transparent"
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={18}
          size={1}
          color="var(--color-border)"
        />
        <Controls showInteractive={false} className="!shadow-[var(--shadow-card)]" />
      </ReactFlow>
    </div>
  );
}
