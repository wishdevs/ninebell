import type { Metadata } from 'next';
import { ManualClient } from './_components/manual-client';

// robots noindex — 향후 운영 공개에 대비한 기본값(검색 색인은 원치 않음).
export const metadata: Metadata = { title: '메뉴얼', robots: { index: false, follow: false } };

export default function ManualPage() {
  return <ManualClient />;
}
