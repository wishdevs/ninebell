/**
 * 멤버 관리 픽스처 — 관리 테이블 + CRUD 다이얼로그 아키타입을 구동한다.
 */

import type { OrgRole } from './workspace';
import { relativeFromNow } from './format';

export type MemberStatus = 'active' | 'invited' | 'suspended';

export const MEMBER_STATUS_LABEL: Record<MemberStatus, string> = {
  active: '활성',
  invited: '초대됨',
  suspended: '정지',
};

export interface WorkspaceMember {
  id: string;
  name: string;
  email: string;
  role: OrgRole;
  status: MemberStatus;
  /** 이메일 인증 여부 — StatusPill 데모용. */
  emailVerified: boolean;
  lastActiveAt: string;
  joinedAt: string;
}

export const WORKSPACE_MEMBERS: readonly WorkspaceMember[] = [
  {
    id: 'u-001',
    name: '김도현',
    email: 'dohyun.kim@etribe.co.kr',
    role: 'owner',
    status: 'active',
    emailVerified: true,
    lastActiveAt: relativeFromNow({ minutes: 12 }),
    joinedAt: relativeFromNow({ days: 320 }),
  },
  {
    id: 'u-002',
    name: '이서연',
    email: 'seoyeon.lee@etribe.co.kr',
    role: 'admin',
    status: 'active',
    emailVerified: true,
    lastActiveAt: relativeFromNow({ hours: 2 }),
    joinedAt: relativeFromNow({ days: 210 }),
  },
  {
    id: 'u-003',
    name: '박준호',
    email: 'junho.park@etribe.co.kr',
    role: 'member',
    status: 'active',
    emailVerified: true,
    lastActiveAt: relativeFromNow({ hours: 5 }),
    joinedAt: relativeFromNow({ days: 168 }),
  },
  {
    id: 'u-004',
    name: '최하늘',
    email: 'haneul.choi@etribe.co.kr',
    role: 'member',
    status: 'active',
    emailVerified: false,
    lastActiveAt: relativeFromNow({ days: 1 }),
    joinedAt: relativeFromNow({ days: 92 }),
  },
  {
    id: 'u-005',
    name: '정유진',
    email: 'yujin.jung@etribe.co.kr',
    role: 'member',
    status: 'invited',
    emailVerified: false,
    lastActiveAt: relativeFromNow({ days: 30 }),
    joinedAt: relativeFromNow({ days: 4 }),
  },
  {
    id: 'u-006',
    name: '한지민',
    email: 'jimin.han@etribe.co.kr',
    role: 'client',
    status: 'active',
    emailVerified: true,
    lastActiveAt: relativeFromNow({ days: 3 }),
    joinedAt: relativeFromNow({ days: 47 }),
  },
  {
    id: 'u-007',
    name: '오세훈',
    email: 'sehun.oh@etribe.co.kr',
    role: 'member',
    status: 'suspended',
    emailVerified: true,
    lastActiveAt: relativeFromNow({ days: 58 }),
    joinedAt: relativeFromNow({ days: 140 }),
  },
];
