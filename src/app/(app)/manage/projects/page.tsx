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
        description="자주쓰는 프로젝트를 지정하고 기본값을 정해 두면, 결의서 입력 에이전트가 카드내역에 자동으로 채워 줍니다. 목록은 ERP에서 동기화합니다."
      />
      <CodeCatalogManager
        kind="project"
        caption="코드"
        title="프로젝트 카탈로그"
        description="프로젝트명·번호, WBS요소, 위치로 검색할 수 있습니다."
      />
    </div>
  );
}
