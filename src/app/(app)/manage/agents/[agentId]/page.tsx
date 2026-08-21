import type { Metadata } from 'next';
import { AgentSettingsDetailClient } from '../_components/agent-settings-detail-client';

export const metadata: Metadata = { title: '에이전트 설정' };

interface PageProps {
  params: Promise<{ agentId: string }>;
}

/**
 * 에이전트 1개 세부설정 — 그룹 상세의 설정 버튼 진입점. 형제 정적 세그먼트(`access`·`groups`)가
 * 우선하므로 그 두 주소는 여기로 오지 않는다.
 */
export default async function AgentSettingsPage({ params }: PageProps) {
  const { agentId } = await params;
  return <AgentSettingsDetailClient agentId={agentId} />;
}
