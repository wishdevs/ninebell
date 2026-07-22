import { Suspense } from 'react';
import type { Metadata } from 'next';
import { AuditClient } from './_components/audit-client';

export const metadata: Metadata = {
  title: '감사',
};

/**
 * 감사(Audit) 화면 — 사용자 접속/행동 감시. 로그인 성공/실패 이벤트(언제·누가·어디서)를
 * 보여준다(옴니솔 access_logs, `GET /logs`).
 *
 * 서버 컴포넌트는 metadata만 소유하고, 권한 게이팅과 데이터 로드는 클라이언트 자식이
 * 담당한다(세션 쿠키 기반 fetch). logs:read(admin+) 전용이며 `user` 롤은 접근 불가.
 * Suspense 경계는 useListParams(useSearchParams) 요구 — 클라이언트가 즉시 자체 로딩을
 * 그리므로 fallback 은 null.
 */
export default function AuditPage() {
  return (
    <Suspense fallback={null}>
      <AuditClient />
    </Suspense>
  );
}
