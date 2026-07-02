import type { Metadata } from 'next';
import { OrgAccessClient } from './_components/org-access-client';

export const metadata: Metadata = {
  title: '조직구분 관리',
};

/**
 * 조직구분 관리 — 조직구분별 에이전트 사용 권한.
 *
 * 서버 컴포넌트는 metadata만 소유하고, 상호작용(조직구분 선택/해제 로컬 state)은 클라이언트
 * 자식으로 분리한다. 데이터는 백엔드 `GET /org-units`·`GET /agent-access`로 로드하고
 * 변경을 PATCH 한다(members 화면과 동일 아키타입).
 */
export default function OrganizationsPage() {
  return <OrgAccessClient />;
}
