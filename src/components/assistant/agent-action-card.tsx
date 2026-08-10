'use client';

import Link from 'next/link';
import { RiArrowRightSLine, RiHistoryLine, RiPlayLine, RiRobot2Line } from '@remixicon/react';
import { PERMISSIONS } from '@/lib/auth/permissions';
import { useCan } from '@/components/permissions/perm-gate';
import { cn } from '@/lib/utils';
import { StatusBadge } from '@/components/ui/status-badge';
import type { AssistantAction, AssistantSnapshot } from '@/lib/assistant/types';

const CHIP =
  'inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-2.5 py-1 text-[11px] font-medium transition-colors';

/**
 * 액션의 id 를 마운트 시 스냅샷에서 해석할 수 있는지. 런 스냅샷은 최근 8건만 담으므로 모델이
 * 더 오래된 런을 가리키면 false 가 될 수 있다. 말풍선 캡션과 카드 렌더를 일치시키는 데 쓴다.
 */
export function isActionResolvable(action: AssistantAction, snapshot: AssistantSnapshot): boolean {
  return action.kind === 'run'
    ? snapshot.runs.some((r) => r.id === action.runId)
    : snapshot.agents.some((a) => a.id === action.agentId);
}

/**
 * 모델이 결정한 액션을 네비게이션 카드로 렌더한다. 실행 트리거는 없고 이동만 한다
 * (실행은 에이전트 상세의 라이브 UI에서). 스냅샷에서 id 를 못 찾으면 렌더하지 않는다.
 */
export function AgentActionCard({
  action,
  snapshot,
}: {
  action: AssistantAction;
  snapshot: AssistantSnapshot;
}) {
  const canReadLogs = useCan(PERMISSIONS.LOGS_READ);

  if (action.kind === 'run') {
    const run = snapshot.runs.find((r) => r.id === action.runId);
    if (!run) return null;
    return (
      <div className="border-accent/30 bg-accent/5 mt-2 rounded-[var(--radius-md)] border p-3">
        <p className="text-accent text-[10px] font-semibold tracking-widest uppercase">실행</p>
        <div className="text-foreground mt-1 flex items-center gap-2 text-[13px]">
          <span className="font-mono font-semibold">{run.id}</span>
          {/* 런 상태 원문 노출 대신 공용 배지 사용(디자인시스템 정리 WS6) */}
          <StatusBadge status={run.status} />
        </div>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <Link
            href={`/agents/${run.agentId}`}
            className={cn(CHIP, 'bg-accent/15 text-accent hover:bg-accent/25')}
          >
            <RiRobot2Line size={13} aria-hidden />
            에이전트 열기
          </Link>
          {canReadLogs ? (
            <Link
              href="/logs"
              className={cn(CHIP, 'bg-muted text-muted-foreground hover:text-foreground')}
            >
              <RiHistoryLine size={13} aria-hidden />
              로깅에서 보기
            </Link>
          ) : null}
        </div>
      </div>
    );
  }

  const agent = snapshot.agents.find((a) => a.id === action.agentId);
  if (!agent) return null;
  const emphasizeRun = action.intent === 'run' && agent.runnable;

  return (
    <div className="border-accent/30 bg-accent/5 mt-2 rounded-[var(--radius-md)] border p-3">
      <p className="text-accent text-[10px] font-semibold tracking-widest uppercase">에이전트</p>
      <div className="text-foreground mt-1 text-[13px] font-semibold">{agent.name}</div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <Link
          href={`/agents/${agent.id}`}
          className={cn(
            CHIP,
            emphasizeRun
              ? 'bg-accent text-accent-foreground hover:bg-accent/90'
              : 'bg-muted text-muted-foreground hover:text-foreground',
          )}
        >
          {emphasizeRun ? <RiPlayLine size={13} aria-hidden /> : null}
          {emphasizeRun ? '실행하러 가기' : '에이전트 열기'}
          {emphasizeRun ? null : <RiArrowRightSLine size={13} aria-hidden />}
        </Link>
      </div>
    </div>
  );
}
