import type { Metadata } from 'next';
import { AgentDetailLoader } from './_components/agent-detail-loader';

interface PageProps {
  params: Promise<{ id: string }>;
}

// 라이브 데이터는 클라이언트(쿠키 기반)에서 로드하므로 서버 메타데이터는 일반 제목만
// 내린다(에이전트명 시드 픽스처 제거 — 실명은 화면 헤더가 API 데이터로 표시).
export const metadata: Metadata = { title: '에이전트' };

export default async function AgentDetailPage({ params }: PageProps) {
  const { id } = await params;
  return <AgentDetailLoader id={id} />;
}
