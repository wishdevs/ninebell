'use client';

import { useMemo } from 'react';
import { useCurrentUser } from '@/app/(app)/providers/user-provider';
import type { PermissionCode, Role } from '@/lib/auth/permissions';

interface UsePermissionsResult {
  has: (code: PermissionCode) => boolean;
  hasAny: (...codes: PermissionCode[]) => boolean;
  hasAll: (...codes: PermissionCode[]) => boolean;
  role: Role;
  permissions: readonly string[];
}

/**
 * 현재 사용자의 권한 체크 헬퍼. `<UserProvider>` 내부에서만 사용.
 *
 * UX 게이팅 용도다 — 백엔드가 각 엔드포인트에서 권한을 최종 강제한다.
 */
export function usePermissions(): UsePermissionsResult {
  const user = useCurrentUser();

  return useMemo(() => {
    const set = new Set(user.permissions);
    return {
      has: (code) => set.has(code),
      hasAny: (...codes) => codes.some((c) => set.has(c)),
      hasAll: (...codes) => codes.every((c) => set.has(c)),
      role: user.role,
      permissions: user.permissions,
    };
  }, [user.permissions, user.role]);
}
