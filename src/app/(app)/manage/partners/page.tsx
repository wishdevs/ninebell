import { Suspense } from 'react';
import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { CodeCatalogManager } from '../_components/code-catalog-manager';

export const metadata: Metadata = { title: '거래처 관리' };

/**
 * 거래처 관리 — 자주쓰는 거래처 지정·기본지정 + ERP 카탈로그 동기화/검색.
 * 개인 즐겨찾기라 로그인한 모든 사용자가 사용한다(별도 권한 없음).
 * Suspense 경계는 CodeCatalogManager 의 useListParams(useSearchParams) 요구 —
 * 클라이언트가 즉시 자체 로딩을 그리므로 fallback 은 null.
 */
export default function PartnersManagePage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="관리"
        title="거래처 관리"
        description="자주쓰는 거래처와 기본값을 지정합니다. 에이전트가 통행료 등 결의서 입력에 활용합니다."
      />
      <Suspense fallback={null}>
        <CodeCatalogManager kind="partner" caption="코드" title="거래처 카탈로그" description="" />
      </Suspense>
    </div>
  );
}
