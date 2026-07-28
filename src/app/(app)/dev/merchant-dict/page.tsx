import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { MerchantDictClient } from './_components/merchant-dict-client';

export const metadata: Metadata = { title: '가맹점 사전' };

/**
 * 가맹점 분류 사전 — 미등록 가맹점을 카드 표기명 키워드로 인식해 업종/계정 힌트를 주는 규칙 사전.
 * 조회는 전 로그인 사용자, 추가/수정/삭제는 관리자만(버튼 게이트 + 백엔드 최종 강제).
 * 라우트 자체는 세션만 요구한다(개입 학습과 동일하게 nav 무게이트 노출).
 */
export default function MerchantDictDevPage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="개발 · 디버그"
        title="가맹점 사전"
        description="미등록 가맹점을 카드 표기명 키워드로 인식해 계정/힌트를 제공하는 사전입니다. 우선순위 오름차순, 첫 매칭 채택."
      />
      <MerchantDictClient />
    </div>
  );
}
