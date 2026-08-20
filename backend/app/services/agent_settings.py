"""에이전트별 세부설정 — 선언적 스키마(코드 단일 소스) + 저장값 오버레이/검증.

설정 항목의 정의(키·라벨·타입·기본값·범위)는 여기 AGENT_SETTINGS_SCHEMA 가 유일
소스이고, DB(agents.settings JSON)에는 관리자가 저장한 값만 담는다. 에이전트가
20개로 늘어도 이 딕셔너리에 SettingDef 목록을 추가하는 것으로 확장한다.

- effective_settings: 스키마 기본값 위에 저장값을 덮어 실효값을 만든다(미지 키 무시).
- validate_settings: 관리자 PATCH 입력을 스키마로 검증한다(위반 시 ValueError 한국어).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# 전표유형 실측 카탈로그(62종) — 경량 상수 모듈에서 직접 import 한다(steps 경유 금지:
# steps 는 nbkit 등 무거운 브라우저 의존을 끌고 온다).
from app.agents.voucher_receivable.docu_types import DOCU_TYPE_CATALOG


@dataclass(frozen=True)
class SettingDef:
    key: str
    label: str
    type: str  # 'number' (향후 'string' | 'boolean' 확장)
    default: int | str | bool
    description: str
    min: int | None = None
    max: int | None = None
    unit: str | None = None


# ── 차량종류별 기준연비(동적 목록) ────────────────────────────────────────────
# 출장(국내/자차) 유류비 계산의 차량종류는 **관리자가 추가/삭제하는 목록**이다(고정 4종 아님).
# 각 행 = {id(안정 식별자), label(표시명), kmPerL(기준연비)}. id 는 실행 전 폼이 제출하는 값이라
# 라벨을 바꿔도 진행 중 선택이 깨지지 않게 안정적으로 유지한다(신규 추가 시 프론트가 생성).
# ⚠ 차량종류는 ERP 로 전송되지 않는다 — 오직 유류비 금액(km ÷ kmPerL × 단가) 계산 조회용이다.
FUEL_CLASSES_KEY = "fuel_classes"
FUEL_UNIT_PRICE_KEY = "fuel_unit_price"
MAX_FUEL_CLASSES = 20

DEFAULT_FUEL_CLASSES: list[dict] = [
    {"id": "under1000", "label": "1,000cc 미만", "kmPerL": 14},
    {"id": "under1600", "label": "1,600cc 미만", "kmPerL": 9},
    {"id": "under2000", "label": "2,000cc 미만", "kmPerL": 7},
    {"id": "over2000", "label": "2,000cc 이상", "kmPerL": 6},
]


def _valid_fuel_class(row: object) -> dict | None:
    """한 차량종류 행 검증 → 정규화 dict{id,label,kmPerL} | None(형식 오류).

    id/label 은 비어있지 않은 문자열, kmPerL 은 1~100 정수. bool 은 int 서브클래스라 배제.
    """
    if not isinstance(row, dict):
        return None
    cid = str(row.get("id") or "").strip()
    label = str(row.get("label") or "").strip()
    km = row.get("kmPerL")
    if not cid or not label:
        return None
    if isinstance(km, bool) or not isinstance(km, int) or not (1 <= km <= 100):
        return None
    return {"id": cid, "label": label, "kmPerL": km}


def _validate_fuel_classes(value: object) -> list[dict]:
    """관리자 입력 fuel_classes 목록 검증 → 정규화 리스트. 위반 시 ValueError(한국어).

    최소 1행·최대 MAX_FUEL_CLASSES, id 중복 금지, 각 행은 라벨+연비(1~100) 필수.
    """
    if not isinstance(value, list) or not value:
        raise ValueError("차량종류를 최소 1개 이상 등록하세요.")
    if len(value) > MAX_FUEL_CLASSES:
        raise ValueError(f"차량종류는 최대 {MAX_FUEL_CLASSES}개까지 등록할 수 있습니다.")
    out: list[dict] = []
    seen: set[str] = set()
    for i, row in enumerate(value):
        norm = _valid_fuel_class(row)
        if norm is None:
            raise ValueError(f"{i + 1}번째 차량종류의 이름·기준연비(1~100 정수)를 확인하세요.")
        if norm["id"] in seen:
            raise ValueError(f"차량종류 식별자가 중복됩니다: {norm['id']}")
        seen.add(norm["id"])
        out.append(norm)
    return out


def fuel_classes_for(stored: dict | None) -> list[dict]:
    """저장된 차량종류 목록(유효하면) 또는 기본 4종. 실효 설정·직렬화 공용."""
    raw = (stored or {}).get(FUEL_CLASSES_KEY)
    try:
        return _validate_fuel_classes(raw)
    except ValueError:
        return [dict(c) for c in DEFAULT_FUEL_CLASSES]


# ── 메뉴 필터 항목(동적 목록) ────────────────────────────────────────────────
# 유형별 전표조회 승인(voucher-by-type)의 메뉴(MENU_NM) 필터 마스터 목록 — **관리자가
# 추가/삭제**한다(fuel_classes 와 동일 패턴). 각 행 = {id(안정 식별자), label(ERP 메뉴 표시명),
# defaultSelected(실행 전 폼 기본 선택 여부)}. 실행별 실제 필터는 폼이 이 목록에서 골라
# params.voucher.menu_filters(라벨 목록)로 보낸다 — ERP 대조 값은 label 이다.
MENU_ITEMS_KEY = "menu_items"
# 실효 설정 전용 읽기 키 — 전표유형 실측 카탈로그(저장/PATCH 대상 아님).
DOCU_TYPE_CHOICES_KEY = "docu_type_choices"
MAX_MENU_ITEMS = 20

DEFAULT_MENU_ITEMS: list[dict] = [
    {"id": "sales-entry", "label": "매출등록", "defaultSelected": True},
    {"id": "sales-cancel", "label": "매출취소", "defaultSelected": True},
    {"id": "export-cost", "label": "수출비용입력[나인벨]", "defaultSelected": False},
]


def _valid_menu_item(row: object) -> dict | None:
    """한 메뉴 항목 검증 → 정규화 dict{id,label,defaultSelected} | None(형식 오류).

    id/label 은 비어있지 않은 문자열, defaultSelected 는 bool(누락 시 False).
    """
    if not isinstance(row, dict):
        return None
    mid = str(row.get("id") or "").strip()
    label = str(row.get("label") or "").strip()
    selected = row.get("defaultSelected", False)
    if not mid or not label:
        return None
    if not isinstance(selected, bool):
        return None
    return {"id": mid, "label": label, "defaultSelected": selected}


def _validate_menu_items(value: object) -> list[dict]:
    """관리자 입력 menu_items 목록 검증 → 정규화 리스트. 위반 시 ValueError(한국어).

    최소 1행·최대 MAX_MENU_ITEMS, id 중복 금지, 각 행은 id+라벨 필수(defaultSelected 는 bool).
    """
    if not isinstance(value, list) or not value:
        raise ValueError("메뉴 항목을 최소 1개 이상 등록하세요.")
    if len(value) > MAX_MENU_ITEMS:
        raise ValueError(f"메뉴 항목은 최대 {MAX_MENU_ITEMS}개까지 등록할 수 있습니다.")
    out: list[dict] = []
    seen: set[str] = set()
    for i, row in enumerate(value):
        norm = _valid_menu_item(row)
        if norm is None:
            raise ValueError(f"{i + 1}번째 메뉴 항목의 식별자·이름(기본선택은 불리언)을 확인하세요.")
        if norm["id"] in seen:
            raise ValueError(f"메뉴 항목 식별자가 중복됩니다: {norm['id']}")
        seen.add(norm["id"])
        out.append(norm)
    return out


def menu_items_for(stored: dict | None) -> list[dict]:
    """저장된 메뉴 항목 목록(유효하면) 또는 기본 3종. 실효 설정·직렬화 공용."""
    raw = (stored or {}).get(MENU_ITEMS_KEY)
    try:
        return _validate_menu_items(raw)
    except ValueError:
        return [dict(m) for m in DEFAULT_MENU_ITEMS]


# 에이전트 id → 설정 항목 정의 목록. 스키마가 없는 에이전트는 설정 기능 자체가 없다.
AGENT_SETTINGS_SCHEMA: dict[str, list[SettingDef]] = {
    "corporate-card": [
        SettingDef(
            key="acct_cutoff_day",
            label="회계시점 결정일",
            type="number",
            default=9,  # 현행 동작(10일 미만=전월)과 동치 — N일까지 전월, N+1일부터 당월.
            min=1,
            max=28,
            unit="일",
            description=(
                "이 날까지는 전월 회계월로, 다음 날부터는 당월로 처리합니다. "
                "예: 4 → 4일까지 전월, 5일부터 당월."
            ),
        ),
    ],
    # trip-domestic: 기준연비는 동적 목록(fuel_classes, 아래 별도 처리)이고, 여기 스칼라 스키마엔
    # 기준단가만 둔다. 차량종류 추가/삭제는 관리 화면의 전용 에디터가 담당한다.
    "trip-domestic": [
        SettingDef(
            key="fuel_unit_price",
            label="기준단가",
            type="number",
            default=2000,
            min=100,
            max=100000,
            unit="원/L",
            description="유류비 지원 금액 = 주행거리 ÷ 기준연비 × 기준단가(원 단위 반올림).",
        ),
    ],
    # voucher-by-type: 스칼라 설정은 없고 메뉴 항목(동적 목록, 아래 별도 처리)만 갖는다 —
    # 빈 스키마([])를 명시해 settings_schema_dicts 가 None 이 아닌 [] 를 돌려주고,
    # serialize_agent 가 settings(menu_items 포함)를 응답에 포함하게 한다.
    "voucher-by-type": [],
}

# 차량종류(동적 목록) 설정을 갖는 에이전트 — 실효 설정에 fuel_classes 를 포함하고 PATCH 에서
# fuel_classes 목록 입력을 허용한다. 현재는 출장(국내/자차)만.
_AGENTS_WITH_FUEL_CLASSES: frozenset[str] = frozenset({"trip-domestic"})

# 메뉴 항목(동적 목록) 설정을 갖는 에이전트 — 실효 설정에 menu_items 를 포함하고 PATCH 에서
# menu_items 목록 입력을 허용한다. ⚠ **에이전트 id** 기준(workflow id 아님).
_AGENTS_WITH_MENU_ITEMS: frozenset[str] = frozenset({"voucher-by-type"})


def settings_schema_dicts(agent_id: str) -> list[dict] | None:
    """직렬화용 스키마(camelCase 키: key/label/type/default/min/max/unit/description).

    스키마가 없는 에이전트는 None(응답에 미포함 — 옵셔널 컨벤션).
    """
    defs = AGENT_SETTINGS_SCHEMA.get(agent_id)
    if defs is None:
        return None
    return [asdict(d) for d in defs]


def effective_settings(agent_id: str, stored: dict | None) -> dict:
    """스키마 기본값 위에 저장값을 오버레이한 실효 설정(스키마에 없는 키는 무시).

    차량종류 목록(fuel_classes)을 갖는 에이전트는 그 목록도 실효값에 포함한다(저장값 또는 기본 4종).
    스키마도 없고 fuel_classes 도 없는 에이전트는 빈 dict.
    """
    defs = AGENT_SETTINGS_SCHEMA.get(agent_id)
    stored = stored or {}
    out: dict = {}
    if defs:
        out = {d.key: stored.get(d.key, d.default) for d in defs}
    if agent_id in _AGENTS_WITH_FUEL_CLASSES:
        out[FUEL_CLASSES_KEY] = fuel_classes_for(stored)
    if agent_id in _AGENTS_WITH_MENU_ITEMS:
        out[MENU_ITEMS_KEY] = menu_items_for(stored)
        # 전표유형 선택지(읽기 전용, 2026-08-20 실측 62종) — 프론트 실행 전 폼이 이 목록으로
        # 렌더한다. 코드 상수가 유일 소스라 **저장 불가**(validate_settings 가 미지 키로 거부).
        out[DOCU_TYPE_CHOICES_KEY] = [
            {"code": code, "label": label} for code, label in DOCU_TYPE_CATALOG
        ]
    return out


def validate_settings(agent_id: str, incoming: dict) -> dict:
    """관리자 PATCH 입력 검증 — 키∈스키마·타입·min/max. 위반 시 ValueError(한국어).

    통과한 키만 담은 새 dict 를 반환한다(원본 불변).
    """
    defs = {d.key: d for d in AGENT_SETTINGS_SCHEMA.get(agent_id, [])}
    has_fuel_classes = agent_id in _AGENTS_WITH_FUEL_CLASSES
    has_menu_items = agent_id in _AGENTS_WITH_MENU_ITEMS
    if not defs and not has_fuel_classes and not has_menu_items:
        raise ValueError("이 에이전트는 설정 항목이 없습니다.")
    validated: dict = {}
    for key, value in incoming.items():
        # 차량종류(동적 목록) — 스칼라 스키마 밖의 특수 항목. 리스트 검증 후 정규화 저장.
        if has_fuel_classes and key == FUEL_CLASSES_KEY:
            validated[key] = _validate_fuel_classes(value)
            continue
        # 메뉴 항목(동적 목록) — voucher-by-type 의 메뉴 필터 마스터 목록(동일 패턴).
        if has_menu_items and key == MENU_ITEMS_KEY:
            validated[key] = _validate_menu_items(value)
            continue
        d = defs.get(key)
        if d is None:
            raise ValueError(f"알 수 없는 설정 항목입니다: {key}")
        if d.type == "number":
            # bool 은 int 의 서브클래스라 명시 배제(True 가 1로 저장되는 사고 방지).
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"'{d.label}' 값은 정수여야 합니다.")
            if d.min is not None and value < d.min:
                raise ValueError(f"'{d.label}' 값은 {d.min} 이상이어야 합니다.")
            if d.max is not None and value > d.max:
                raise ValueError(f"'{d.label}' 값은 {d.max} 이하여야 합니다.")
        else:  # 향후 'string' | 'boolean' 타입 추가 시 여기서 분기.
            raise ValueError(f"지원하지 않는 설정 타입입니다: {d.type}")
        validated[key] = value
    return validated
