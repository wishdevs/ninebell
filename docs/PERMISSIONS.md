# 권한 시스템 (RBAC) 문서

> **이 문서는 살아있는 문서(living document)입니다.** 권한이 하나라도 추가/변경될 때마다 반드시 함께 갱신합니다.
> 권한은 앞으로 매우 많아지고 백엔드·프론트 전반에서 계속 재사용되므로, 시스템 구조와 재사용 래퍼(wrapper)를 여기에 한 곳에 정리해 둡니다.

대시보드는 **글로벌 단일 테넌트** 모델입니다. 조직/워크스페이스 스코프는 없고, 롤은 전역(global)으로 한 사용자당 하나의 롤(`role_id`)만 가집니다.

---

## 1. 롤 계층 (Role Hierarchy)

세 가지 전역 롤이 있습니다. 각 롤은 `roles.code` 컬럼의 고정 값입니다.

| 롤 코드 | 이름 | 랭크 | 설명 |
|---|---|---|---|
| `super_admin` | 최고관리자 | 3 | 모든 권한. env `SUPER_ADMIN_OMNISOL_IDS`에 등록된 옴니솔 ID가 최초 로그인 시 부여됨. |
| `admin` | 관리자 | 2 | 현재 `super_admin`과 **동일한 권한 집합**을 가짐(아래 분리 근거 참고). |
| `user` | 사용자 | 1 | 최소 권한. 기본값으로 `agents:read` 만. 사용자/로그 관리 불가. |

### 역할 랭크 (Role Rank)

```python
_ROLE_RANK = {"user": 1, "admin": 2, "super_admin": 3}
```

랭크는 `require_role_min(rank)` 게이트에서 "이 롤 이상" 비교에 사용합니다.
숫자가 클수록 상위 롤입니다 (`super_admin` > `admin` > `user`).

### super_admin 과 admin 을 분리해 둔 근거 (중요)

- **현재 시점에는 두 롤의 권한 집합이 100% 동일합니다.** 즉 `admin`도 모든 권한을 가집니다.
- 그럼에도 **`roles` 테이블에서 별도의 행(row)으로, 그리고 소스 코드에서 별도의 상수/매핑으로 분리**해 둡니다.
- **이유: 스키마 마이그레이션 없이 향후 권한을 분기(diverge)시키기 위함**입니다.
  - 예) 나중에 "테넌트 삭제", "결제 설정", "감사로그 영구삭제" 같은 권한이 생기면 `super_admin`에만 부여하고 `admin`에서는 빼면 됩니다.
  - 이때 바꾸는 것은 `DEFAULT_ROLES` 매핑과 `role_permissions` seed 뿐이고, **테이블 구조(스키마)는 그대로**입니다.
- 만약 지금 둘을 하나로 합쳐버리면, 나중에 분기시킬 때 롤을 새로 만들고 모든 사용자를 재매핑하는 마이그레이션이 필요해집니다. 그 비용을 미리 회피하는 설계입니다.

---

## 2. 권한 코드 컨벤션 (Permission Codes)

### 컨벤션

권한 코드는 항상 `<resource>:<action>` 형식의 소문자 문자열입니다.

- `resource` — 대상 자원 (예: `users`, `roles`, `agents`, `logs`)
- `action` — 동작 (예: `read`, `write`, `delete`, `assign`)

이 컨벤션 덕분에 자원별로 권한을 그룹화·검색하기 쉽고, 화면 단위 게이팅에 그대로 매핑됩니다.

### 현재 권한 코드 목록

| 권한 코드 | 설명 | super_admin | admin | user |
|---|---|:---:|:---:|:---:|
| `users:read` | 사용자(멤버) 목록 조회 | ✅ | ✅ | ❌ |
| `users:write` | 사용자 생성/수정(상태 변경 등) | ✅ | ✅ | ❌ |
| `users:delete` | 사용자 삭제 | ✅ | ✅ | ❌ |
| `roles:read` | 롤 목록/구성 조회 | ✅ | ✅ | ❌ |
| `roles:assign` | 사용자에게 롤 부여/변경 | ✅ | ✅ | ❌ |
| `agents:read` | 에이전트 리스트/상세 조회 | ✅ | ✅ | ✅ |
| `agents:write` | 에이전트 생성/수정 | ✅ | ✅ | ❌ |
| `agents:delete` | 에이전트 삭제 | ✅ | ✅ | ❌ |
| `logs:read` | 접속 로그(로깅 화면) 조회 | ✅ | ✅ | ❌ |

> **사용자 관리 CRUD는 `admin` 이상 전용입니다.** `users:read`/`users:write`/`users:delete`/`roles:assign`/`logs:read`는 `super_admin`·`admin`에만 부여됩니다. `user` 롤은 에이전트 조회(`agents:read`)만 가능하며 멤버/로깅 화면의 변경 액션은 노출되지 않습니다.

### 기본 롤 매핑 요약

- **`super_admin`**: 위 표의 전체 권한.
- **`admin`**: 위 표의 전체 권한 (현재 `super_admin`과 동일 — 단, 1절의 근거대로 소스/DB에서 분리).
- **`user`**: `agents:read` 만.

소스 오브 트루스(source of truth)는 백엔드 `app/core/permissions.py`의 상수와 `DEFAULT_ROLES`입니다. 프론트의 `src/lib/auth/permissions.ts`는 이 값과 **수동으로 동기화**해야 합니다(4절 절차 참고).

---

## 3. 재사용 프리미티브 사용법 (Reusable Primitives)

권한 검사는 백엔드/프론트 모두 **재사용 가능한 래퍼**로만 수행합니다. 엔드포인트/컴포넌트마다 직접 롤 문자열을 비교하지 마세요.

### 3.1 백엔드 (FastAPI) — `Depends(...)` 게이트

`app/core/deps.py`가 다음을 제공합니다.

| 프리미티브 | 시그니처 | 용도 |
|---|---|---|
| `require_permission(code)` | `(code: str) -> Depends` | 단일 권한 요구. 없으면 403. |
| `require_any_permission(*codes)` | `(*codes: str) -> Depends` | 나열된 권한 중 **하나라도** 있으면 통과. |
| `require_role_min(rank)` | `(rank: int) -> Depends` | 지정 랭크 **이상**의 롤이면 통과. |
| `collect_user_permissions(user)` | `(user: User) -> set[str]` | 사용자의 롤에서 권한 코드 집합을 평탄화(flatten). `/auth/me`의 `permissions[]` 생성과 게이트 내부 검사에 사용. |

각 `require_*`는 의존성 팩토리입니다. 호출하면 `Depends`로 쓸 콜러블을 돌려주고, 검증을 통과하면 현재 `User`를 반환합니다.

**엔드포인트 예시 — `users:write` 게이트:**

```python
from typing import Annotated
from fastapi import APIRouter, Depends

from app.core.deps import require_permission, require_role_min
from app.core.permissions import USERS_WRITE
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    payload: UserUpdate,
    # users:write 권한이 없으면 여기서 403으로 차단됨
    actor: Annotated[User, Depends(require_permission(USERS_WRITE))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ...
```

**any-of 예시** (둘 중 하나라도 있으면 통과):

```python
from app.core.deps import require_any_permission
from app.core.permissions import USERS_WRITE, ROLES_ASSIGN

actor: Annotated[User, Depends(require_any_permission(USERS_WRITE, ROLES_ASSIGN))]
```

**랭크 기반 예시** (admin 이상):

```python
from app.core.deps import require_role_min

actor: Annotated[User, Depends(require_role_min(2))]  # 2 = admin 이상
```

### 3.2 프론트엔드 (React) — 훅 & 게이트 컴포넌트

권한 상수는 `src/lib/auth/permissions.ts`의 `PERMISSIONS`를 통해 참조합니다(문자열 하드코딩 금지).

**`usePermissions()` — `src/hooks/use-permissions.ts`:**

현재 사용자(user-provider 컨텍스트)의 평탄화된 권한 집합으로 다음을 제공합니다.

```tsx
import { usePermissions } from "@/hooks/use-permissions";
import { PERMISSIONS } from "@/lib/auth/permissions";

function Example() {
  const { has, hasAny, hasAll } = usePermissions();

  has(PERMISSIONS.USERS_WRITE);                                  // boolean
  hasAny([PERMISSIONS.USERS_WRITE, PERMISSIONS.ROLES_ASSIGN]);   // 하나라도 있으면 true
  hasAll([PERMISSIONS.USERS_WRITE, PERMISSIONS.USERS_DELETE]);   // 전부 있어야 true
}
```

**`<PermGate>` — `src/components/permissions/perm-gate.tsx`:**

권한이 있을 때만 자식을 렌더링합니다. 없으면 아무것도(또는 `fallback`) 렌더링하지 않습니다. 메뉴/섹션 자체를 숨길 때 적합합니다.

```tsx
import { PermGate } from "@/components/permissions/perm-gate";
import { PERMISSIONS } from "@/lib/auth/permissions";

<PermGate require={PERMISSIONS.USERS_WRITE}>
  <InviteMemberButton />
</PermGate>

// fallback 제공 예
<PermGate require={PERMISSIONS.LOGS_READ} fallback={<EmptyState />}>
  <LogsTable />
</PermGate>
```

**CTA 패턴 — "비활성 + 툴팁" (권장):**

버튼/액션 같은 CTA는 **숨기기보다 비활성화(disabled) + 사유 툴팁**을 권장합니다. 사용자가 "왜 못 누르는지"를 알 수 있어 UX가 좋습니다. (완전히 가려야 하는 민감한 메뉴는 `<PermGate>`로 숨깁니다.)

```tsx
function DeleteUserButton() {
  const { has } = usePermissions();
  const canDelete = has(PERMISSIONS.USERS_DELETE);

  return (
    <Tooltip content={canDelete ? undefined : "삭제 권한이 없습니다"}>
      <Button variant="destructive" disabled={!canDelete}>
        삭제
      </Button>
    </Tooltip>
  );
}
```

> **주의: 프론트 게이팅은 UX용이지 보안 경계가 아닙니다.** 실제 권한 강제는 항상 백엔드 `Depends(require_*)`가 책임집니다. 프론트는 노출을 정리할 뿐, 우회 가능하다는 전제로 백엔드를 신뢰합니다.

---

## 4. 권한 추가 절차 (체크리스트)

새 권한을 추가할 때는 아래 순서를 그대로 따릅니다. **이 문서 갱신까지가 1세트입니다.**

1. **백엔드 상수 추가** — `app/core/permissions.py`에 새 상수 정의
   ```python
   AGENTS_RUN = "agents:run"
   ```
   `ALL_PERMISSIONS`(또는 권한 레지스트리)에도 코드+설명을 등록.

2. **DEFAULT_ROLES 매핑** — 어떤 롤에 줄지 결정해 `DEFAULT_ROLES`에 반영
   (예: `super_admin`/`admin`에만 부여, `user`에서는 제외).

3. **seed 재실행(멱등)** — `services/seed.py`의 seed를 다시 실행.
   seed는 멱등(idempotent)이므로 기존 데이터 손상 없이 누락된 `permissions`/`role_permissions` 행만 추가됩니다. 앱 부팅 시 자동 실행됩니다.

4. **프론트 상수 동기화** — `src/lib/auth/permissions.ts`의 `PERMISSIONS`에 동일 코드 추가
   ```ts
   export const PERMISSIONS = {
     // ...
     AGENTS_RUN: "agents:run",
   } as const;
   ```
   백엔드와 문자열이 **정확히 일치**해야 합니다(오타 = 항상 false).

5. **이 문서(`docs/PERMISSIONS.md`) 갱신** — 2절의 권한 코드 표에 새 행(설명 + 롤별 부여 여부)을 추가.

> 권한 코드는 한 번 배포되면 클라이언트/문서/seed에 퍼지므로, **이름을 바꾸지 말고 새로 추가**하는 것을 원칙으로 합니다. 폐기할 때도 표에 "(deprecated)"로 남겨 추적성을 유지하세요.

---

## 5. 파일 위치 맵 (File Map)

권한 시스템의 소스가 흩어지지 않도록, 관련 파일을 한눈에 정리합니다.
(아래 파일들은 병렬로 구축 중이며, 경로는 구현 계약서에서 정한 의도된 위치입니다.)

### 백엔드 (`backend/`)

| 파일 | 역할 |
|---|---|
| `app/core/permissions.py` | **소스 오브 트루스.** 권한 상수, `ALL_PERMISSIONS`, `DEFAULT_ROLES`(super_admin/admin/user 매핑), `_ROLE_RANK`. |
| `app/core/deps.py` | `get_current_user`, `require_permission`, `require_any_permission`, `require_role_min`, `collect_user_permissions`. |
| `app/core/security.py` | JWT 인코드/디코드(세션 토큰). |
| `app/services/seed.py` | permissions/roles/role_permissions 멱등 seed + 최초 super_admin 처리. |

### 프론트엔드 (`src/`)

| 파일 | 역할 |
|---|---|
| `src/lib/auth/permissions.ts` | 프론트 권한/롤 상수(`PERMISSIONS`). 백엔드와 수동 동기화 대상. |
| `src/hooks/use-permissions.ts` | `usePermissions()` → `has` / `hasAny` / `hasAll`. |
| `src/components/permissions/perm-gate.tsx` | `<PermGate require={...} fallback={...}>` 게이트 컴포넌트. |
| `src/app/(app)/providers/` (user-provider) | `GET /auth/me`로 현재 사용자 + 평탄화 권한 로드 → 컨텍스트 제공. |

### 권한이 흐르는 경로 (요약)

```
[백엔드] permissions.py(상수·DEFAULT_ROLES)
   └→ seed.py 가 DB(roles/permissions/role_permissions)에 멱등 적재
        └→ 로그인 후 GET /auth/me 가 collect_user_permissions 로 권한 평탄화
             └→ [프론트] user-provider 컨텍스트
                  └→ usePermissions() / <PermGate> 가 화면 노출 제어
   (※ 실제 강제는 백엔드 Depends(require_*) — 프론트는 UX 정리용)
```
