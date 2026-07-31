import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { IS_DEV_ENV } from '@/lib/env';
import { AnalyticsClient } from './_components/analytics-client';

export const metadata: Metadata = { title: '애널리틱스' };

/**
 * 애널리틱스(GA 풍) 대시보드 — 차트 Bento 아키타입.
 *
 * 서버 컴포넌트로 두어 `metadata`를 export하고, 기간 상태·recharts 등
 * 모든 인터랙션은 클라이언트 자식(`AnalyticsClient`)으로 분리한다.
 * 데이터는 `@/lib/data/analytics`의 동기 더미데이터를 그대로 사용한다.
 */
export default function AnalyticsPage() {
  // 정적 더미데이터 기반 목업 — 비개발 환경에선 직접 URL 접근을 404 로 막는다(nav devOnly 규약).
  if (!IS_DEV_ENV) notFound();
  return <AnalyticsClient />;
}
