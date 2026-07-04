import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { PageHeader } from '@/components/ui/page-header';
import { CardLearningTable } from './_components/card-learning-table';

export const metadata: Metadata = { title: '개입 학습(디버그)' };

/**
 * 개입 학습 디버그 — 가맹점→사용자 확정 선택(예산단위/프로젝트/적요·빈도)을 열람한다.
 * 제작용이며 **개발 환경에서만** 접근 가능(프로덕션 빌드에서는 404). 실제 사용자는 볼 필요 없음.
 */
export default function CardLearningDevPage() {
  if (process.env.NODE_ENV === 'production') notFound();
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="개발 · 디버그"
        title="개입 학습"
        description="AI 추천의 근거가 되는 '가맹점 → 과거 확정 선택'을 확인합니다. 빈도 3회 이상이면 AI 없이 그 선택으로 결정적 프리필됩니다."
      />
      <CardLearningTable />
    </div>
  );
}
