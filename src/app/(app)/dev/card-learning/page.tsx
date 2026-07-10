import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { CardLearningTable } from './_components/card-learning-table';
import { CardSeedTable } from './_components/card-seed-table';

export const metadata: Metadata = { title: '개입 학습(디버그)' };

/**
 * 개입 학습 디버그 — AI 추천 근거가 되는 두 tier 를 탭으로 나눠 열람한다.
 * - 공통: 전사 기초자료(seed, 가맹점→계정·적요) — 공용, 개인 학습 없을 때 폴백.
 * - 개인: 사용자가 그리드 개입에서 확정한 선택(예산단위/프로젝트/적요·빈도).
 * 운영 노출(관리자+ nav 게이트). 라우트 자체는 세션만 요구한다.
 */
export default function CardLearningDevPage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="개발 · 디버그"
        title="개입 학습"
        description="AI 추천의 근거 데이터를 확인합니다. 우선순위: 개인(확정 ≥3회는 결정적) > AI > 공통(전사) > 기본."
      />
      <Tabs defaultValue="seed">
        <TabsList>
          <TabsTrigger value="seed">공통 (전사)</TabsTrigger>
          <TabsTrigger value="personal">개인</TabsTrigger>
        </TabsList>
        <TabsContent value="seed" className="pt-4">
          <CardSeedTable />
        </TabsContent>
        <TabsContent value="personal" className="pt-4">
          <CardLearningTable />
        </TabsContent>
      </Tabs>
    </div>
  );
}
