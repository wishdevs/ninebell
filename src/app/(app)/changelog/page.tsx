import { Suspense } from 'react';
import type { Metadata } from 'next';
import { ChangelogClient } from './_components/changelog-client';

export const metadata: Metadata = {
  title: '변경사항',
};

/**
 * 변경사항(릴리스 노트) 화면 — 대시보드/에이전트에 무엇이 추가·수정·삭제됐는지를
 * 릴리스(버전) 단위로 최신순 타임라인으로 보여준다(`GET /changelog`).
 *
 * 읽기 전용 — 릴리스는 backend/app/data/releases/*.md 에서 기동 시 적재된다(2026-09-02
 * 화면의 작성·수정·삭제 UI 제거). 본문은 마크다운이며 미공개(draft)는 관리자에게만 보인다.
 * Suspense 경계는 useListParams(useSearchParams) 요구 — 클라이언트가 즉시 자체 로딩을
 * 그리므로 fallback 은 null.
 */
export default function ChangelogPage() {
  return (
    <Suspense fallback={null}>
      <ChangelogClient />
    </Suspense>
  );
}
