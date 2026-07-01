/**
 * 권한/롤 상수 — 백엔드 `backend/app/core/permissions.py`와 1:1로 동기화한다.
 *
 * 글로벌 단일 테넌트라 ax의 `system:`/`org:` 스코프 구분 없이
 * `<resource>:<action>` 컨벤션만 사용한다. 백엔드가 권한을 추가하면
 * 이 파일도 수동으로 갱신할 것(추후 OpenAPI 스키마에서 생성 자동화 가능).
 */

export const PERMISSIONS = {
  USERS_READ: 'users:read',
  USERS_WRITE: 'users:write',
  USERS_DELETE: 'users:delete',
  ROLES_READ: 'roles:read',
  ROLES_ASSIGN: 'roles:assign',
  AGENTS_READ: 'agents:read',
  AGENTS_WRITE: 'agents:write',
  AGENTS_DELETE: 'agents:delete',
  LOGS_READ: 'logs:read',
} as const;

export type PermissionCode = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

export const ROLES = {
  SUPER_ADMIN: 'super_admin',
  ADMIN: 'admin',
  USER: 'user',
} as const;

export type Role = (typeof ROLES)[keyof typeof ROLES];

/** 역할 계층 랭크 — `roleAtLeast`로 "최소 롤" 게이팅에 사용. 백엔드 `_ROLE_RANK`와 동일. */
export const ROLE_RANK: Record<Role, number> = {
  user: 1,
  admin: 2,
  super_admin: 3,
};

export function hasPermission(userPerms: readonly string[], code: PermissionCode): boolean {
  return userPerms.includes(code);
}

export function hasAnyPermission(
  userPerms: readonly string[],
  codes: readonly PermissionCode[],
): boolean {
  return codes.some((c) => userPerms.includes(c));
}

export function hasAllPermissions(
  userPerms: readonly string[],
  codes: readonly PermissionCode[],
): boolean {
  return codes.every((c) => userPerms.includes(c));
}

/** `role`이 `min` 이상의 계층인지. 예: roleAtLeast(user.role, ROLES.ADMIN). */
export function roleAtLeast(role: Role, min: Role): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[min];
}
