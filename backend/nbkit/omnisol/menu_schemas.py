"""옴니솔 메뉴 스키마 — 메뉴ID ↔ 딥링크 ↔ 상세 service_url ↔ 필요 사용자유형.

각 메뉴는 특정 **사용자유형(인사/회계)** 컨텍스트에서만 접근 가능하다(사용자유형 전환이
모듈 접근을 부여). 그리드 수집 메뉴는 디테일 transport URL 을 함께 들고 있어야
$.ajax 병렬 수집이 가능하다(collection-strategies §함수호출방식).

이 맵이 있으면 patterns/navigator 가 문자열을 흩뿌리지 않고 스키마 하나로 진입·수집한다.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── 사용자유형 별칭 ────────────────────────────────────────────────────────────
# ⚠ 이 집합은 **MenuSchema.user_type 값 검증**(오타 방지)용일 뿐이다. 런타임 전환
# (auth.switch_user_type)은 이 집합을 전혀 참조하지 않고 ERP 가 실제로 제공하는 옵션 목록으로
# 별칭을 해석하므로, **여기 없는 유형도 전환 자체는 정상 동작한다**. 즉 유형이 추가돼도
# 새 메뉴 스키마를 등록할 때만 register_user_type() 한 줄이면 되고, 고정 frozenset 을
# 다시 쓸 일이 없다.
_VALID_USER_TYPES: set[str] = set()


def register_user_type(alias: str) -> str:
    """사용자유형 별칭을 검증 집합에 등록하고 그대로 돌려준다(상수 정의와 나란히 쓴다)."""
    _VALID_USER_TYPES.add(alias)
    return alias


def known_user_types() -> frozenset[str]:
    """현재 등록된 사용자유형 별칭 스냅샷(로그·진단용, 불변 사본)."""
    return frozenset(_VALID_USER_TYPES)


# 별칭은 ERP 옵션 원문이 아니라, 옵션 목록과 대조해 유일한 라벨로 해석되는 짧은 키다
# (auth.resolve_user_type_label — 완전일치 → 접두일치 → 포함일치, 모호하면 실패).
USER_TYPE_HR = register_user_type("인사")  # → '인사사용자(예외)' — IM(재고) 모듈
USER_TYPE_ACCT = register_user_type("회계")  # → '회계사용자(예외)' — FI(재무회계) 모듈
# 2026-08-01 라이브 실측으로 확인된 3번째 유형. 라벨에 '사용자' 접미사가 없다('SCM-구매') —
# 종전 '○○사용자' 가정이 깨진 지점이며, 이제 어떤 형태의 라벨이든 옵션 목록으로 해석한다.
USER_TYPE_SCM = register_user_type("SCM")  # → 'SCM-구매'


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

# 전표조회승인(총계정원장>전표관리>전표조회승인) — voucher_receivable 라이브 프로브로 확정
# (2026-07-20). 결의서입력과 달리 **조회+결재** 아키타입: 마스터(조회결과)+디테일(계정정보) 2그리드.
VOUCHER_RECEIVABLE = MenuSchema(
    key="voucher-receivable",
    menu_id="GLDDOC00700",
    deeplink="/FI/GLDDOC00700",
    label="전표조회승인",
    user_type=USER_TYPE_ACCT,
    grids_expected=2,  # 마스터(조회결과) + 디테일(계정정보)
    detail_service_url=None,  # 조회 폼 기반(수집 아님)
    master_id_field=None,
)

# 프로젝트BOM구매요청[나인벨](SCM-구매) — purchase_order 라이브 읽기 프로브로 확정(2026-08-13).
# 딥링크 3종 중 화면 ①. navigate_menu 무수정 진입 실측(grids_required=1 — 화면의 플랫
# .dews-ui-grid 2개 기준. BOM 본체는 .dews-ui-treegrid 로 별개 위젯이라 카운트 대상 아님).
PURCHASE_ORDER_BOM = MenuSchema(
    key="purchase-order-bom",
    menu_id="PUOPRQ00200_X20616",
    deeplink="/PU/PUOPRQ00200_X20616",
    label="프로젝트BOM구매요청[나인벨]",
    user_type=USER_TYPE_SCM,
    grids_expected=1,
    detail_service_url=None,  # 읽기 그래프(Phase A) — 트리그리드 루프 리더로 수집.
    master_id_field=None,
)

# 구매요청처리[나인벨] — 화면 ②(셀프결재 상신). 랜딩 실측(2026-08-25): .dews-ui-grid 5개(마스터+탭4).
PURCHASE_REQ_PROCESS = MenuSchema(
    key="purchase-req-process",
    menu_id="PUOPRQ00300_X20616",
    deeplink="/PU/PUOPRQ00300_X20616",
    label="구매요청처리[나인벨]",
    user_type=USER_TYPE_SCM,
    grids_expected=2,
    detail_service_url=None,
    master_id_field=None,
)

MENU_MAP: dict[str, MenuSchema] = {
    BOM_COLLECTION.key: BOM_COLLECTION,
    EXPENSE_CARD.key: EXPENSE_CARD,
    VOUCHER_RECEIVABLE.key: VOUCHER_RECEIVABLE,
    PURCHASE_ORDER_BOM.key: PURCHASE_ORDER_BOM,
    PURCHASE_REQ_PROCESS.key: PURCHASE_REQ_PROCESS,
}


def get_menu(key: str) -> MenuSchema:
    """key 로 메뉴 스키마 조회. 없으면 KeyError(명확 실패)."""
    return MENU_MAP[key]


def deeplink_for(schema: MenuSchema, base: str) -> str:
    """base + deeplink 절대 URL. 예: 'https://erp...'+'/IM/...'."""
    return f"{base.rstrip('/')}{schema.deeplink}"


def is_valid_user_type(user_type: str) -> bool:
    """등록된 사용자유형 별칭인지(스키마 값 검증 전용 — 런타임 전환 가능 여부와 무관)."""
    return user_type in _VALID_USER_TYPES
