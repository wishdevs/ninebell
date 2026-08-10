import type { Metadata } from 'next';
import { ManualClient } from '../_components/manual-client';

export const metadata: Metadata = { title: '메뉴얼' };

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function ManualDocPage({ params }: PageProps) {
  const { id } = await params;
  return <ManualClient docId={id} />;
}
