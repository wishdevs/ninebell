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
 * 읽기는 로그인한 모든 사용자, 작성·수정·삭제는 관리자 전용(백엔드가 최종 강제).
 * 본문은 마크다운이며 대부분 Claude Code 가 커밋 후 API 로 등록하고, 사람은 여기서
 * 검토·수정한다. 미공개(draft)는 관리자에게만 보인다.
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
