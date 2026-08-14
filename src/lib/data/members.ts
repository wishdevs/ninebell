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

/** 셀렉트/필터용 전체 역할 옵션. */
export const MEMBER_ROLE_OPTIONS: readonly Role[] = ['super_admin', 'admin', 'user'];

/** 셀렉트/필터용 전체 상태 옵션. */
export const MEMBER_STATUS_OPTIONS: readonly MemberStatus[] = ['active', 'invited', 'suspended'];

/** 역할 읽기 전용 배지 톤(StatusPill variant='custom'). */
export const MEMBER_ROLE_BADGE: Record<Role, string> = {
  super_admin: 'bg-accent/10 text-accent',
  admin: 'bg-warning/10 text-warning',
  user: 'bg-muted text-muted-foreground',
};

/** 상태 → StatusPill 톤 매핑. */
export const MEMBER_STATUS_VARIANT: Record<MemberStatus, 'success' | 'info' | 'danger'> = {
  active: 'success',
  invited: 'info',
  suspended: 'danger',
};

/** 조직구분 셀렉트/필터의 '미지정' 센티넬(Select 값은 문자열이라야 하므로 null 대체). */
export const ORG_NONE = '__none__';

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
  /** 옴니솔 로그인 식별자 — 상세 드로워 표시용(구버전 응답엔 없을 수 있어 optional). */
  omnisolUserid?: string;
  /** 부서(ERP 문자열, 조직구분과 별개). 없으면 null/undefined. */
  department?: string | null;
  /** 마지막 수정 시각 — 상세 드로워 표시용. */
  updatedAt?: string;
}
