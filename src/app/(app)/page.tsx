import type { Metadata } from 'next';
import { HomeGreeting } from './_components/home-greeting';

export const metadata: Metadata = {
  title: '홈',
};

/**
 * 대시보드 홈 — 로그인 사용자를 위한 심플 인사 화면.
 *
 * 인사는 `useCurrentUser()`가 필요해 클라이언트 컴포넌트(HomeGreeting)로 분리했고,
 * 페이지 자체는 metadata만 노출하는 서버 컴포넌트로 둔다.
 */
export default function HomePage() {
  return <HomeGreeting />;
}
