import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { CodeCatalogManager } from '../_components/code-catalog-manager';

export const metadata: Metadata = { title: '예산단위 관리' };

/**
 * 예산단위 관리 — 자주쓰는 예산단위(조합 행) 지정·기본지정 + ERP 카탈로그 동기화/검색.
 * 개인 즐겨찾기라 로그인한 모든 사용자가 사용한다(별도 권한 없음).
 */
export default function BudgetUnitsPage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="관리"
        title="예산단위 관리"
        description="자주쓰는 예산단위를 지정하고 기본값을 정해 두면, 결의서 입력 에이전트가 카드내역에 자동으로 채워 줍니다. 목록은 ERP에서 동기화합니다."
      />
      <CodeCatalogManager
        kind="budget_unit"
        caption="코드"
        title="예산단위 카탈로그"
        description="기본은 내 부서 기준으로 보여줍니다. 예산계정명·사업계획명으로 검색할 수 있습니다."
        supportsDept
      />
    </div>
  );
}
