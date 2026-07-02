import type { Metadata } from 'next';
import { CodeCatalogManager } from '../_components/code-catalog-manager';

export const metadata: Metadata = { title: '예산단위 관리' };

/**
 * 예산단위 관리 — 자주쓰는 예산단위(조합 행) 지정·기본지정 + ERP 카탈로그 동기화/검색.
 * 개인 즐겨찾기라 로그인한 모든 사용자가 사용한다(별도 권한 없음).
 */
export default function BudgetUnitsPage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <CodeCatalogManager
        kind="budget_unit"
        caption="관리"
        title="예산단위 관리"
        description="자주쓰는 예산단위를 관리하고, ERP에서 예산단위 목록을 동기화합니다. 기본은 내 부서 기준입니다."
        supportsDept
      />
    </div>
  );
}
