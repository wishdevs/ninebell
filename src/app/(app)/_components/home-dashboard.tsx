'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import { RiErrorWarningLine, RiPlayCircleLine } from '@remixicon/react';
import { BentoCell, BentoGrid } from '@/components/ui/bento-grid';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionCard } from '@/components/ui/section-card';
import { Skeleton } from '@/components/ui/skeleton';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { usePermissions } from '@/hooks/use-permissions';
import { PERMISSIONS } from '@/lib/auth/permissions';
import type { Agent } from '@/lib/data/agents';
import type { RunSummary } from '@/lib/live/runs-api';
import { HomeGreeting } from './home-greeting';
import { HomeKpiTiles } from './home-kpi-tiles';
import { HomeRecentRuns } from './home-recent-runs';

/**
 * 홈 대시보드 — 인사 헤더 + KPI 타일 + 최근 실행 이력 + 바로 실행 CTA.
 *
 * 데이터는 두 갈래를 클라이언트에서 로드한다(세션이 httpOnly 쿠키라
 * 클라이언트 훅 {@link useApiResource} 패턴을 따른다):
 * - `GET /runs?limit=30` — 실행 이력 표본(최신순, 본인 스코프 — 관리자는 전체).
 *   응답 envelope 은 `{ runs: RunSummary[], total: number }`.
 * - `GET /agents` — 런의 workflow id(`run.agentId`)를 에이전트 페이지 id·이름으로
 *   역해석하기 위한 카탈로그(agents:read 있을 때만).
 */

/** KPI 표본 + 최근 목록의 원천 window(런 최신순 상위 N건). */
const RUNS_WINDOW = 30;

/** 바로 실행 CTA 대상 — "결의서 입력 - 카드"(현재 유일한 실동작 에이전트). */
const QUICK_RUN_AGENT_ID = 'card-chat';

interface RunsEnvelope {
  runs: RunSummary[];
  total: number;
}

export function HomeDashboard() {
  const { has } = usePermissions();
  const canAgents = has(PERMISSIONS.AGENTS_READ);
  const canViewLogs = has(PERMISSIONS.LOGS_READ);

  const runsRes = useApiResource<RunsEnvelope>(`/runs?limit=${RUNS_WINDOW}`);
  // 에이전트 카탈로그는 이름 해석·CTA 용도 — 권한이 없으면 호출 자체를 생략.
  const agentsRes = useApiResource<Agent[]>(canAgents ? '/agents' : null);

  const runs = runsRes.data?.runs ?? [];
  const total = runsRes.data?.total ?? 0;

  /** workflow id → 에이전트(페이지 id·이름). 카탈로그 미로드/미등록이면 null. */
  const agentByWorkflow = useMemo(() => {
    const map = new Map<string, { id: string; name: string }>();
    for (const a of agentsRes.data ?? []) {
      if (a.workflowId) map.set(a.workflowId, { id: a.id, name: a.name });
    }
    return map;
  }, [agentsRes.data]);

  const quickAgent =
    agentsRes.data?.find((a) => a.id === QUICK_RUN_AGENT_ID) ?? null;
  // 카탈로그 로딩 중에는 CTA 자리를 비워두지 않도록 스켈레톤을 유지한다.
  const quickAgentPending = canAgents && agentsRes.status === 'loading';
  const showQuickCell = quickAgentPending || quickAgent !== null;

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <HomeGreeting />

      {runsRes.status === 'error' ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="실행 현황을 불러오지 못했습니다"
          description={
            runsRes.error?.status === 0
              ? '서버에 연결할 수 없습니다.'
              : (runsRes.error?.message ?? '')
          }
          action={
            <Button variant="secondary" size="sm" onClick={runsRes.reload}>
              다시 시도
            </Button>
          }
        />
      ) : (
        <>
          <HomeKpiTiles
            loading={runsRes.status === 'loading'}
            runs={runs}
            total={total}
            resolveAgentName={(workflowId) =>
              agentByWorkflow.get(workflowId)?.name ?? workflowId
            }
          />

          <BentoGrid>
            <BentoCell span={showQuickCell ? 8 : 12}>
              <HomeRecentRuns
                loading={runsRes.status === 'loading'}
                runs={runs}
                canOpenAgents={canAgents}
                canViewLogs={canViewLogs}
                resolveAgent={(workflowId) => agentByWorkflow.get(workflowId) ?? null}
              />
            </BentoCell>

            {showQuickCell ? (
              <BentoCell span={4}>
                {quickAgent ? (
                  <QuickRunCard agent={quickAgent} />
                ) : (
                  <QuickRunSkeleton />
                )}
              </BentoCell>
            ) : null}
          </BentoGrid>
        </>
      )}
    </div>
  );
}

// ── 바로 실행 CTA ────────────────────────────────────────────────────

/** 실행 트리거는 범위 밖 — 상세 페이지로 잇기만 한다(실행은 상세에서 시작). */
function QuickRunCard({ agent }: { agent: Agent }) {
  return (
    <SectionCard caption="바로 실행" title={agent.name} description={agent.description} className="h-full">
      <div className="mt-auto">
        <Button asChild>
          <Link href={`/agents/${agent.id}`}>
            <RiPlayCircleLine size={16} aria-hidden />
            바로 실행
          </Link>
        </Button>
      </div>
    </SectionCard>
  );
}

function QuickRunSkeleton() {
  return (
    <SectionCard className="h-full">
      <div className="flex flex-col gap-3" role="status" aria-busy>
        <Skeleton className="h-3 w-14" />
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-9 w-28" />
      </div>
    </SectionCard>
  );
}
