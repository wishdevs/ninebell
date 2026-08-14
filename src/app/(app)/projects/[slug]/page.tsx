import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { findProject } from '@/lib/data/projects';
import { IS_DEV_ENV } from '@/lib/env';
import { ProjectDetailClient } from './_components/project-detail-client';

interface ProjectDetailPageProps {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: ProjectDetailPageProps): Promise<Metadata> {
  const { slug } = await params;
  const project = findProject(slug);
  return {
    title: project ? `${project.name} · 프로젝트` : '프로젝트',
  };
}

/**
 * 프로젝트 상세 — 서버 컴포넌트. params(Promise)를 풀어 더미데이터에서 프로젝트를
 * 조회하고, 없으면 notFound(). 인터랙티브한 탭/헤더는 클라이언트 자식으로 위임한다.
 */
export default async function ProjectDetailPage({ params }: ProjectDetailPageProps) {
  // 목록(/projects)과 같은 정적 픽스처 목업 — 비개발 환경에선 직접 URL 접근을 404 로 막는다.
  if (!IS_DEV_ENV) notFound();
  const { slug } = await params;
  const project = findProject(slug);
  if (!project) notFound();

  return <ProjectDetailClient project={project} />;
}
