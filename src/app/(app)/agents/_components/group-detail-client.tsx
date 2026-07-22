'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { RiArrowLeftSLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { ListStatePanel } from '@/components/ui/list-state';
import { MetaChip } from '@/components/ui/meta-chip';
import { type Agent, filterVisibleAgents } from '@/lib/data/agents';
import { useFavorites } from '@/lib/live/use-favorites';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { AgentCard } from './agent-card';
import { GROUP_TOOLS, GroupTools } from './group-nav';

/**
 * 그룹 상세 — `/agents/groups/[groupId]`. `GET /agents`에서 해당 그룹 소속만 걸러 카드로 나열한다.
 * 최상위 목록(에이전트)에서 그룹 카드를 눌러 한 단계 더 들어온 화면이다. 그룹 기준정보(예산단위·
 * 프로젝트·거래처 관리)는 여기 헤더 우측에서 연다.
 */
export function GroupDetailClient({ groupId }: { groupId: string }) {
  const { status, data, error, reload } = useApiResource<Agent[]>('/agents');
  const fav = useFavorites('agent');
  const { loadIds } = fav;

  useEffect(() => {
    void loadIds();
  }, [loadIds]);

  // 숨김 대상(해외출장·경조금 등) 제외 후 그룹 필터(UI 전용).
  const agents = filterVisibleAgents(data ?? []).filter((a) => a.group?.id === groupId);
  const group = agents[0]?.group ?? null;

  return (
    <div className="flex max-w-[var(--content-max)] flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Link
          href="/agents"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-[length:var(--text-body-sm)] font-medium transition-colors"
        >
          <RiArrowLeftSLine size={15} aria-hidden />
          에이전트
        </Link>

        {group ? (
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <div className="flex items-center gap-2">
                <h1 className="text-foreground text-[length:var(--text-heading)] leading-tight font-semibold tracking-tight">
                  {group.name}
                </h1>
                <MetaChip className="tabular-nums">{agents.length}</MetaChip>
              </div>
              {group.description ? (
                <p className="text-muted-foreground text-xs leading-relaxed">{group.description}</p>
              ) : null}
            </div>
            {GROUP_TOOLS[group.id] ? <GroupTools tools={GROUP_TOOLS[group.id]} /> : null}
          </div>
        ) : null}
      </div>

      {/* loading/error/빈 상태 3분기는 ListStatePanel 이 단일 소유. */}
      <ListStatePanel
        phase={status === 'success' ? 'ready' : status}
        error={error}
        loadingLabel="에이전트를 불러오는 중…"
        errorTitle="에이전트를 불러오지 못했습니다"
        onRetry={reload}
        isEmpty={agents.length === 0}
        empty={{
          title: '그룹을 찾을 수 없습니다',
          description: '이 그룹에 속한 에이전트가 없습니다.',
          action: (
            <Button asChild variant="secondary" size="sm">
              <Link href="/agents">에이전트 목록으로</Link>
            </Button>
          ),
        }}
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              favorite={{
                active: fav.has(agent.id),
                onToggle: () => void fav.toggle(agent.id, agent.name),
              }}
            />
          ))}
        </div>
      </ListStatePanel>
    </div>
  );
}
