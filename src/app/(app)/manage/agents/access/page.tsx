import type { Metadata } from 'next';
import { AgentAccessClient } from '../_components/agent-access-client';

export const metadata: Metadata = {
  title: '에이전트 접근',
};

/**
 * 에이전트 접근 — /manage/agents/access. 조직구분 관리 화면의 탭이었던 에이전트별 접근 설정을
 * 에이전트 관리 화면군으로 옮긴 서브라우트. 서버 컴포넌트는 metadata만 소유하고, 상호작용은
 * 클라이언트 자식(AgentAccessClient)으로 분리한다.
 */
export default function AgentAccessPage() {
  return <AgentAccessClient />;
}
