/**
 * 애널리틱스(GA 풍) 대시보드 픽스처 — KPI · 추이 · 채널 · 디바이스 · 인기 페이지.
 * recharts 차트와 KPI 카드에 그대로 먹인다.
 */

export interface KpiDatum {
  key: string;
  label: string;
  /** 포맷 완료된 표시 문자열. */
  value: string;
  /** 비교 기간 대비 부호 있는 증감률(%). null이면 증감 행 숨김. */
  delta: number | null;
  /** "전주 대비" 등 비교 라벨. */
  deltaLabel: string;
  /** up이 좋은 지표인지(대부분) / down이 좋은지(이탈률). */
  tone: 'positive-up' | 'positive-down' | 'neutral';
}

export const KPIS: readonly KpiDatum[] = [
  {
    key: 'users',
    label: '활성 사용자',
    value: '38,204',
    delta: 8.3,
    deltaLabel: '전주 대비',
    tone: 'positive-up',
  },
  {
    key: 'sessions',
    label: '세션',
    value: '52,914',
    delta: 6.1,
    deltaLabel: '전주 대비',
    tone: 'positive-up',
  },
  {
    key: 'engagement',
    label: '참여 시간',
    value: '2분 14초',
    delta: 3.4,
    deltaLabel: '전주 대비',
    tone: 'positive-up',
  },
  {
    key: 'bounce',
    label: '이탈률',
    value: '41.2%',
    delta: -2.7,
    deltaLabel: '전주 대비',
    tone: 'positive-down',
  },
];

export interface TrendPoint {
  date: string; // YYYY-MM-DD
  activeUsers: number;
  sessions: number;
}

export const TRAFFIC_TREND: readonly TrendPoint[] = [
  { date: '2026-06-01', activeUsers: 4120, sessions: 5680 },
  { date: '2026-06-02', activeUsers: 4380, sessions: 6010 },
  { date: '2026-06-03', activeUsers: 4015, sessions: 5520 },
  { date: '2026-06-04', activeUsers: 4690, sessions: 6450 },
  { date: '2026-06-05', activeUsers: 5120, sessions: 7020 },
  { date: '2026-06-06', activeUsers: 4870, sessions: 6680 },
  { date: '2026-06-07', activeUsers: 4520, sessions: 6210 },
  { date: '2026-06-08', activeUsers: 4980, sessions: 6840 },
  { date: '2026-06-09', activeUsers: 5340, sessions: 7330 },
  { date: '2026-06-10', activeUsers: 5210, sessions: 7150 },
  { date: '2026-06-11', activeUsers: 5680, sessions: 7790 },
  { date: '2026-06-12', activeUsers: 5420, sessions: 7440 },
  { date: '2026-06-13', activeUsers: 5090, sessions: 6980 },
  { date: '2026-06-14', activeUsers: 5610, sessions: 7700 },
];

export interface ChannelDatum {
  channel: string;
  sessions: number;
  /** 점유율(%). */
  share: number;
}

export const CHANNELS: readonly ChannelDatum[] = [
  { channel: '자연 검색', sessions: 18420, share: 34.8 },
  { channel: '직접 유입', sessions: 12810, share: 24.2 },
  { channel: '소셜', sessions: 9240, share: 17.5 },
  { channel: '추천', sessions: 6680, share: 12.6 },
  { channel: '이메일', sessions: 3520, share: 6.7 },
  { channel: '유료 검색', sessions: 2244, share: 4.2 },
];

export interface DeviceDatum {
  device: '모바일' | '데스크톱' | '태블릿';
  sessions: number;
  share: number;
}

export const DEVICES: readonly DeviceDatum[] = [
  { device: '모바일', sessions: 32140, share: 60.7 },
  { device: '데스크톱', sessions: 17890, share: 33.8 },
  { device: '태블릿', sessions: 2884, share: 5.5 },
];

export interface TopPageRow {
  path: string;
  title: string;
  views: number;
  avgSeconds: number;
  bounceRate: number;
}

export const TOP_PAGES: readonly TopPageRow[] = [
  { path: '/', title: '홈', views: 18420, avgSeconds: 96, bounceRate: 38.2 },
  {
    path: '/products/ax-suite',
    title: 'AX 스위트 소개',
    views: 9240,
    avgSeconds: 184,
    bounceRate: 29.4,
  },
  { path: '/pricing', title: '요금제', views: 7180, avgSeconds: 142, bounceRate: 44.1 },
  {
    path: '/blog/genai-search',
    title: '생성형 검색 가이드',
    views: 5860,
    avgSeconds: 268,
    bounceRate: 22.7,
  },
  {
    path: '/docs/getting-started',
    title: '시작하기',
    views: 4410,
    avgSeconds: 312,
    bounceRate: 18.9,
  },
  { path: '/contact', title: '문의', views: 2980, avgSeconds: 88, bounceRate: 51.3 },
];

export type AnalyticsRange = '7d' | '28d' | '90d';

export const RANGE_LABEL: Record<AnalyticsRange, string> = {
  '7d': '최근 7일',
  '28d': '최근 28일',
  '90d': '최근 90일',
};
