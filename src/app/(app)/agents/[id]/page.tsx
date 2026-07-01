import type { Metadata } from 'next';
import { findAgent } from '@/lib/data/agents';
import { AgentDetailLoader } from './_components/agent-detail-loader';

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * 라이브 데이터는 클라이언트(쿠키 기반)에서 로드하므로, 메타데이터 제목은
 * 시드 정의(백엔드와 동일 id)에서 베스트에포트로 채운다. 미스 시 일반 제목.
 */
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const agent = findAgent(id);
  return { title: agent ? agent.name : '에이전트' };
}

export default async function AgentDetailPage({ params }: PageProps) {
  const { id } = await params;
  return <AgentDetailLoader id={id} />;
}
