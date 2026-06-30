import type { Metadata } from 'next';
import { ProjectsClient } from './_components/projects-client';

export const metadata: Metadata = { title: '프로젝트' };

/**
 * 프로젝트 카드 그리드 — 서버 컴포넌트. 상태 필터(useState) 때문에 본문은
 * 클라이언트 자식(ProjectsClient)으로 분리한다.
 */
export default function ProjectsPage() {
  return <ProjectsClient />;
}
