/**
 * 워크스페이스(조직) + 현재 사용자 더미데이터.
 *
 * 원본 AX는 멀티테넌트 SaaS라 조직 전환·역할·모듈 게이팅이 핵심이다.
 * 기본형에서는 인증/권한 로직을 모두 제거하고, 화면 구성을 보여주기 위한
 * 정적 픽스처만 남긴다.
 */

export type OrgRole = 'owner' | 'admin' | 'member' | 'client';

export const ROLE_LABEL: Record<OrgRole, string> = {
  owner: '소유자',
  admin: '관리자',
  member: '멤버',
  client: '클라이언트',
};

/** 워크스페이스가 켤 수 있는 제품 모듈. 사이드바 Workspace 그룹을 게이팅한다. */
export type ModuleKey = 'geo' | 'work' | 'ga' | 'monitoring' | 'playbook' | 'projects';

export interface Workspace {
  id: string;
  /** URL/식별용 슬러그. 기본형에선 라우팅에 쓰지 않지만 칩/메뉴에 노출. */
  slug: string;
  name: string;
  role: OrgRole;
  /** 사이드바 색상 바 + 아바타 그라데이션 톤. */
  color: string | null;
  memberCount: number;
  enabledModules: readonly ModuleKey[];
}

export interface CurrentUser {
  id: string;
  fullName: string;
  email: string;
  /** 아바타 이미지 대신 이니셜 폴백을 쓴다(백엔드 없음). */
  hasAvatar: false;
  /** 전역 슈퍼관리자 여부 — 사이드바 "시스템" 그룹 노출용. */
  isSystemAdmin: boolean;
}

export const CURRENT_USER: CurrentUser = {
  id: 'u-001',
  fullName: '김도현',
  email: 'dohyun.kim@etribe.co.kr',
  hasAvatar: false,
  isSystemAdmin: true,
};

export const WORKSPACES: readonly Workspace[] = [
  {
    id: 'org-hynro',
    slug: 'hynro',
    name: '하이로 커머스',
    role: 'owner',
    color: 'oklch(56% 0.21 258)',
    memberCount: 14,
    enabledModules: ['geo', 'work', 'ga', 'monitoring', 'playbook', 'projects'],
  },
  {
    id: 'org-mellow',
    slug: 'mellow',
    name: '멜로우 스튜디오',
    role: 'admin',
    color: 'oklch(64% 0.17 150)',
    memberCount: 8,
    enabledModules: ['work', 'ga', 'projects'],
  },
  {
    id: 'org-nimbus',
    slug: 'nimbus',
    name: '님버스 랩스',
    role: 'member',
    color: 'oklch(68% 0.16 40)',
    memberCount: 23,
    enabledModules: ['geo', 'monitoring'],
  },
];

/** 사이드바/스위처가 가리키는 현재 활성 워크스페이스. */
export const ACTIVE_WORKSPACE: Workspace = WORKSPACES[0];
