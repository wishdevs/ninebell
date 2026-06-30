/**
 * 사이드바 네비게이션 구조.
 *
 * 원본 AX는 권한/모듈 게이팅으로 항목을 동적으로 숨기지만, 기본형에서는
 * 정적 그룹 구조만 보여준다. 아이콘은 컴포넌트 단에서 매핑한다.
 */

export type NavIconKey =
  'home' | 'agents' | 'works' | 'analytics' | 'projects' | 'members' | 'settings' | 'design';

export interface NavItem {
  href: string;
  label: string;
  icon: NavIconKey;
  /** true면 정확히 일치할 때만 활성(하위 경로로 번지지 않음). */
  exact?: boolean;
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
      { href: '/agents', label: '에이전트', icon: 'agents' },
      { href: '/works', label: '업무', icon: 'works' },
      { href: '/analytics', label: '애널리틱스', icon: 'analytics' },
      { href: '/projects', label: '프로젝트', icon: 'projects' },
    ],
  },
  {
    label: '운영',
    items: [
      { href: '/members', label: '멤버', icon: 'members' },
      { href: '/settings', label: '조직 설정', icon: 'settings', exact: true },
    ],
  },
  {
    label: '개발',
    items: [{ href: '/design-system', label: '디자인 시스템', icon: 'design' }],
  },
];
