import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { IS_DEV_ENV } from '@/lib/env';
import { WorksClient } from './_components/works-client';

export const metadata: Metadata = { title: '업무' };

/**
 * 업무 허브 — 리스트 + 마스터/디테일 아키타입.
 * 서버 컴포넌트로 두어 metadata를 export하고, 인터랙티브 본문은
 * 클라이언트 자식(WorksClient)에 위임한다.
 * 정적 픽스처 기반 목업 — 비개발 환경에선 직접 URL 접근을 404 로 막는다(nav devOnly 규약).
 */
export default function WorksPage() {
  if (!IS_DEV_ENV) notFound();
  return <WorksClient />;
}
