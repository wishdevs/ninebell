'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { RiArrowLeftSLine, RiErrorWarningLine, RiSettings3Line } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { LockedEmptyState } from '@/components/ui/list-state';
import { MetaChip } from '@/components/ui/meta-chip';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { usePermissions } from '@/hooks/use-permissions';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { ApiError, api, errorMessage, toApiError } from '@/lib/api/client';
import type { Agent } from '@/lib/data/agents';
import { AgentSettingsCard } from './agent-settings-card';

type Phase = 'loading' | 'ready' | 'error';

/**
 * 에이전트 관리 그룹 드릴인 — /manage/agents/groups/[groupId]. `GET /agents`에서 이 그룹의
 * **설정 가능한**(settingsSchema 보유) 에이전트만 걸러 설정 폼으로 나열한다. 관리자 전용.
 */
export function ManageAgentsGroupClient({ groupId }: { groupId: string }) {
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

  const inGroup = agents.filter(
    (a) => a.group?.id === groupId && (a.settingsSchema?.length ?? 0) > 0,
  );
  const group = inGroup[0]?.group ?? null;

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <div className="flex flex-col gap-3">
        <Link
          href="/manage/agents"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-[length:var(--text-body-sm)] font-medium transition-colors"
        >
          <RiArrowLeftSLine size={15} aria-hidden />
          에이전트 관리
        </Link>
        <PageHeader
          caption="운영"
          title={
            <span className="inline-flex items-center gap-2">
              {group?.name ?? '에이전트 관리'}
              {group ? <MetaChip className="tabular-nums">{inGroup.length}</MetaChip> : null}
            </span>
          }
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
          title="에이전트를 불러오지 못했습니다"
          description={errorMessage(error)}
          action={
            <Button variant="secondary" size="sm" onClick={() => void load()}>
              다시 시도
            </Button>
          }
        />
      ) : inGroup.length === 0 ? (
        <EmptyState
          icon={<RiSettings3Line size={18} aria-hidden />}
          title="설정 가능한 에이전트가 없습니다"
          description="이 그룹에 세부설정을 가진 에이전트가 없습니다."
          action={
            <Button asChild variant="secondary" size="sm">
              <Link href="/manage/agents">에이전트 관리로</Link>
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-6">
          {inGroup.map((agent) => (
            <AgentSettingsCard
              key={agent.id}
              agent={agent}
              onSaved={(updated) =>
                setAgents((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
