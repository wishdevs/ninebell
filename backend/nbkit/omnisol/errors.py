"""옴니솔 도메인 예외 계층.

프리미티브(browser/*)는 실패를 ``False``/``None`` 으로 돌려주고, omnisol/patterns 계층이
그것을 **명확한 도메인 오류**로 승격한다. 이렇게 하면 상위(엔진/라우터)가 사용자에게
읽을 수 있는 메시지로 분기할 수 있다(예: 권한 없음 → 90초 헛돌지 않고 즉시 실패).
"""

from __future__ import annotations


class OmnisolError(RuntimeError):
    """모든 옴니솔 자동화 오류의 최상위."""


class AuthError(OmnisolError):
    """로그인 실패(자격증명 불일치·폼 미소멸 등)."""


class UserTypeError(OmnisolError):
    """사용자 유형(인사/회계) 전환 실패 — 실클릭 반영 안 됨 등."""


class MenuError(OmnisolError):
    """메뉴 진입 실패 — 권한 없음 팝업·그리드 미로드 등."""


class GridError(OmnisolError):
    """그리드 수집 실패 — 조회 미응답·그리드 인스턴스 접근 불가 등."""


class PopupError(OmnisolError):
    """모달/팝업 상호작용 실패 — 팝업 미오픈·적용 미반영 등."""


# 기존 backend/app/erp 의 명칭과의 친숙성을 위한 별칭(동일 의미).
ErpAuthError = AuthError
