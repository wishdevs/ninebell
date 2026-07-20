'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  RiArrowRightSLine,
  RiErrorWarningLine,
  RiLockLine,
  RiSettings3Line,
  RiShieldKeyholeLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { usePermissions } from '@/hooks/use-permissions';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { ApiError, api, errorMessage, toApiError } from '@/lib/api/client';
import type { Agent } from '@/lib/data/agents';
import { AgentSettingsCard } from './agent-settings-card';
import { ManageGroupCard } from './manage-group-card';

type Phase = 'loading' | 'ready' | 'error';

interface GroupBucket {
  group: NonNullable<Agent['group']>;
  agents: Agent[];
}

/**
 * 설정 가능한 에이전트를 그룹별로 묶는다(등장 순서 유지). 그룹 없는(단독) 설정 에이전트는
 * 별도로 모은다. 그룹은 폴더 카드로 드릴인, 단독은 최상위에서 바로 설정 폼으로 편다.
 */
function bucketByGroup(agents: readonly Agent[]): { groups: GroupBucket[]; standalone: Agent[] } {
  const byId = new Map<string, GroupBucket>();
  const standalone: Agent[] = [];
  for (const agent of agents) {
    if (!agent.group) {
      standalone.push(agent);
      continue;
    }
    const bucket = byId.get(agent.group.id);
    if (bucket) bucket.agents.push(agent);
    else byId.set(agent.group.id, { group: agent.group, agents: [agent] });
  }
  return { groups: [...byId.values()], standalone };
}

/**
 * 에이전트 관리(관리자 전용) — `GET /agents`에서 settingsSchema 가 있는 에이전트만 대상으로,
 * **그룹 폴더 카드**로 묶어 한 단계 드릴인(/manage/agents/groups/[id])해 설정한다. 에이전트가
 * 늘어도(20개+) 최상위가 평평하게 깔리지 않는다(카탈로그 목록과 동일 IA).
 * 게이트는 UX 보조일 뿐이며 백엔드가 PATCH 에서 admin 을 최종 강제한다(미만 403).
 */
export function AgentSettingsClient() {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

  const [agents, setAgents] = useState<Agent[]>([]);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setPhase('loading');
    setError(null);
    try {
      setAgents(await api.get<Agent[]>('/agents'));
      setPhase('ready');
    } catch (err: unknown) {
      setError(toApiError(err));
      setPhase('error');
    }
  }, []);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  // 스키마가 있는(설정 가능한) 에이전트만 노출 대상이다.
  const configurable = agents.filter((agent) => (agent.settingsSchema?.length ?? 0) > 0);
  const { groups, standalone } = bucketByGroup(configurable);

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption="운영"
        title="에이전트 관리"
        description="에이전트별 세부설정을 관리합니다. 저장한 값은 다음 실행부터 적용됩니다."
      />

      {!isAdmin ? (
        <EmptyState
          icon={<RiLockLine size={18} aria-hidden />}
          title="접근 권한이 없습니다"
          description="에이전트 관리는 관리자 이상만 사용할 수 있습니다."
        />
      ) : phase === 'loading' ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} label="에이전트 불러오는 중" />
          에이전트를 불러오는 중…
        </div>
      ) : phase === 'error' ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="에이전트를 불러오지 못했습니다"
          description={errorMessage(error)}
          action={
            <Button variant="secondary" size="sm" onClick={() => void load()}>
              다시 시도
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-6">
          <Link
            href="/manage/agents/access"
            className="card-interactive border-border bg-surface group flex items-center gap-3 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)] transition-colors"
          >
            <span
              aria-hidden
              className="bg-accent/10 text-accent flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)]"
            >
              <RiShieldKeyholeLine size={18} />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="text-foreground text-[length:var(--text-body-lg)] font-semibold tracking-tight">
                에이전트 접근
              </h3>
              <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                에이전트별 실행 가능 조직(팀)을 설정합니다.
              </p>
            </div>
            <RiArrowRightSLine
              size={18}
              aria-hidden
              className="text-foreground-tertiary group-hover:text-accent shrink-0 transition-colors"
            />
          </Link>

          {configurable.length === 0 ? (
            <EmptyState
              icon={<RiSettings3Line size={18} aria-hidden />}
              title="설정 가능한 에이전트가 없습니다"
              description="세부설정 스키마를 가진 에이전트가 아직 없습니다."
            />
          ) : (
            <>
              {groups.length > 0 ? (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {groups.map((bucket) => (
                    <ManageGroupCard
                      key={bucket.group.id}
                      group={bucket.group}
                      agents={bucket.agents}
                    />
                  ))}
                </div>
              ) : null}
              {standalone.map((agent) => (
                <AgentSettingsCard
                  key={agent.id}
                  agent={agent}
                  onSaved={(updated) =>
                    setAgents((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
                  }
                />
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
