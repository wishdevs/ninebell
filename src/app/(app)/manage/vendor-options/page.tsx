import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { VendorOptionsClient } from './_components/vendor-options-client';

export const metadata: Metadata = { title: '통합 지정 거래처' };

/**
 * 통합 지정 거래처 관리 — 구매발주 계획서의 분류별(가공품·판금품·주식회사 오텍) 거래처 후보
 * 목록. 발주 패턴(/manage/order-patterns)과 같은 저장소(purchase-order settings)를 쓰지만
 * 화면은 별도다(2026-08-26 사용자 요청 — 발주 패턴 레벨의 독립 페이지).
 */
export default function VendorOptionsPage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="관리"
        title="통합 지정 거래처"
        description="구매발주 계획서의 통합 지정과 발주단위 거래처 그룹에 뜨는 분류별 후보 목록을 관리합니다. 추가는 거래처 카탈로그 검색이 기본이고, 기본으로 표시한 거래처가 계획서 첫 진입값이 됩니다."
      />
      <VendorOptionsClient />
    </div>
  );
}
