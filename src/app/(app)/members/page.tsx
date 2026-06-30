import type { Metadata } from 'next';
import { MembersClient } from './_components/members-client';

export const metadata: Metadata = {
  title: '멤버',
};

/**
 * 멤버 관리 — 관리 테이블 + 다이얼로그 CRUD 아키타입.
 *
 * 서버 컴포넌트는 metadata만 소유하고, 모든 상호작용(로컬 state, 다이얼로그,
 * 낙관적 업데이트)은 클라이언트 자식으로 분리한다. 백엔드가 없으므로 데이터는
 * `@/lib/data/members`의 동기 픽스처를 클라이언트에서 복사해 다룬다.
 */
export default function MembersPage() {
  return <MembersClient />;
}
