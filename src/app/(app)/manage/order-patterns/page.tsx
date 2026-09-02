import type { Metadata } from 'next';
import { ManualLink } from '@/components/ui/manual-link';
import { PageHeader } from '@/components/ui/page-header';
import { PJT_PLACEHOLDER } from '@/lib/purchase/order-patterns';
import { OrderPatternsClient } from './_components/order-patterns-client';

export const metadata: Metadata = { title: '발주 패턴' };

/**
 * 발주 패턴 관리 — 구매발주 계획서가 발주단위를 자동 편성할 때 쓰는 기준표(발주그룹 1개 = 발주 1건).
 * 저장 위치는 purchase-order 에이전트의 settings 라 관리자 전용이다(게이트는 클라이언트가 건다).
 */
export default function OrderPatternsPage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="관리"
        title="발주 패턴"
        titleAdornment={<ManualLink docId="order-patterns" />}
        description={`구매발주 계획서가 이 패턴대로 발주단위를 자동 편성합니다 — 발주그룹 1개가 발주 1건입니다. 구매사유의 '${PJT_PLACEHOLDER}' 는 계획서에서 선택한 프로젝트로 치환되고, 규격에 EFEM-/Process- 접두가 없으면 장비명으로 묶음을 판별해 매칭합니다.`}
      />
      <OrderPatternsClient />
    </div>
  );
}
