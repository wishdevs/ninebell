import type { Metadata } from 'next';
import { ManageAgentsGroupClient } from '../../_components/manage-agents-group-client';

export const metadata: Metadata = { title: '에이전트 관리' };

interface PageProps {
  params: Promise<{ groupId: string }>;
}

export default async function ManageAgentsGroupPage({ params }: PageProps) {
  const { groupId } = await params;
  return <ManageAgentsGroupClient groupId={groupId} />;
}
