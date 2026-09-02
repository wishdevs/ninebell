import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { ErpSyncClient } from './_components/erp-sync-client';

export const metadata: Metadata = { title: 'ERP 동기화' };

/**
 * ERP 동기화 통합 관리 — 예산단위·프로젝트·거래처·ERP 조직 4종의 마지막 동기화와 최근 결과를
 * 한 화면에서 보고 즉시 동기화한다. 매일 자정(Asia/Seoul) 자동 동기화 상태도 여기서 확인한다.
 * 관리자 전용이다(게이트는 클라이언트가 걸고 백엔드가 최종 강제한다).
 */
export default function ErpSyncPage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] min-w-0 flex-col gap-6">
      <PageHeader
        caption="관리"
        title="ERP 동기화"
        description="예산단위·프로젝트·거래처·ERP 조직의 기준정보를 옴니솔에서 가져옵니다. 항목별로 정한 주기마다 자동으로 최신화되며, 필요하면 여기서 즉시 동기화할 수 있습니다."
      />
      <ErpSyncClient />
    </div>
  );
}
