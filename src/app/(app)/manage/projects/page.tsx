import { Suspense } from 'react';
import type { Metadata } from 'next';
import Link from 'next/link';
import { PageHeader } from '@/components/ui/page-header';
import { cn } from '@/lib/utils';
import { CodeCatalogManager } from '../_components/code-catalog-manager';

export const metadata: Metadata = { title: '프로젝트 관리' };

/** 자주쓰는 프로젝트의 용도 스코프 — 프로젝트 코드 목록(카탈로그)은 둘이 공유하고,
 * 즐겨찾기·기본지정만 갈라 담는다(백엔드 kind, 2026-08-21 사용자 결정). */
const SCOPES = [
  {
    id: 'resolution',
    label: '결의서용',
    href: '/manage/projects',
    favoriteKind: 'project',
    description: '자주쓰는 프로젝트와 기본값을 지정합니다. 에이전트가 카드내역 입력에 활용합니다.',
  },
  {
    id: 'purchase',
    label: '구매팀용',
    href: '/manage/projects?scope=purchase',
    favoriteKind: 'project_purchase',
    description: '구매팀이 자주쓰는 프로젝트를 지정합니다. 구매발주 실행 전 폼이 이 목록을 씁니다.',
  },
] as const;

interface ProjectsManagePageProps {
  searchParams: Promise<{ scope?: string }>;
}

/**
 * 프로젝트 관리 — 자주쓰는 프로젝트(WBS 행) 지정·기본지정 + ERP 카탈로그 동기화/검색.
 * 개인 즐겨찾기라 로그인한 모든 사용자가 사용한다(별도 권한 없음).
 * `?scope=purchase` 면 구매팀용 즐겨찾기(kind='project_purchase')를 다룬다 — 카탈로그는
 * 어느 쪽이든 같은 'project' 목록이라 동기화 결과가 두 용도에 함께 반영된다.
 * Suspense 경계는 CodeCatalogManager 의 useListParams(useSearchParams) 요구 —
 * 클라이언트가 즉시 자체 로딩을 그리므로 fallback 은 null.
 */
export default async function ProjectsManagePage({ searchParams }: ProjectsManagePageProps) {
  const { scope } = await searchParams;
  const active = SCOPES.find((s) => s.id === scope) ?? SCOPES[0];

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader caption="관리" title="프로젝트 관리" description={active.description} />
      <nav aria-label="자주쓰는 프로젝트 용도" className="flex items-center gap-1.5">
        {SCOPES.map((s) => {
          const current = s.id === active.id;
          return (
            <Link
              key={s.id}
              href={s.href}
              aria-current={current ? 'page' : undefined}
              className={cn(
                'flex h-9 items-center rounded-full border px-3.5 text-[13px] font-medium transition-colors',
                current
                  ? 'border-accent/40 bg-accent/10 text-accent'
                  : 'border-border text-foreground-secondary hover:border-accent/50 hover:text-foreground',
              )}
            >
              {s.label}
            </Link>
          );
        })}
      </nav>
      <Suspense key={active.id} fallback={null}>
        <CodeCatalogManager
          kind="project"
          favoriteKind={active.favoriteKind}
          favoriteLabel={active.label}
          caption="코드"
          title="프로젝트 카탈로그"
          description=""
        />
      </Suspense>
    </div>
  );
}
