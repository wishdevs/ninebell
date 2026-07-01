"""옴니솔 메뉴 스키마 — 메뉴ID ↔ 딥링크 ↔ 상세 service_url ↔ 필요 사용자유형.

각 메뉴는 특정 **사용자유형(인사/회계)** 컨텍스트에서만 접근 가능하다(사용자유형 전환이
모듈 접근을 부여). 그리드 수집 메뉴는 디테일 transport URL 을 함께 들고 있어야
$.ajax 병렬 수집이 가능하다(collection-strategies §함수호출방식).

이 맵이 있으면 patterns/navigator 가 문자열을 흩뿌리지 않고 스키마 하나로 진입·수집한다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 사용자유형 정규 라벨(auth.switch_user_type 의 target 과 정렬).
USER_TYPE_HR = "인사"  # 인사사용자(예외) — IM(재고) 모듈
USER_TYPE_ACCT = "회계"  # 회계사용자(예외) — FI(재무회계) 모듈
_VALID_USER_TYPES = frozenset({USER_TYPE_HR, USER_TYPE_ACCT})


@dataclass(frozen=True)
class MenuSchema:
    """단일 옴니솔 메뉴의 진입/수집 스키마(불변).

    key            nbkit 내부 식별자.
    menu_id        더존 메뉴 ID(예: 'IMIIRM00700_X20616').
    deeplink       base 에 붙일 진입 경로(예: '/IM/IMIIRM00700_X20616').
    label          사람이 읽는 메뉴명(로그/진행 이벤트 표시).
    user_type      진입에 필요한 사용자유형('인사'|'회계').
    grids_expected 진입 성공 판정용 최소 그리드 수(1 이상).
    detail_service_url  마스터-디테일 수집 시 디테일 transport read URL(없으면 None).
    master_id_field     디테일 조회 파라미터가 되는 마스터 행 키(없으면 None).
    """

    key: str
    menu_id: str
    deeplink: str
    label: str
    user_type: str
    grids_expected: int = 1
    detail_service_url: str | None = None
    master_id_field: str | None = None


# ── 검증된 메뉴 스키마 ─────────────────────────────────────────────────────────
BOM_COLLECTION = MenuSchema(
    key="bom-collection",
    menu_id="IMIIRM00700_X20616",
    deeplink="/IM/IMIIRM00700_X20616",
    label="프로젝트BOM불출요청처리[나인벨]",
    user_type=USER_TYPE_HR,
    grids_expected=2,  # 마스터 + 디테일
    detail_service_url="/api/IM/Imiirm00700_X20616_Service/imiirm00700_x20616_list_dtl",
    master_id_field="INVTRX_RSV_NO",
)

EXPENSE_CARD = MenuSchema(
    key="expense-card",
    menu_id="GLDDOC00300",
    deeplink="/FI/GLDDOC00300",
    label="결의서입력",
    user_type=USER_TYPE_ACCT,
    grids_expected=3,  # 마스터 + 디테일 + 항목
    detail_service_url=None,  # 쓰기 플로우(수집 아님)
    master_id_field=None,
)

MENU_MAP: dict[str, MenuSchema] = {
    BOM_COLLECTION.key: BOM_COLLECTION,
    EXPENSE_CARD.key: EXPENSE_CARD,
}


def get_menu(key: str) -> MenuSchema:
    """key 로 메뉴 스키마 조회. 없으면 KeyError(명확 실패)."""
    return MENU_MAP[key]


def deeplink_for(schema: MenuSchema, base: str) -> str:
    """base + deeplink 절대 URL. 예: 'https://erp...'+'/IM/...'."""
    return f"{base.rstrip('/')}{schema.deeplink}"


def is_valid_user_type(user_type: str) -> bool:
    """사용자유형이 정규 라벨('인사'|'회계')인지."""
    return user_type in _VALID_USER_TYPES
