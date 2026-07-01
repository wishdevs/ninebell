/**
 * `GET /auth/me` 응답 계약과 1:1로 대응하는 현재 사용자 타입.
 *
 * 백엔드 schemas와 camelCase 키까지 일치한다. `src/lib/data/workspace.ts`의
 * 더미 `CurrentUser`와는 별개이며(라운드2에서 화면이 이 타입으로 수렴),
 * 권한 인프라(useCurrentUser/usePermissions/PermGate)는 이 타입을 소비한다.
 */

import type { Role } from './permissions';

export interface CurrentUser {
  id: string;
  omnisolUserid: string;
  displayName: string;
  /** 옴니솔 프로필에서 추출 가능 시. 없으면 null. */
  department: string | null;
  /** 옴니솔 프로필에 이메일이 없을 수 있어 nullable. */
  email: string | null;
  role: Role;
  /** 롤로부터 평탄화된 권한 코드 목록. PermissionCode의 상위집합일 수 있어 string[]. */
  permissions: string[];
  /** 직전 로그인 시각(ISO). 최초 생성 직후 등에서 null 가능. */
  lastLoginAt: string | null;
}
