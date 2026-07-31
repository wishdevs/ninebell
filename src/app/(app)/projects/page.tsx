import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { IS_DEV_ENV } from '@/lib/env';
import { ProjectsClient } from './_components/projects-client';

export const metadata: Metadata = { title: '프로젝트' };

/**
 * 프로젝트 카드 그리드 — 서버 컴포넌트. 상태 필터(useState) 때문에 본문은
 * 클라이언트 자식(ProjectsClient)으로 분리한다.
 * 정적 픽스처 기반 목업 — 비개발 환경에선 직접 URL 접근을 404 로 막는다(nav devOnly 규약).
 */
export default function ProjectsPage() {
  if (!IS_DEV_ENV) notFound();
  return <ProjectsClient />;
}
