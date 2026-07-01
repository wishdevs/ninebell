/**
 * 업무(Works) 픽스처 — 리스트 + 마스터/디테일 아키타입을 구동한다.
 * 상태/우선순위/담당자/마감/프로젝트/단계/카테고리를 포함.
 */

import { relativeFromNow } from './format';

export type WorkStatus = 'todo' | 'in_progress' | 'review' | 'done';
export type WorkPriority = 'low' | 'medium' | 'high' | 'urgent';

export const WORK_STATUS_LABEL: Record<WorkStatus, string> = {
  todo: '할 일',
  in_progress: '진행 중',
  review: '검토',
  done: '완료',
};

export const WORK_PRIORITY_LABEL: Record<WorkPriority, string> = {
  low: '낮음',
  medium: '보통',
  high: '높음',
  urgent: '긴급',
};

export interface WorkPhase {
  id: string;
  name: string;
  color: string;
}

export interface WorkCategory {
  id: string;
  name: string;
  color: string;
}

export interface Member {
  id: string;
  name: string;
  email: string;
}

export interface ProjectRef {
  id: string;
  slug: string;
  name: string;
}

export interface Work {
  id: string;
  title: string;
  status: WorkStatus;
  priority: WorkPriority;
  projectId: string;
  phaseId: string | null;
  categoryId: string | null;
  assigneeId: string | null;
  /** ISO 마감일. null이면 마감 없음. */
  dueAt: string | null;
  /** ISO 최근 갱신. */
  updatedAt: string;
  /** 마크다운/플레인 설명(상세 패널 본문). */
  description: string;
}

export const WORK_PHASES: readonly WorkPhase[] = [
  { id: 'ph-discovery', name: '리서치', color: 'oklch(64% 0.17 250)' },
  { id: 'ph-design', name: '디자인', color: 'oklch(66% 0.16 320)' },
  { id: 'ph-build', name: '개발', color: 'oklch(64% 0.16 150)' },
  { id: 'ph-launch', name: '런칭', color: 'oklch(70% 0.15 60)' },
];

export const WORK_CATEGORIES: readonly WorkCategory[] = [
  { id: 'cat-content', name: '콘텐츠', color: 'oklch(66% 0.15 40)' },
  { id: 'cat-seo', name: 'SEO', color: 'oklch(64% 0.16 150)' },
  { id: 'cat-dev', name: '개발', color: 'oklch(64% 0.17 250)' },
  { id: 'cat-ops', name: '운영', color: 'oklch(60% 0.04 250)' },
];

export const MEMBERS: readonly Member[] = [
  { id: 'u-001', name: '김도현', email: 'dohyun.kim@ninebell.co.kr' },
  { id: 'u-002', name: '이서연', email: 'seoyeon.lee@ninebell.co.kr' },
  { id: 'u-003', name: '박준호', email: 'junho.park@ninebell.co.kr' },
  { id: 'u-004', name: '최하늘', email: 'haneul.choi@ninebell.co.kr' },
  { id: 'u-005', name: '정유진', email: 'yujin.jung@ninebell.co.kr' },
];

export const PROJECT_REFS: readonly ProjectRef[] = [
  { id: 'pj-commerce', slug: 'commerce-renewal', name: '커머스 리뉴얼' },
  { id: 'pj-genai', slug: 'genai-search', name: '생성형 검색 대응' },
  { id: 'pj-brand', slug: 'brand-site', name: '브랜드 사이트' },
];

export const WORKS: readonly Work[] = [
  {
    id: 'wk-101',
    title: '생성형 검색 노출 키워드 1차 셋업',
    status: 'in_progress',
    priority: 'high',
    projectId: 'pj-genai',
    phaseId: 'ph-discovery',
    categoryId: 'cat-seo',
    assigneeId: 'u-002',
    dueAt: relativeFromNow({ days: -1 }),
    updatedAt: relativeFromNow({ hours: 3 }),
    description:
      '주요 카테고리 30개 키워드에 대해 ChatGPT·Perplexity 노출 여부를 측정한다. 경쟁사 대비 인용 위치를 함께 기록.',
  },
  {
    id: 'wk-102',
    title: '상품 상세 페이지 카피 리라이트',
    status: 'review',
    priority: 'medium',
    projectId: 'pj-commerce',
    phaseId: 'ph-design',
    categoryId: 'cat-content',
    assigneeId: 'u-004',
    dueAt: relativeFromNow({ days: 2 }),
    updatedAt: relativeFromNow({ hours: 20 }),
    description: '베스트셀러 12개 상품 상세 카피를 톤앤매너 가이드에 맞춰 리라이트. 검토 후 배포.',
  },
  {
    id: 'wk-103',
    title: '체크아웃 퍼널 이탈 분석',
    status: 'todo',
    priority: 'urgent',
    projectId: 'pj-commerce',
    phaseId: 'ph-discovery',
    categoryId: 'cat-ops',
    assigneeId: 'u-003',
    dueAt: relativeFromNow({ days: -2 }),
    updatedAt: relativeFromNow({ days: 1 }),
    description: '최근 2주 체크아웃 단계별 이탈률을 GA에서 추출, 결제 직전 이탈 원인 가설을 정리.',
  },
  {
    id: 'wk-104',
    title: '브랜드 사이트 히어로 섹션 모션',
    status: 'in_progress',
    priority: 'medium',
    projectId: 'pj-brand',
    phaseId: 'ph-build',
    categoryId: 'cat-dev',
    assigneeId: 'u-001',
    dueAt: relativeFromNow({ days: 4 }),
    updatedAt: relativeFromNow({ hours: 6 }),
    description: '히어로 오로라 배경 + 스크롤 패럴랙스를 compositor-friendly 속성으로 구현.',
  },
  {
    id: 'wk-105',
    title: 'SSL 인증서 갱신 자동화',
    status: 'todo',
    priority: 'high',
    projectId: 'pj-brand',
    phaseId: 'ph-launch',
    categoryId: 'cat-ops',
    assigneeId: 'u-005',
    dueAt: relativeFromNow({ days: 7 }),
    updatedAt: relativeFromNow({ days: 2 }),
    description: '2개 도메인 인증서 만료 14일 전 자동 갱신 + 슬랙 알림 파이프라인 구성.',
  },
  {
    id: 'wk-106',
    title: '블로그 SEO 메타 일괄 점검',
    status: 'done',
    priority: 'low',
    projectId: 'pj-genai',
    phaseId: 'ph-build',
    categoryId: 'cat-seo',
    assigneeId: 'u-002',
    dueAt: relativeFromNow({ days: -5 }),
    updatedAt: relativeFromNow({ days: 3 }),
    description: '게시글 84건의 title/description/OG 태그를 점검하고 누락분을 채움.',
  },
  {
    id: 'wk-107',
    title: '결제 모듈 PG 연동 리팩터',
    status: 'in_progress',
    priority: 'high',
    projectId: 'pj-commerce',
    phaseId: 'ph-build',
    categoryId: 'cat-dev',
    assigneeId: 'u-003',
    dueAt: relativeFromNow({ days: 3 }),
    updatedAt: relativeFromNow({ hours: 10 }),
    description: '신규 PG사 연동을 위해 결제 추상화 레이어를 도입하고 기존 호출부를 마이그레이션.',
  },
  {
    id: 'wk-108',
    title: '주간 운영 리포트 템플릿',
    status: 'review',
    priority: 'low',
    projectId: 'pj-brand',
    phaseId: 'ph-design',
    categoryId: 'cat-content',
    assigneeId: 'u-004',
    dueAt: null,
    updatedAt: relativeFromNow({ days: 1 }),
    description: '경영진 공유용 주간 KPI 리포트 1페이지 템플릿 초안.',
  },
  {
    id: 'wk-109',
    title: '경쟁사 브랜드 인용 모니터링 룰',
    status: 'todo',
    priority: 'medium',
    projectId: 'pj-genai',
    phaseId: 'ph-discovery',
    categoryId: 'cat-seo',
    assigneeId: null,
    dueAt: relativeFromNow({ days: 5 }),
    updatedAt: relativeFromNow({ days: 1 }),
    description: '경쟁사 3곳의 생성형 검색 인용 패턴을 주기적으로 수집하는 룰 정의.',
  },
  {
    id: 'wk-110',
    title: '모바일 네비게이션 접근성 개선',
    status: 'done',
    priority: 'medium',
    projectId: 'pj-brand',
    phaseId: 'ph-build',
    categoryId: 'cat-dev',
    assigneeId: 'u-001',
    dueAt: relativeFromNow({ days: -8 }),
    updatedAt: relativeFromNow({ days: 4 }),
    description: '드로어 포커스 트랩, 키보드 내비게이션, ARIA 라벨을 보강.',
  },
];

// ── 조회 헬퍼 ────────────────────────────────────────────────────────

export function findWork(id: string): Work | null {
  return WORKS.find((w) => w.id === id) ?? null;
}

export function memberById(id: string | null): Member | null {
  if (!id) return null;
  return MEMBERS.find((m) => m.id === id) ?? null;
}

export function phaseById(id: string | null): WorkPhase | null {
  if (!id) return null;
  return WORK_PHASES.find((p) => p.id === id) ?? null;
}

export function categoryById(id: string | null): WorkCategory | null {
  if (!id) return null;
  return WORK_CATEGORIES.find((c) => c.id === id) ?? null;
}

export function projectRefById(id: string): ProjectRef | null {
  return PROJECT_REFS.find((p) => p.id === id) ?? null;
}
