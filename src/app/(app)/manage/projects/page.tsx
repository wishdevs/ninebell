import type { Metadata } from 'next';
import { PageHeader } from '@/components/ui/page-header';
import { CodeCatalogManager } from '../_components/code-catalog-manager';

export const metadata: Metadata = { title: '프로젝트 관리' };

/**
 * 프로젝트 관리 — 자주쓰는 프로젝트(WBS 행) 지정·기본지정 + ERP 카탈로그 동기화/검색.
 * 개인 즐겨찾기라 로그인한 모든 사용자가 사용한다(별도 권한 없음).
 */
export default function ProjectsManagePage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="관리"
        title="프로젝트 관리"
        description="자주쓰는 프로젝트와 기본값을 지정합니다. 에이전트가 카드내역 입력에 활용합니다."
      />
      <CodeCatalogManager kind="project" caption="코드" title="프로젝트 카탈로그" description="" />
    </div>
  );
}
