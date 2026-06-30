import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { findAgent } from '@/lib/data/agents';
import { AgentDetailClient } from './_components/agent-detail-client';

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const agent = findAgent(id);
  return { title: agent ? agent.name : '에이전트' };
}

export default async function AgentDetailPage({ params }: PageProps) {
  const { id } = await params;
  const agent = findAgent(id);
  if (!agent) notFound();
  return <AgentDetailClient agent={agent} />;
}
