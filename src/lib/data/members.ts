/**
 * 멤버(전역 사용자) 타입·라벨 — `GET /users` 응답 계약과 1:1.
 *
 * 글로벌 단일 테넌트라 멤버 = 전역 사용자 리스트다. 롤은 백엔드 `Role`
 * (super_admin|admin|user)을 그대로 쓰고, 한국어 표기만 여기서 소유한다.
 * (시드 픽스처는 백엔드 `GET /users`로 대체되어 더 이상 두지 않는다.)
 */

import type { Role } from '@/lib/auth/permissions';

export type MemberStatus = 'active' | 'invited' | 'suspended';

export const MEMBER_STATUS_LABEL: Record<MemberStatus, string> = {
  active: '활성',
  invited: '초대됨',
  suspended: '정지',
};

/** 롤 한국어 라벨 — 멤버 테이블의 역할 셀렉트/배지 표기에 사용. */
export const MEMBER_ROLE_LABEL: Record<Role, string> = {
  super_admin: '최고관리자',
  admin: '관리자',
  user: '사용자',
};

export interface WorkspaceMember {
  id: string;
  name: string;
  email: string;
  role: Role;
  status: MemberStatus;
  /** 이메일 인증 여부 — StatusPill 표시용. */
  emailVerified: boolean;
  lastActiveAt: string;
  joinedAt: string;
  /** 소속 조직구분 id(에이전트 실행 조직접근 게이트 기준). 미지정이면 null. */
  orgUnitId: string | null;
}
