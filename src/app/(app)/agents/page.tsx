import type { Metadata } from 'next';
import { AgentsClient } from './_components/agents-client';

export const metadata: Metadata = { title: '에이전트' };

export default function AgentsPage() {
  return <AgentsClient />;
}
