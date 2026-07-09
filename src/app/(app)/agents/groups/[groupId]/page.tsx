import { GroupDetailClient } from '../../_components/group-detail-client';

interface PageProps {
  params: Promise<{ groupId: string }>;
}

export default async function AgentGroupPage({ params }: PageProps) {
  const { groupId } = await params;
  return <GroupDetailClient groupId={groupId} />;
}
