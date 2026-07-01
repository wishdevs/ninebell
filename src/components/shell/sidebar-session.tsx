'use client';

import { useEffect, useState } from 'react';
import { RiTimeLine } from '@remixicon/react';
import { useCurrentUser } from '@/app/(app)/providers/user-provider';
import { formatDateTime } from '@/lib/data/format';

const TIME_FMT = new Intl.DateTimeFormat('ko-KR', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

/**
 * 사이드바 하단(사용자 카드 위) — 최근 접속 시각 + 현재 라이브 시계.
 * 탑바를 제거하면서 옮겨온 정보. 라이브 시계는 마운트 전 자리표시자로 렌더해
 * 하이드레이션을 안전하게 한다.
 */
export function SidebarSession() {
  const user = useCurrentUser();
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="border-border-subtle flex flex-col gap-0.5 border-t px-4 py-2 text-[10px]">
      <div className="flex items-center justify-between gap-2">
        <span className="text-foreground-tertiary inline-flex min-w-0 items-center gap-1">
          <RiTimeLine size={10} aria-hidden className="shrink-0" />
          최근 접속
        </span>
        <span className="text-foreground-secondary shrink-0 tabular-nums">
          {user.lastLoginAt ? formatDateTime(user.lastLoginAt) : '—'}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-foreground-tertiary inline-flex items-center gap-1">
          <span aria-hidden className="bg-success size-1.5 animate-pulse rounded-full" />
          현재
        </span>
        <span suppressHydrationWarning className="text-foreground font-semibold tabular-nums">
          {now ? TIME_FMT.format(now) : '--:--:--'}
        </span>
      </div>
    </div>
  );
}
