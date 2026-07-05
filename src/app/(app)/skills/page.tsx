import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { PageHeader } from '@/components/ui/page-header';
import { SkillsTable } from './_components/skills-table';

export const metadata: Metadata = { title: '스킬' };

/**
 * 스킬 카탈로그(개발) — 에이전트 스텝이 사용하는 공용 스킬의 단일 소스
 * (backend app/services/skills.py)를 사용 에이전트 역인덱스와 함께 열람한다.
 * 제작용이며 **개발 환경에서만** 접근 가능(프로덕션 빌드에서는 404).
 */
export default function SkillsDevPage() {
  if (process.env.NODE_ENV === 'production') notFound();
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="개발 · 카탈로그"
        title="스킬"
        description="에이전트 단계가 사용하는 공용 스킬 카탈로그입니다. 각 스킬을 어떤 에이전트가 쓰는지 역인덱스로 확인합니다."
      />
      <SkillsTable />
    </div>
  );
}
