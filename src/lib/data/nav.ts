/**
 * 사이드바 네비게이션 구조.
 *
 * 각 항목은 권한/롤 게이트를 가질 수 있고, 사이드바가 `usePermissions()`로
 * 게이트를 평가해 접근 가능한 항목만 노출한다(기본 비접근·숨김). 아이콘은
 * 컴포넌트 단에서 매핑한다.
 */

import type { PermissionCode, Role } from '@/lib/auth/permissions';

export type NavIconKey =
  | 'home'
  | 'agents'
  | 'assistant'
  | 'works'
  | 'analytics'
  | 'projects'
  | 'members'
  | 'settings'
  | 'design'
  | 'audit'
  | 'logging'
  | 'org'
  | 'budget'
  | 'learning';

export interface NavItem {
  href: string;
  label: string;
  icon: NavIconKey;
  /** true면 정확히 일치할 때만 활성(하위 경로로 번지지 않음). */
  exact?: boolean;
  /** 이 권한을 가진 사용자에게만 노출. */
  permission?: PermissionCode;
  /** 이 롤 이상(계층)에게만 노출. `permission`과 함께 쓰지 않는다. */
  minRole?: Role;
  /** true면 개발 환경(NODE_ENV!=='production')에서만 노출 — 제작용 디버그 메뉴. */
  devOnly?: boolean;
}

export interface NavGroup {
  /** null이면 라벨 없는 그룹(홈 진입점). */
  label: string | null;
  items: readonly NavItem[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    label: null,
    items: [{ href: '/', label: '홈', icon: 'home', exact: true }],
  },
  {
    label: 'Workspace',
    items: [
      { href: '/agents', label: '에이전트', icon: 'agents', permission: 'agents:read' },
      // 로그인한 모든 사용자에게 노출(게이트 없음 — /agents·/runs 읽기는 모든 롤의 암묵 권한).
      { href: '/assistant', label: 'AI 어시스턴트', icon: 'assistant' },
    ],
  },
  // 예산단위·프로젝트 관리는 '결의서 작성' 그룹의 공유 기준정보라, 사이드바 최상위가 아니라
  // 에이전트 목록의 그룹 섹션에서 연다(agents-client.tsx GROUP_TOOLS). URL(/manage/*)은 유지.
  {
    label: '운영',
    items: [
      { href: '/members', label: '멤버', icon: 'members', permission: 'users:read' },
      // 에이전트별 세부설정(스키마 기반 폼) 관리(관리자+). 에이전트별 접근(사용 가능 조직) 설정은
      // 이 아래 /manage/agents/access 서브라우트로 옮겨졌다(사이드바에는 별도 항목 없음).
      { href: '/manage/agents', label: '에이전트 관리', icon: 'agents', minRole: 'admin' },
      // 조직구분(ERP 조직도 미러링) 관리 — 팀별 비용구분 설정(관리자+).
      { href: '/organizations', label: '조직구분 관리', icon: 'org', minRole: 'admin' },
      // 감사 = 사용자 접속/행동 감시(로그인 access_logs). 로깅 = 에이전트 사용 내역(runs).
      { href: '/audit', label: '감사', icon: 'audit', permission: 'logs:read' },
      { href: '/logs', label: '로깅', icon: 'logging', permission: 'logs:read' },
    ],
  },
  {
    label: '개발',
    items: [
      { href: '/design-system', label: '디자인 시스템', icon: 'design', minRole: 'admin' },
      // 개입 학습(가맹점→선택)·전사 기초자료 열람 — dev·운영 모두 노출(전 로그인 사용자).
      { href: '/dev/card-learning', label: '개입 학습(디버그)', icon: 'learning' },
      // 공용 스킬 카탈로그 + 사용 에이전트 역인덱스 — 개발 환경에서만 노출.
      { href: '/skills', label: '스킬', icon: 'works', devOnly: true },
    ],
  },
];
