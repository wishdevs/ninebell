import type { Metadata } from 'next';
import { AccountClient } from './_components/account-client';

export const metadata: Metadata = {
  title: '계정 설정',
};

/**
 * 계정 설정 — 로그인한 본인의 개인 정보(이름·부서·이메일) 수정.
 *
 * `/settings`(조직 설정)와는 별개다. 서버 컴포넌트는 metadata만 소유하고,
 * 폼 상태·저장은 클라이언트 자식으로 위임한다.
 */
export default function AccountPage() {
  return <AccountClient />;
}
