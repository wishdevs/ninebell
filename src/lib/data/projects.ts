/**
 * 프로젝트 픽스처 — 카드 그리드 + 상세(탭) 아키타입을 구동한다.
 */

import { relativeFromNow } from './format';

export type ProjectStatus = 'active' | 'paused' | 'archived';

export const PROJECT_STATUS_LABEL: Record<ProjectStatus, string> = {
  active: '진행 중',
  paused: '보류',
  archived: '보관',
};

export interface ProjectMemberRef {
  id: string;
  name: string;
}

export interface Project {
  id: string;
  slug: string;
  name: string;
  description: string;
  status: ProjectStatus;
  /** 강조 색상 — 카드 상단 바/아바타 톤. */
  color: string;
  /** 0..100 진행률. */
  progress: number;
  workCount: number;
  openWorkCount: number;
  members: readonly ProjectMemberRef[];
  /** 활성 모듈 태그. */
  modules: readonly string[];
  updatedAt: string;
  createdAt: string;
}

export const PROJECTS: readonly Project[] = [
  {
    id: 'pj-commerce',
    slug: 'commerce-renewal',
    name: '커머스 리뉴얼',
    description: '메인 커머스 플랫폼 전면 리뉴얼 — 체크아웃 퍼널 최적화와 상품 상세 개편.',
    status: 'active',
    color: 'oklch(56% 0.21 258)',
    progress: 62,
    workCount: 24,
    openWorkCount: 9,
    members: [
      { id: 'u-001', name: '김도현' },
      { id: 'u-003', name: '박준호' },
      { id: 'u-004', name: '최하늘' },
    ],
    modules: ['업무', 'GA', '모니터링'],
    updatedAt: relativeFromNow({ hours: 5 }),
    createdAt: relativeFromNow({ days: 96 }),
  },
  {
    id: 'pj-genai',
    slug: 'genai-search',
    name: '생성형 검색 대응',
    description: '생성형 검색(GEO)에서 브랜드 노출을 추적하고 인용 위치를 끌어올리는 프로젝트.',
    status: 'active',
    color: 'oklch(64% 0.16 150)',
    progress: 38,
    workCount: 16,
    openWorkCount: 11,
    members: [
      { id: 'u-002', name: '이서연' },
      { id: 'u-005', name: '정유진' },
    ],
    modules: ['GEO', '업무', '플레이북'],
    updatedAt: relativeFromNow({ hours: 3 }),
    createdAt: relativeFromNow({ days: 41 }),
  },
  {
    id: 'pj-brand',
    slug: 'brand-site',
    name: '브랜드 사이트',
    description: '브랜드 마이크로사이트 구축 — 스크롤리텔링 히어로와 접근성 강화.',
    status: 'active',
    color: 'oklch(68% 0.16 40)',
    progress: 78,
    workCount: 19,
    openWorkCount: 4,
    members: [
      { id: 'u-001', name: '김도현' },
      { id: 'u-004', name: '최하늘' },
      { id: 'u-005', name: '정유진' },
    ],
    modules: ['업무', '모니터링'],
    updatedAt: relativeFromNow({ hours: 9 }),
    createdAt: relativeFromNow({ days: 58 }),
  },
  {
    id: 'pj-loyalty',
    slug: 'loyalty-program',
    name: '멤버십 리워드',
    description: '신규 멤버십 등급제와 리워드 적립 흐름 설계. 분석 셋업 대기 중.',
    status: 'paused',
    color: 'oklch(66% 0.16 320)',
    progress: 18,
    workCount: 8,
    openWorkCount: 6,
    members: [{ id: 'u-002', name: '이서연' }],
    modules: ['업무'],
    updatedAt: relativeFromNow({ days: 6 }),
    createdAt: relativeFromNow({ days: 22 }),
  },
  {
    id: 'pj-archive',
    slug: '2025-q4-campaign',
    name: '2025 Q4 캠페인',
    description: '연말 프로모션 캠페인 — 종료 후 보관됨.',
    status: 'archived',
    color: 'oklch(60% 0.04 250)',
    progress: 100,
    workCount: 31,
    openWorkCount: 0,
    members: [
      { id: 'u-003', name: '박준호' },
      { id: 'u-004', name: '최하늘' },
    ],
    modules: ['업무', 'GA'],
    updatedAt: relativeFromNow({ days: 120 }),
    createdAt: relativeFromNow({ days: 210 }),
  },
];

// ── 상세(탭)용 추가 데이터 ───────────────────────────────────────────

export interface ActivityItem {
  id: string;
  actor: string;
  action: string;
  target: string;
  at: string;
}

export const PROJECT_ACTIVITY: readonly ActivityItem[] = [
  {
    id: 'ac-1',
    actor: '이서연',
    action: '업무를 완료로 이동',
    target: '블로그 SEO 메타 일괄 점검',
    at: relativeFromNow({ hours: 3 }),
  },
  {
    id: 'ac-2',
    actor: '박준호',
    action: '댓글 추가',
    target: '체크아웃 퍼널 이탈 분석',
    at: relativeFromNow({ hours: 7 }),
  },
  {
    id: 'ac-3',
    actor: '김도현',
    action: '단계를 개발로 변경',
    target: '브랜드 사이트 히어로 섹션 모션',
    at: relativeFromNow({ hours: 12 }),
  },
  {
    id: 'ac-4',
    actor: '최하늘',
    action: '업무 생성',
    target: '주간 운영 리포트 템플릿',
    at: relativeFromNow({ days: 1 }),
  },
  {
    id: 'ac-5',
    actor: '정유진',
    action: '담당자 지정',
    target: 'SSL 인증서 갱신 자동화',
    at: relativeFromNow({ days: 2 }),
  },
];

export interface FileItem {
  id: string;
  name: string;
  kind: string;
  size: string;
  uploadedBy: string;
  at: string;
}

export const PROJECT_FILES: readonly FileItem[] = [
  {
    id: 'fl-1',
    name: '리뉴얼_IA_v3.fig',
    kind: 'Figma',
    size: '4.2MB',
    uploadedBy: '최하늘',
    at: relativeFromNow({ days: 2 }),
  },
  {
    id: 'fl-2',
    name: '퍼널_분석_2026-06.xlsx',
    kind: '스프레드시트',
    size: '880KB',
    uploadedBy: '박준호',
    at: relativeFromNow({ days: 4 }),
  },
  {
    id: 'fl-3',
    name: '카피_가이드.pdf',
    kind: 'PDF',
    size: '1.1MB',
    uploadedBy: '이서연',
    at: relativeFromNow({ days: 9 }),
  },
];

export function findProject(slug: string): Project | null {
  return PROJECTS.find((p) => p.slug === slug) ?? null;
}
