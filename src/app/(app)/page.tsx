import type { Metadata } from 'next';
import { HomeDashboard } from './_components/home-dashboard';

export const metadata: Metadata = {
  title: '홈',
};

/**
 * 대시보드 홈 — 인사 헤더 + 실행 이력·KPI·바로 실행(UX 토론 합의).
 *
 * 데이터는 httpOnly 세션 쿠키가 필요해 클라이언트 컴포넌트(HomeDashboard)에서
 * 로드하고, 페이지 자체는 metadata만 노출하는 서버 컴포넌트로 둔다.
 */
export default function HomePage() {
  return <HomeDashboard />;
}
