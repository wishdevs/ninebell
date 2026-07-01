'use client';

import { RiErrorWarningLine } from '@remixicon/react';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { Button } from '@/components/ui/button';
import type { Agent } from '@/lib/data/agents';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { AgentCard } from './agent-card';

/**
 * 에이전트 카탈로그. 저장된 에이전트 정의를 `GET /agents`로 불러와 카드로 보여준다.
 * 에이전트는 워커로 상주하지 않으며(카드를 열 때 라이브 세션 시작, 화면을 벗어나면
 * 종료), 리스트에서는 실행 이력만 노출한다.
 */
export function AgentsClient() {
  const { status, data, error, reload } = useApiResource<Agent[]>('/agents');

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
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data?.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
}
