"""권한 코드 + 기본 롤 정의 (ax `core/permissions.py` 이식, 단일 테넌트로 단순화).

권한 코드 컨벤션: ``<resource>:<action>`` (ax 의 ``system:``/``org:`` 스코프 분리 제거).
권한 추가 절차: (1) 여기 상수 추가 → (2) ``ALL_PERMISSIONS`` 등록 →
(3) ``DEFAULT_ROLES`` 매핑 → (4) seed 재실행 → (5) 프론트 상수 동기화.
docs/PERMISSIONS.md 참조.
"""

from __future__ import annotations

from typing import Final

# ---- 권한 코드 -------------------------------------------------------------

USERS_READ: Final = "users:read"
USERS_WRITE: Final = "users:write"
USERS_DELETE: Final = "users:delete"

ROLES_READ: Final = "roles:read"
ROLES_ASSIGN: Final = "roles:assign"

AGENTS_READ: Final = "agents:read"
AGENTS_WRITE: Final = "agents:write"
AGENTS_DELETE: Final = "agents:delete"

LOGS_READ: Final = "logs:read"


ALL_PERMISSIONS: Final[dict[str, str]] = {
    USERS_READ: "사용자 목록 조회",
    USERS_WRITE: "사용자 생성/수정(상태 변경 등)",
    USERS_DELETE: "사용자 삭제",
    ROLES_READ: "롤과 권한 조회",
    ROLES_ASSIGN: "사용자에게 롤 부여/변경",
    AGENTS_READ: "에이전트 조회",
    AGENTS_WRITE: "에이전트 생성/수정",
    AGENTS_DELETE: "에이전트 삭제",
    LOGS_READ: "접속 로그 조회",
}


# ---- 롤 ---------------------------------------------------------------------

ROLE_SUPER_ADMIN: Final = "super_admin"
ROLE_ADMIN: Final = "admin"
ROLE_USER: Final = "user"

# 역할 랭크 — require_role_min 계층 비교용. 클수록 강한 권한.
ROLE_RANK: Final[dict[str, int]] = {
    ROLE_USER: 1,
    ROLE_ADMIN: 2,
    ROLE_SUPER_ADMIN: 3,
}

_ALL_CODES: Final[tuple[str, ...]] = tuple(ALL_PERMISSIONS)

# (code) -> (표시명, 설명, 권한코드 튜플)
# super_admin 과 admin 은 현재 동일 권한이지만 **별도 행/소스로 분리** 하여
# 향후 디버전스를 무마이그레이션으로 가능하게 한다.
DEFAULT_ROLES: Final[dict[str, tuple[str, str, tuple[str, ...]]]] = {
    ROLE_SUPER_ADMIN: (
        "최고관리자",
        "전체 권한 — 시스템 최상위 관리자",
        _ALL_CODES,
    ),
    ROLE_ADMIN: (
        "관리자",
        "전체 권한 — 현재 super_admin 과 동일하나 소스/DB 에서 분리(향후 확장 대비)",
        _ALL_CODES,
    ),
    ROLE_USER: (
        "사용자",
        "에이전트 읽기 전용 — 사용자/로그 관리 불가",
        (AGENTS_READ,),
    ),
}


def role_rank(code: str | None) -> int:
    """롤 코드의 랭크. 알 수 없는 롤은 0(권한 없음)."""
    if code is None:
        return 0
    return ROLE_RANK.get(code, 0)
