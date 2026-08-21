'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { RiArrowLeftSLine, RiErrorWarningLine, RiSettings3Line } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { LockedEmptyState } from '@/components/ui/list-state';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { usePermissions } from '@/hooks/use-permissions';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { ApiError, api, errorMessage, toApiError } from '@/lib/api/client';
import type { Agent } from '@/lib/data/agents';
import { AgentSettingsCard, isConfigurable } from './agent-settings-card';

type Phase = 'loading' | 'ready' | 'error';

/**
 * 에이전트 1개 세부설정 — /manage/agents/[agentId]. 그룹 상세(/agents/groups/[id])의 설정 버튼이
 * 여는 화면이라 목록·그룹 필터 없이 `GET /agents/{id}` 1건만 읽는다. 관리자 전용(게이트는 UX
 * 보조일 뿐이며 백엔드가 PATCH 에서 admin 을 최종 강제한다).
 */
export function AgentSettingsDetailClient({ agentId }: { agentId: string }) {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

  const [agent, setAgent] = useState<Agent | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setPhase('loading');
    setError(null);
    try {
      setAgent(await api.get<Agent>(`/agents/${encodeURIComponent(agentId)}`));
      setPhase('ready');
    } catch (err: unknown) {
      setError(toApiError(err));
      setPhase('error');
    }
  }, [agentId]);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  // 돌아갈 자리 = 들어온 자리(그룹 상세). 그룹 없는 단독 에이전트는 집계 뷰로 보낸다.
  const back = agent?.group
    ? { href: `/agents/groups/${agent.group.id}`, label: agent.group.name }
    : { href: '/manage/agents', label: '에이전트 관리' };

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <div className="flex flex-col gap-3">
        <Link
          href={back.href}
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-[length:var(--text-body-sm)] font-medium transition-colors"
        >
          <RiArrowLeftSLine size={15} aria-hidden />
          {back.label}
        </Link>
        <PageHeader
          caption="운영"
          title={agent?.name ?? '에이전트 설정'}
          description="에이전트별 세부설정을 관리합니다. 저장한 값은 다음 실행부터 적용됩니다."
        />
      </div>

      {!isAdmin ? (
        <LockedEmptyState description="에이전트 관리는 관리자 이상만 사용할 수 있습니다." />
      ) : phase === 'loading' ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} label="에이전트 불러오는 중" />
          에이전트를 불러오는 중…
        </div>
      ) : phase === 'error' ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title={
            error?.status === 404 ? '에이전트를 찾을 수 없습니다' : '에이전트를 불러오지 못했습니다'
          }
          description={errorMessage(error)}
          action={
            error?.status === 404 ? (
              <Button asChild variant="secondary" size="sm">
                <Link href="/manage/agents">에이전트 관리로</Link>
              </Button>
            ) : (
              <Button variant="secondary" size="sm" onClick={() => void load()}>
                다시 시도
              </Button>
            )
          }
        />
      ) : agent && isConfigurable(agent) ? (
        <AgentSettingsCard agent={agent} onSaved={setAgent} />
      ) : (
        <EmptyState
          icon={<RiSettings3Line size={18} aria-hidden />}
          title="설정 항목이 없습니다"
          description="이 에이전트는 세부설정 스키마를 갖고 있지 않습니다."
          action={
            <Button asChild variant="secondary" size="sm">
              <Link href="/manage/agents">에이전트 관리로</Link>
            </Button>
          }
        />
      )}
    </div>
  );
}
