'use client';

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { getMe } from '@/lib/api/client';
import { Spinner } from '@/components/ui/spinner';
import type { CurrentUser } from '@/lib/auth/types';

type UserState =
  | { status: 'loading'; user: null }
  | { status: 'authenticated'; user: CurrentUser }
  | { status: 'unauthenticated'; user: null };

interface UserContextValue {
  state: UserState;
  /** 프로필 수정(PATCH /auth/me) 성공 응답 등으로 캐시된 사용자를 갱신한다. */
  setUser: (user: CurrentUser) => void;
}

const UserContext = createContext<UserContextValue | null>(null);

/**
 * 현재 사용자 컨텍스트 제공자.
 *
 * 마운트 시 `GET /auth/me`로 사용자+권한을 로드한다. 로드 전에는 children을
 * 렌더하지 않고(스피너 게이트), 미인증(401)이면 `/login`으로 리다이렉트한다.
 * 따라서 children 내부에서 `useCurrentUser()`는 항상 인증된 사용자를 반환한다.
 *
 * `initialUser`를 주면(서버에서 미리 fetch한 경우) 즉시 authenticated로 시작해
 * 클라이언트 재요청을 건너뛴다.
 *
 * 라운드2 (app) 레이아웃에서 `useCurrentUser`/`usePermissions`를 쓰는 컴포넌트
 * 위에 이 제공자를 배치할 것(보통 DashboardShell 또는 그 children을 감싼다).
 */
export function UserProvider({
  children,
  initialUser,
}: {
  children: ReactNode;
  initialUser?: CurrentUser;
}) {
  const router = useRouter();
  const [state, setState] = useState<UserState>(
    initialUser
      ? { status: 'authenticated', user: initialUser }
      : { status: 'loading', user: null },
  );

  useEffect(() => {
    if (initialUser) {
      return;
    }
    let active = true;
    getMe()
      .then((user) => {
        if (active) {
          setState({ status: 'authenticated', user });
        }
      })
      .catch(() => {
        if (!active) {
          return;
        }
        // 쿠키가 만료/무효일 때(미들웨어를 통과해 들어온 경우) 로그인으로.
        setState({ status: 'unauthenticated', user: null });
        router.replace('/login');
      });
    return () => {
      active = false;
    };
  }, [initialUser, router]);

  if (state.status === 'loading') {
    return (
      <div className="grid min-h-dvh place-items-center">
        <Spinner size={24} label="불러오는 중" className="text-foreground-tertiary" />
      </div>
    );
  }

  if (state.status === 'unauthenticated') {
    return null;
  }

  const setUser = (user: CurrentUser) => setState({ status: 'authenticated', user });

  return <UserContext.Provider value={{ state, setUser }}>{children}</UserContext.Provider>;
}

/**
 * 인증된 현재 사용자를 반환한다. 제공자 밖이거나 미인증 상태에서 호출되면
 * 예외를 던진다 — 제공자가 인증 후에만 children을 렌더하므로 정상 흐름에선
 * 항상 사용자를 안전하게 반환한다.
 */
export function useCurrentUser(): CurrentUser {
  const ctx = useContext(UserContext);
  if (!ctx) {
    throw new Error('useCurrentUser must be used inside <UserProvider>');
  }
  if (ctx.state.status !== 'authenticated') {
    throw new Error('useCurrentUser called before the current user was loaded');
  }
  return ctx.state.user;
}

/** 프로필 수정 등으로 캐시된 현재 사용자를 갱신하는 setter. */
export function useSetCurrentUser(): (user: CurrentUser) => void {
  const ctx = useContext(UserContext);
  if (!ctx) {
    throw new Error('useSetCurrentUser must be used inside <UserProvider>');
  }
  return ctx.setUser;
}
