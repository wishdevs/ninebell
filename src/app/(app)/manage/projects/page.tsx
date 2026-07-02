import type { Metadata } from 'next';
import { CodeCatalogManager } from '../_components/code-catalog-manager';

export const metadata: Metadata = { title: '프로젝트 관리' };

/**
 * 프로젝트 관리 — 자주쓰는 프로젝트(WBS 행) 지정·기본지정 + ERP 카탈로그 동기화/검색.
 * 개인 즐겨찾기라 로그인한 모든 사용자가 사용한다(별도 권한 없음).
 */
export default function ProjectsManagePage() {
  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <CodeCatalogManager
        kind="project"
        caption="관리"
        title="프로젝트 관리"
        description="자주쓰는 프로젝트를 관리하고, ERP에서 프로젝트 목록을 동기화합니다. 프로젝트·WBS·위치로 검색할 수 있습니다."
      />
    </div>
  );
}
