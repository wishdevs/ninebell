'use client';

import Link from 'next/link';
import { RiHistoryLine } from '@remixicon/react';
import { SectionCard } from '@/components/ui/section-card';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyHint } from '@/components/ui/empty-hint';
import { cn } from '@/lib/utils';
import { formatDateTime } from '@/lib/data/format';
import type { RunStatus, RunSummary } from '@/lib/live/runs-api';

/**
 * 홈 — 최근 실행 목록. "어제 처리했나"를 3초에 확인하는 게 목적이라
 * 행마다 에이전트명·시각·상태·결과 한 줄만 담고, 행 전체를 에이전트
 * 상세(`/agents/{id}`)로 잇는다(실행·재실행은 상세에서).
 */

/** 홈 목록에 표시할 최근 실행 행 수(원천 표본에서 앞에서 자른다). */
const RECENT_LIMIT = 8;

interface ResolvedAgent {
  /** 에이전트 상세 페이지 id(`/agents/{id}`). */
  id: string;
  name: string;
}

interface HomeRecentRunsProps {
  loading: boolean;
  /** 최근 표본(최신순) — 이 컴포넌트가 앞 {@link RECENT_LIMIT}건만 그린다. */
  runs: RunSummary[];
  /** agents:read 가 있어야 행을 상세로 링크한다(없으면 정적 행). */
  canOpenAgents: boolean;
  /** logs:read 관리자에게만 전체 로깅 링크를 노출. */
  canViewLogs: boolean;
  /** 런의 workflow id → 에이전트(페이지 id·이름). 미등록/미로드면 null. */
  resolveAgent: (workflowId: string) => ResolvedAgent | null;
}

export function HomeRecentRuns({
  loading,
  runs,
  canOpenAgents,
  canViewLogs,
  resolveAgent,
}: HomeRecentRunsProps) {
  const rows = runs.slice(0, RECENT_LIMIT);

  return (
    <SectionCard
      caption="실행 이력"
      title="최근 실행"
      description="최근에 실행한 에이전트와 결과입니다."
      action={
        canViewLogs ? (
          <Link
            href="/logs"
            className="text-muted-foreground hover:text-foreground text-xs font-medium transition-colors"
          >
            전체 로깅 →
          </Link>
        ) : undefined
      }
      className="h-full"
    >
      {loading ? (
        <ul className="flex flex-col gap-1" role="status" aria-busy>
          {Array.from({ length: 4 }, (_, i) => (
            <li key={i} className="flex items-center gap-3 px-2 py-2.5">
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <Skeleton className="h-3.5 w-40" />
                <Skeleton className="h-3 w-64" />
              </div>
              <Skeleton className="h-3 w-24" />
            </li>
          ))}
        </ul>
      ) : rows.length === 0 ? (
        <EmptyHint
          icon={<RiHistoryLine size={14} aria-hidden />}
          title="아직 실행 이력이 없습니다"
          description="에이전트를 실행하면 여기에서 결과를 바로 확인할 수 있습니다."
        />
      ) : (
        <ul className="flex flex-col">
          {rows.map((run) => (
            <RunRow
              key={run.id}
              run={run}
              agent={resolveAgent(run.agentId)}
              canOpenAgents={canOpenAgents}
            />
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function RunRow({
  run,
  agent,
  canOpenAgents,
}: {
  run: RunSummary;
  agent: ResolvedAgent | null;
  canOpenAgents: boolean;
}) {
  const summary = run.resultSummary?.trim() || (run.failedStep ? `실패 단계: ${run.failedStep}` : null);

  const body = (
    <>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span className="text-foreground truncate text-sm font-medium">
            {agent?.name ?? run.agentId}
          </span>
          <RunStatusBadge status={run.status} />
        </div>
        <p className="text-muted-foreground truncate text-xs" title={summary ?? undefined}>
          {summary ?? '—'}
        </p>
      </div>
      <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
        {run.startedAt ? formatDateTime(run.startedAt) : '—'}
      </span>
    </>
  );

  const rowClass =
    'border-border-subtle flex items-center gap-3 border-b px-2 py-2.5 last:border-0';

  // agents:read + 등록된 에이전트일 때만 상세로 링크(그 외엔 정적 행).
  if (canOpenAgents && agent) {
    return (
      <li>
        <Link
          href={`/agents/${agent.id}`}
          className={cn(rowClass, 'row-hover -mx-2 rounded-[var(--radius-sm)]')}
        >
          {body}
        </Link>
      </li>
    );
  }
  return <li className={rowClass}>{body}</li>;
}

// ── 상태 배지(런 상태 어휘) ──────────────────────────────────────────
// 공용 StatusBadge(ui/status-badge.tsx)는 GEO 배치 어휘(completed 등)라
// 런 상태(succeeded/waiting_input/…)를 모른다 — 로깅 화면(logs-client)과
// 동일한 파일-로컬 배지 관례를 따른다.

const STATUS_STYLE: Record<string, { className: string; label: string }> = {
  running: { className: 'border-accent/30 bg-accent/10 text-accent', label: '실행 중' },
  waiting_input: { className: 'border-warning/30 bg-warning/10 text-warning', label: '개입 대기' },
  succeeded: { className: 'border-success/30 bg-success/10 text-success', label: '완료' },
  failed: { className: 'border-danger/30 bg-danger/10 text-danger', label: '실패' },
  cancelled: { className: 'border-border bg-muted text-muted-foreground', label: '종료됨' },
};

function RunStatusBadge({ status }: { status: RunStatus }) {
  const style = STATUS_STYLE[status] ?? {
    className: 'border-border bg-muted text-muted-foreground',
    label: status,
  };
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider',
        style.className,
      )}
    >
      {style.label}
    </span>
  );
}
