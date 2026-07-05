'use client';

import Link from 'next/link';
import { RiArrowRightLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { usePermissions } from '@/hooks/use-permissions';
import { PERMISSIONS } from '@/lib/auth/permissions';
import { useCurrentUser } from '@/app/(app)/providers/user-provider';

/**
 * 홈 인사 헤더.
 *
 * 로그인 사용자의 `displayName`으로 인사한다. `useCurrentUser()`는 클라이언트
 * 훅이라 이 조각만 client component로 분리했다((app) 레이아웃의 UserProvider
 * 안이라 항상 인증된 사용자를 반환). 에이전트 접근 권한이 있는 사용자에게만
 * 카탈로그 진입 CTA를 노출한다.
 *
 * 페이지 래퍼(`animate-page-enter`·max-w)는 `HomeDashboard`가 소유한다 —
 * 이 컴포넌트는 헤더 블록만 그린다.
 */
export function HomeGreeting() {
  const user = useCurrentUser();
  const { has } = usePermissions();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        caption="NINEBELL"
        title={`안녕하세요, ${user.displayName}님`}
        description="나인벨 옴니솔 자동화 대시보드입니다. 최근 실행 현황을 확인하고 바로 실행해보세요."
      />

      {has(PERMISSIONS.AGENTS_READ) ? (
        <div>
          <Button asChild variant="secondary">
            <Link href="/agents">
              에이전트 살펴보기
              <RiArrowRightLine size={16} aria-hidden />
            </Link>
          </Button>
        </div>
      ) : null}
    </div>
  );
}
