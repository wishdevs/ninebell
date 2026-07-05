'use client';

import { useEffect } from 'react';
import { RiErrorWarningLine } from '@remixicon/react';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { Button } from '@/components/ui/button';
import { MetaChip } from '@/components/ui/meta-chip';
import type { Agent } from '@/lib/data/agents';
import { useFavorites } from '@/lib/live/use-favorites';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { AgentCard } from './agent-card';

interface GroupSection {
  /** null = 단독 에이전트 섹션. */
  group: NonNullable<Agent['group']> | null;
  agents: Agent[];
}

/**
 * 그룹별 섹션으로 묶는다(등장 순서 유지). 그룹 소속 섹션이 먼저, 단독(group null)은
 * 마지막 섹션. 그룹이 하나도 없으면 빈 배열을 반환해 기존 플랫 그리드로 렌더한다.
 */
function groupSections(agents: readonly Agent[]): GroupSection[] {
  if (!agents.some((a) => a.group)) return [];
  const byId = new Map<string, GroupSection>();
  const standalone: Agent[] = [];
  for (const agent of agents) {
    if (!agent.group) {
      standalone.push(agent);
      continue;
    }
    const section = byId.get(agent.group.id);
    if (section) {
      section.agents.push(agent);
    } else {
      byId.set(agent.group.id, { group: agent.group, agents: [agent] });
    }
  }
  const sections = [...byId.values()];
  if (standalone.length > 0) sections.push({ group: null, agents: standalone });
  return sections;
}

/**
 * 에이전트 카탈로그. 저장된 에이전트 정의를 `GET /agents`로 불러와 카드로 보여준다.
 * 에이전트는 워커로 상주하지 않으며(카드를 열 때 라이브 세션 시작, 화면을 벗어나면
 * 종료), 리스트에서는 실행 이력만 노출한다. 그룹(2뎁스 분류)이 있으면 섹션으로 묶는다.
 *
 * 카드 우상단 ★ = 자주쓰는 에이전트 토글(kind='agent', 낙관적 반영+실패 롤백) —
 * 홈 '자주쓰는 에이전트' 섹션의 소스가 된다.
 */
export function AgentsClient() {
  const { status, data, error, reload } = useApiResource<Agent[]>('/agents');
  const fav = useFavorites('agent');
  const { loadIds } = fav;

  // 마운트 시 내 즐겨찾기(kind=agent)를 불러와 ★ 상태를 채운다.
  useEffect(() => {
    void loadIds();
  }, [loadIds]);

  return (
    <div className="flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="자동화"
        title="에이전트"
        description="실행할 업무를 고르기만 하면 됩니다. 에이전트가 더존 화면을 대신 조작하고, 진행 과정을 실시간으로 보여주며 증빙·프로젝트 같은 중요한 선택은 직접 승인하면 됩니다."
      />

      {status === 'loading' ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} label="에이전트 불러오는 중" />
          에이전트를 불러오는 중…
        </div>
      ) : status === 'error' ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="에이전트를 불러오지 못했습니다"
          description={error?.status === 0 ? '서버에 연결할 수 없습니다.' : (error?.message ?? '')}
          action={
            <Button variant="secondary" size="sm" onClick={reload}>
              다시 시도
            </Button>
          }
        />
      ) : (data?.length ?? 0) === 0 ? (
        <EmptyState
          title="등록된 에이전트가 없습니다"
          description="아직 사용할 수 있는 에이전트가 없습니다."
        />
      ) : (

        (() => {
          const sections = groupSections(data ?? []);
          if (sections.length === 0) {
            // 그룹이 전혀 없으면 기존처럼 플랫 그리드(헤더 없음).
            return (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {data?.map((agent) => (
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
            );
          }
          return (
            <div className="flex flex-col gap-8">
              {sections.map((section) => (
                <section
                  key={section.group?.id ?? '__standalone'}
                  aria-label={section.group?.name ?? '단독 에이전트'}
                  className="flex flex-col gap-3"
                >
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <h2 className="text-foreground text-[length:var(--text-body-lg)] font-semibold tracking-tight">
                        {section.group?.name ?? '단독 에이전트'}
                      </h2>
                      <MetaChip className="tabular-nums">{section.agents.length}</MetaChip>
                    </div>
                    {section.group?.description ? (
                      <p className="text-muted-foreground truncate text-xs leading-relaxed">
                        {section.group.description}
                      </p>
                    ) : null}
                  </div>
                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    {section.agents.map((agent) => (
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
                </section>
              ))}
            </div>
          );
        })()
      )}
    </div>
  );
}
