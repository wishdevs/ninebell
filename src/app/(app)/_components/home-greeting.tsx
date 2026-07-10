'use client';

import { PageHeader } from '@/components/ui/page-header';
import { usePermissions } from '@/hooks/use-permissions';
import { PERMISSIONS } from '@/lib/auth/permissions';
import { useCurrentUser } from '@/app/(app)/providers/user-provider';
import { HomeFavoriteAgents } from './home-favorite-agents';
import { PushAlarmTest } from './push-alarm-test';

/**
 * 홈 — 인사 헤더 + '자주쓰는 에이전트' 최대 3개 (사용자 확정 2026-07-05: 홈은 이것만).
 *
 * 로그인 사용자의 `displayName`으로 인사한다. `useCurrentUser()`는 클라이언트
 * 훅이라 이 조각만 client component로 분리했다((app) 레이아웃의 UserProvider
 * 안이라 항상 인증된 사용자를 반환). 에이전트 접근 권한이 있는 사용자에게만
 * '자주쓰는 에이전트' 섹션을 노출한다(즐겨찾기가 없으면 에이전트 페이지로 유도).
 */
export function HomeGreeting() {
  const user = useCurrentUser();
  const { has } = usePermissions();

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="NINEBELL"
        title={`안녕하세요, ${user.displayName}님`}
        description="나인벨 옴니솔 자동화 대시보드입니다. 자주 쓰는 에이전트를 바로 실행해보세요."
      />

      {has(PERMISSIONS.AGENTS_READ) ? <HomeFavoriteAgents /> : null}

      <PushAlarmTest />
    </div>
  );
}
