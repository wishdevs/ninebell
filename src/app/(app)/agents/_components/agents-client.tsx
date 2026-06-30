import { PageHeader } from '@/components/ui/page-header';
import { AGENTS } from '@/lib/data/agents';
import { AgentCard } from './agent-card';

/**
 * 에이전트 카탈로그. 에이전트는 모두 사전에 만들어진 것만 보여지며, 워커로 상주하지
 * 않는다(카드를 열 때 라이브 세션 시작, 화면을 벗어나면 종료). 새 에이전트 생성·상주
 * 상태 같은 요소는 두지 않는다.
 */
export function AgentsClient() {
  return (
    <div className="flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="자동화"
        title="에이전트"
        description="실행할 업무를 고르기만 하면 됩니다. 에이전트가 더존 화면을 대신 조작하고, 진행 과정을 실시간으로 보여주며 증빙·프로젝트 같은 중요한 선택은 직접 승인하면 됩니다."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {AGENTS.map((agent) => (
          <AgentCard key={agent.id} agent={agent} />
        ))}
      </div>
    </div>
  );
}
