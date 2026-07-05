import type { Metadata } from 'next';
import { HomeGreeting } from './_components/home-greeting';

export const metadata: Metadata = {
  title: '홈',
};

/**
 * 홈 — 인사 헤더 + 자주쓰는 에이전트 최대 3개 (사용자 확정 2026-07-05: 홈은 이것만.
 * 이전 KPI·최근 실행·바로실행 대시보드는 .recycles/ 로 이동).
 *
 * 데이터는 httpOnly 세션 쿠키가 필요해 클라이언트 컴포넌트(HomeGreeting →
 * HomeFavoriteAgents)에서 로드하고, 페이지 자체는 metadata만 노출하는 서버 컴포넌트.
 */
export default function HomePage() {
  return <HomeGreeting />;
}
