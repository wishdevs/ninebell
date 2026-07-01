'use client';

import type { ReactNode } from 'react';
import { usePermissions } from '@/hooks/use-permissions';
import type { PermissionCode } from '@/lib/auth/permissions';

interface PermGateProps {
  /** 단일 권한 요구(이 권한이 있으면 통과). */
  require?: PermissionCode;
  /** 여러 권한 중 하나라도 있으면 통과. `require`와 함께 쓰면 `require`가 우선. */
  requireAny?: readonly PermissionCode[];
  children: ReactNode;
  /** 권한이 없을 때 렌더. 기본 null(숨김). */
  fallback?: ReactNode;
}

/**
 * 클라이언트 권한 게이트.
 *
 * 권한이 있으면 `children`, 없으면 `fallback`(기본 null)을 렌더한다.
 * 삭제/수정 같은 작은 어포던스 숨김에 적합하다. 주요 CTA는 숨기기보다
 * `usePermissions().has()`로 "비활성+툴팁" 상태를 권장한다(ax 관례).
 *
 * 중요: 이것은 UX 보조일 뿐이다 — 백엔드가 해당 엔드포인트에서
 * `require_permission()`로 권한을 최종 강제한다.
 */
export function PermGate({ require, requireAny, children, fallback = null }: PermGateProps) {
  const { has, hasAny } = usePermissions();
  const allowed = require ? has(require) : requireAny ? hasAny(...requireAny) : true;
  return <>{allowed ? children : fallback}</>;
}

/** 단일 권한 보유 여부를 반환하는 편의 훅. 비활성 상태/툴팁 분기에 사용. */
export function useCan(code: PermissionCode): boolean {
  return usePermissions().has(code);
}
