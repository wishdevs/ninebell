/**
 * 대시보드 홈 픽스처 — 알림 피드 + 모듈별 인사이트 카드.
 *
 * 원본의 `/t/{slug}` 환영 화면을 그대로 차용: 상단은 조치가 필요한 고-신호
 * 알림 3~4건, 하단은 활성 모듈별 요약 Bento 카드.
 */

import type { ModuleKey } from './workspace';
import { relativeFromNow } from './format';

export type HomeAlertSeverity = 'urgent' | 'warning' | 'info';

export interface HomeAlert {
  id: string;
  severity: HomeAlertSeverity;
  module: ModuleKey;
  title: string;
  detail?: string;
  /** 클릭 시 이동할 모듈 경로(기본형은 라우트만 존재하면 됨). */
  href: string;
  ctaLabel: string;
  occurredAt: string;
}

export const HOME_ALERTS: readonly HomeAlert[] = [
  {
    id: 'alert-geo-failed-run',
    severity: 'urgent',
    module: 'geo',
    title: '브랜드 모니터링 배치 1건 실패',
    detail: '검토 후 재실행이 필요합니다.',
    href: '/works',
    ctaLabel: '실행 보기',
    occurredAt: relativeFromNow({ hours: 2 }),
  },
  {
    id: 'alert-monitoring-ssl',
    severity: 'warning',
    module: 'monitoring',
    title: 'SSL 만료 임박 — 2개 도메인',
    detail: '14일 이내 만료 예정. 갱신 일정 확인이 필요합니다.',
    href: '/analytics',
    ctaLabel: '도메인 확인',
    occurredAt: relativeFromNow({ hours: 6 }),
  },
  {
    id: 'alert-work-pending-review',
    severity: 'warning',
    module: 'work',
    title: '내 검토 대기 업무 5건',
    detail: '평균 대기 1.4일 · 이번 주 안에 처리 권장.',
    href: '/works',
    ctaLabel: '업무 열기',
    occurredAt: relativeFromNow({ hours: 18 }),
  },
  {
    id: 'alert-playbook-stale',
    severity: 'info',
    module: 'playbook',
    title: '플레이북 갱신 1주차 지연',
    detail: '월간 자동 갱신은 다음 새벽에 재시도됩니다.',
    href: '/projects',
    ctaLabel: '프로젝트 보기',
    occurredAt: relativeFromNow({ days: 1 }),
  },
];

// ── 모듈별 인사이트 카드 ─────────────────────────────────────────────

export interface GeoInsight {
  module: 'geo';
  label: string;
  caption: string;
  href: string;
  activeBrands: number;
  alarmCount: number;
  /** 7일 노출량 스파크라인. */
  exposureSparkline: readonly number[];
  hint: string;
}

export interface WorksInsight {
  module: 'work';
  label: string;
  caption: string;
  href: string;
  total: number;
  inProgress: number;
  done: number;
  overdue: number;
  hint: string;
}

export interface GaInsight {
  module: 'ga';
  label: string;
  caption: string;
  href: string;
  sessions7d: number;
  deltaPct: number;
  sparkline: readonly number[];
  hint: string;
}

export interface MonitoringInsight {
  module: 'monitoring';
  label: string;
  caption: string;
  href: string;
  siteCount: number;
  avgUptimePct: number;
  downCount: number;
  hint: string;
}

export interface PlaybookInsight {
  module: 'playbook';
  label: string;
  caption: string;
  href: string;
  latestVersion: string;
  latestUpdatedAt: string;
  pendingReviewCount: number;
  hint: string;
}

export type ModuleInsight =
  GeoInsight | WorksInsight | GaInsight | MonitoringInsight | PlaybookInsight;

export const MODULE_INSIGHTS: readonly ModuleInsight[] = [
  {
    module: 'geo',
    label: 'GEO 모니터링',
    caption: '생성형 검색 노출 추적',
    href: '/works',
    activeBrands: 4,
    alarmCount: 2,
    exposureSparkline: [38, 41, 47, 52, 49, 58, 64],
    hint: '최근 7일 노출 +14% · 경보 2건',
  },
  {
    module: 'work',
    label: '업무',
    caption: '진행 중 업무 현황',
    href: '/works',
    total: 47,
    inProgress: 23,
    done: 18,
    overdue: 6,
    hint: '오늘 마감 3건 · 지연 6건',
  },
  {
    module: 'ga',
    label: 'GA 대시보드',
    caption: '최근 7일 세션',
    href: '/analytics',
    sessions7d: 14820,
    deltaPct: 8.3,
    sparkline: [1820, 2050, 1990, 2240, 2310, 2180, 2230],
    hint: '전주 대비 +8.3%',
  },
  {
    module: 'monitoring',
    label: '모니터링',
    caption: '사이트 가동률',
    href: '/analytics',
    siteCount: 12,
    avgUptimePct: 99.94,
    downCount: 0,
    hint: '24시간 평균 가동률 99.94%',
  },
  {
    module: 'playbook',
    label: '플레이북',
    caption: '최신 운영 가이드',
    href: '/projects',
    latestVersion: 'v3.2',
    latestUpdatedAt: relativeFromNow({ days: 14 }),
    pendingReviewCount: 1,
    hint: '검토 대기 1건 · 2주 전 갱신',
  },
];

/** 활성 모듈만, 사이드바와 동일한 정규 순서로 인사이트를 반환. */
export function getModuleInsights(enabled: readonly ModuleKey[]): readonly ModuleInsight[] {
  const set = new Set(enabled);
  return MODULE_INSIGHTS.filter((insight) => set.has(insight.module));
}
