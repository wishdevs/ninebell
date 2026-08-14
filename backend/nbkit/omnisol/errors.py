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


class LoginPageError(AuthError):
    """로그인 페이지 미로드 — 옴니솔 점검·SPA 지연 등 **인프라성** 실패.

    자격증명 실패와 구분하기 위한 서브클래스. AuthError 를 상속하므로 기존 nbkit
    소비자(에이전트 로그인 노드 등)의 ``except AuthError`` 에는 종전대로 잡히고,
    backend 로그인 래퍼(app/erp/login.py)만 이를 따로 잡아 401(시도제한 카운트)이
    아닌 502 인프라 오류 경로로 승격한다."""


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
