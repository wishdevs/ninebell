'use client';

import { useEffect } from 'react';
import { PageHeader } from '@/components/ui/page-header';
import { ListStatePanel } from '@/components/ui/list-state';
import { type Agent, filterVisibleAgents } from '@/lib/data/agents';
import { useFavorites } from '@/lib/live/use-favorites';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { AgentCard } from './agent-card';
import { GroupCard } from './group-nav';

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
  // 해외출장·경조금 등 숨김 대상은 목록에서 제외(UI 전용 — 백엔드·실행은 그대로).
  const visible = filterVisibleAgents(data ?? []);

  // 마운트 시 내 즐겨찾기(kind=agent)를 불러와 ★ 상태를 채운다.
  useEffect(() => {
    void loadIds();
  }, [loadIds]);

  return (
    <div className="flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="자동화"
        title="에이전트"
        description="반복되는 업무를 대신 처리하는 자동화입니다. 할 일을 고르면 알아서 진행하고, 중요한 선택만 직접 확인하면 됩니다."
      />

      {/* loading/error/빈 상태 3분기는 ListStatePanel 이 단일 소유. */}
      <ListStatePanel
        phase={status === 'success' ? 'ready' : status}
        error={error}
        loadingLabel="에이전트를 불러오는 중…"
        errorTitle="에이전트를 불러오지 못했습니다"
        onRetry={reload}
        isEmpty={visible.length === 0}
        empty={{
          title: '등록된 에이전트가 없습니다',
          description: '아직 사용할 수 있는 에이전트가 없습니다.',
        }}
      >
        {(() => {
          const sections = groupSections(visible);
          // 그룹 = 폴더형 카드(클릭 시 상세로 한 단계 이동), 단독 에이전트 = 실행 카드. 한 그리드에 섞는다.
          // 그룹이 새 에이전트로 불어나도 최상위는 카드 1장으로 유지된다(평평하게 깔리지 않음).
          const groupCards = sections.filter((s) => s.group);
          const standalone =
            sections.find((s) => !s.group)?.agents ?? (sections.length === 0 ? [...visible] : []);
          return (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {groupCards.map((section) => (
                <GroupCard key={section.group!.id} group={section.group!} agents={section.agents} />
              ))}
              {standalone.map((agent) => (
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
        })()}
      </ListStatePanel>
    </div>
  );
}
