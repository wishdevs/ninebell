"""에이전트별 세부설정 — 선언적 스키마(코드 단일 소스) + 저장값 오버레이/검증.

설정 항목의 정의(키·라벨·타입·기본값·범위)는 여기 AGENT_SETTINGS_SCHEMA 가 유일
소스이고, DB(agents.settings JSON)에는 관리자가 저장한 값만 담는다. 에이전트가
20개로 늘어도 이 딕셔너리에 SettingDef 목록을 추가하는 것으로 확장한다.

- effective_settings: 스키마 기본값 위에 저장값을 덮어 실효값을 만든다(미지 키 무시).
- validate_settings: 관리자 PATCH 입력을 스키마로 검증한다(위반 시 ValueError 한국어).
"""

from __future__ import annotations

import copy
import re
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


# ── 발주 패턴 v2(발주그룹) ────────────────────────────────────────────────────
# 구매발주(purchase-order)의 발주 패턴 마스터 — **관리자가 추가/삭제/수정**한다.
# v2(2026-08-21): 단위 번호(unitNo)로 묶던 플랫 27행을 **발주그룹** object 로 교체했다.
# 그룹 1개 = 발주단위 1건이고, 그룹이 소속 모듈(규격)·납기 규칙·구매사유·예외 규칙을 소유한다.
# 매칭 1순위 키는 spec(규격, ITEM_SPEC_DC)이다 — name(품명, ITEM_NM)은 '제조2팀'처럼 한 장비
# 안에서도 중복돼 2순위/표시용이다(2026-08-13 실측). reason 의 'PJT DESC' 는 적용 시
# 프로젝트로 치환되는 자리표시자이고, exceptions 는 v1 의 참고 텍스트와 달리 계획서의 거래처
# 그룹 납기·거래처·비고 기본값으로 **실반영**된다(개별 수정이 항상 우선).
#
# 프론트 미러: src/lib/purchase/order-patterns.ts(타입·한도·관대 파서).
# ⚠ 아래 기본 9그룹 리터럴은 src/lib/purchase/order-patterns.default.json 과 **값이 완전히
#   같아야** 한다 — 배포 이미지에 src/ 가 없어 백엔드가 자체 리터럴을 들고 있고,
#   tests/test_fe_be_mirror_parity.py 가 그 JSON 을 읽어 재귀 비교로 드리프트를 감시한다.
ORDER_PATTERNS_KEY = "order_patterns"
MAX_PATTERN_GROUPS = 40
MAX_GROUP_MODULES = 50
MAX_GROUP_EXCEPTIONS = 20
MAX_OFFSET_WEEKS = 52

# 그룹 납기의 기준일 3종 — 계획서 상단에서 한 번 입력받는 값이다.
BASE_DATE_KEYS: tuple[str, ...] = ("FRAME", "1공장", "3공장")
# 예외 전용 특수 기준 — 같은 발주단위 **가공품 그룹의 확정 납기**를 기준으로 삼는다
# (BUFFER 규칙 '그 외 가공품 납품일 일주일전'). 그룹 자체 납기(due)에는 쓸 수 없다.
PROCESSED_DUE_BASE = "가공품납기"
# 예외 대상 — 분류 일치 / 유효 거래처명 일치 / 분류 제외(그 분류만 빼고 전부).
EXCEPTION_SCOPE_KINDS: frozenset[str] = frozenset({"vendorClass", "vendor", "exceptClass"})
# 순환 차단 대상 분류 — 가공품 그룹이 자기 납기('가공품납기')를 기준으로 삼는 것을 막는다.
_PROCESSED_CLASS = "가공품"

DEFAULT_ORDER_PATTERNS: dict = {
    "groups": [
        {
            "id": "g1",
            "bundle": "EFEM",
            "name": "FRAME",
            "due": {"base": "FRAME", "offsetWeeks": 0},
            "reason": "PJT DESC EFEM FRAME",
            "modules": [
                {"id": "g1m1", "spec": "EFEM-Frame Assy", "name": "외주조립-F"},
            ],
            "exceptions": [
                {
                    "id": "g1x1",
                    "scope": {"kind": "exceptClass", "value": "판금품"},
                    "due": {"base": "FRAME", "offsetWeeks": 1},
                    "note": "직배송 판금품",
                },
                # 판금품은 직배송 — FRAME 당일(내장 기본 −리드타임에 밀리지 않게 명시).
                {
                    "id": "g1x2",
                    "scope": {"kind": "vendorClass", "value": "판금품"},
                    "due": {"base": "FRAME", "offsetWeeks": 0},
                },
            ],
        },
        {
            "id": "g2",
            "bundle": "EFEM",
            "name": "L Axis",
            "due": {"base": "FRAME", "offsetWeeks": 1},
            "reason": "PJT DESC EFEM L AXIS",
            "modules": [
                {"id": "g2m1", "spec": "EFEM-L Axis Assy", "name": "외주조립-L"},
            ],
            "exceptions": [
                {
                    "id": "g2x1",
                    "scope": {"kind": "exceptClass", "value": "가공품"},
                    "due": {"base": "FRAME", "offsetWeeks": 2},
                    "note": "직배송 가공품",
                },
                {"id": "g2x2", "scope": {"kind": "vendorClass", "value": "가공품"}, "note": "직배송 판금품"},
            ],
        },
        {
            "id": "g3",
            "bundle": "EFEM",
            "name": "1공장",
            "due": {"base": "1공장", "offsetWeeks": 0},
            "reason": "PJT DESC EFEM 1공장",
            "modules": [
                {"id": "g3m1", "spec": "EFEM-Electric Pannel Assy", "name": "외주조립-ELECTRIC PANNEL"},
                {"id": "g3m2", "spec": "EFEM-완제품 조립", "name": "제조1팀"},
                {"id": "g3m3", "spec": "EFEM-Frame 배선", "name": "전장-제조1팀"},
            ],
            "exceptions": [
                {
                    "id": "g3x1",
                    "scope": {"kind": "vendor", "value": "와이엔에스"},
                    "due": {"base": "FRAME", "offsetWeeks": 3},
                },
                {
                    "id": "g3x2",
                    "scope": {"kind": "vendorClass", "value": "판금품"},
                    "due": {"base": "FRAME", "offsetWeeks": 0},
                },
            ],
        },
        {
            "id": "g4",
            "bundle": "EFEM",
            "name": "3공장",
            "due": {"base": "3공장", "offsetWeeks": 0},
            "reason": "PJT DESC EFEM 3공장",
            "modules": [
                {"id": "g4m1", "spec": "EFEM-Interlock Assy", "name": "제조2팀"},
                {"id": "g4m2", "spec": "EFEM-R Axis Assy", "name": "제조2팀"},
                {"id": "g4m3", "spec": "EFEM-Regulator Box Assy", "name": "외주조립-명판"},
                {"id": "g4m4", "spec": "EFEM-Robot 후공정인계", "name": "제조2팀"},
                {"id": "g4m5", "spec": "EFEM-Switch Box Assy", "name": "외주조립-명판"},
                {"id": "g4m6", "spec": "EFEM-T Axis Assy", "name": "제조2팀"},
                {"id": "g4m7", "spec": "EFEM-Z Axis Assy", "name": "제조2팀"},
                {"id": "g4m8", "spec": "EFEM-Robot 배선", "name": "전장-제조2팀"},
            ],
            "exceptions": [],
        },
        {
            "id": "g5",
            "bundle": "PROCESS",
            "name": "FRAME",
            "due": {"base": "FRAME", "offsetWeeks": 0},
            "reason": "PJT DESC PROCESS FRAME",
            "modules": [
                {"id": "g5m1", "spec": "Process-Frame Assy", "name": "외주조립-F"},
            ],
            "exceptions": [
                {
                    "id": "g5x1",
                    "scope": {"kind": "exceptClass", "value": "판금품"},
                    "due": {"base": "FRAME", "offsetWeeks": 1},
                    "note": "직배송 판금품",
                },
                # 판금품은 직배송 — FRAME 당일(내장 기본 −리드타임에 밀리지 않게 명시).
                {
                    "id": "g5x2",
                    "scope": {"kind": "vendorClass", "value": "판금품"},
                    "due": {"base": "FRAME", "offsetWeeks": 0},
                },
            ],
        },
        {
            "id": "g6",
            "bundle": "PROCESS",
            "name": "L Axis",
            "due": {"base": "FRAME", "offsetWeeks": 1},
            "reason": "PJT DESC PROCESS L AXIS",
            "modules": [
                {"id": "g6m1", "spec": "Process-L Axis Assy", "name": "외주조립-L"},
            ],
            "exceptions": [
                {
                    "id": "g6x1",
                    "scope": {"kind": "exceptClass", "value": "가공품"},
                    "due": {"base": "FRAME", "offsetWeeks": 2},
                    "note": "직배송 가공품",
                },
                {"id": "g6x2", "scope": {"kind": "vendorClass", "value": "가공품"}, "note": "직배송 판금품"},
            ],
        },
        {
            "id": "g7",
            "bundle": "PROCESS",
            "name": "1공장",
            "due": {"base": "1공장", "offsetWeeks": 0},
            "reason": "PJT DESC PROCESS 1공장",
            "modules": [
                {"id": "g7m1", "spec": "Process-Electric Pannel Assy", "name": "외주조립-ELECTRIC PANNEL"},
                {"id": "g7m2", "spec": "Process-완제품 조립", "name": "제조1팀"},
                {"id": "g7m3", "spec": "Process-Frame 배선", "name": "전장-제조1팀"},
            ],
            "exceptions": [
                {
                    "id": "g7x1",
                    "scope": {"kind": "vendor", "value": "와이엔에스"},
                    "due": {"base": "FRAME", "offsetWeeks": 3},
                },
                {
                    "id": "g7x2",
                    "scope": {"kind": "vendorClass", "value": "판금품"},
                    "due": {"base": "FRAME", "offsetWeeks": 0},
                },
            ],
        },
        {
            "id": "g8",
            "bundle": "PROCESS",
            "name": "3공장",
            "due": {"base": "3공장", "offsetWeeks": 0},
            "reason": "PJT DESC PROCESS 3공장",
            "modules": [
                {"id": "g8m1", "spec": "Process-Flat Cable Assy", "name": "외주조립-FLAT"},
                {"id": "g8m2", "spec": "Process-Interlock Assy", "name": "제조2팀"},
                {"id": "g8m3", "spec": "Process-R Axis Assy", "name": "제조2팀"},
                {"id": "g8m4", "spec": "Process-Robot 후공정인계", "name": "제조2팀"},
                {"id": "g8m5", "spec": "Process-Switch & Regulator Box Assy", "name": "외주조립-명판"},
                {"id": "g8m6", "spec": "Process-T Axis Assy", "name": "제조2팀"},
                {"id": "g8m7", "spec": "Process-Z Axis Assy", "name": "제조2팀"},
                {"id": "g8m8", "spec": "Process-Robot 배선", "name": "전장-제조2팀"},
            ],
            "exceptions": [
                {
                    "id": "g8x1",
                    "scope": {"kind": "vendor", "value": "유트랙스"},
                    "due": {"base": "3공장", "offsetWeeks": 1},
                    "note": "하네스 업체로 직납",
                },
            ],
        },
        {
            "id": "g9",
            "bundle": "PROCESS",
            "name": "BUFFER MODULE",
            "due": {"base": "1공장", "offsetWeeks": 0},
            "reason": "PJT DESC BUFFER MODULE",
            "modules": [
                {"id": "g9m1", "spec": "Process-Buffer Assy", "name": "외주조립-BUFFER"},
            ],
            "exceptions": [
                {"id": "g9x1", "scope": {"kind": "vendorClass", "value": "가공품"}, "vendor": "한국메카트로닉스"},
                {
                    "id": "g9x2",
                    "scope": {"kind": "exceptClass", "value": "가공품"},
                    "due": {"base": "가공품납기", "offsetWeeks": 1},
                    "note": "직배송 한국메카",
                },
            ],
        },
    ]
}

# 발주 패턴 문자열 필드의 최대 길이 — 관리 화면 입력이 그대로 settings JSON 에 저장되므로
# 계층마다 상한을 둔다. 구매사유·비고는 여러 줄을 담아 넉넉하다.
_GROUP_LIMITS: dict[str, int] = {"id": 64, "bundle": 32, "name": 64, "reason": 200}
_MODULE_LIMITS: dict[str, int] = {"id": 64, "spec": 128, "name": 128}
_EXCEPTION_LIMITS: dict[str, int] = {"id": 64, "value": 64, "vendor": 64, "note": 200}


def _pattern_text(value: object, limit: int) -> str | None:
    """패턴의 문자열 필드 → 앞뒤 공백만 제거한 값. 문자열 아님/길이 초과면 None(행 오류).

    strip 만 하므로 구매사유·비고의 줄바꿈은 보존된다.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if len(text) <= limit else None


def _bundle_key(bundle: str) -> str:
    """발주묶음 비교 정규화 — 프론트 order-patterns.ts 의 bundleKey() 미러."""
    return bundle.strip().upper()


def _match_key(value: str) -> str:
    """규격 매칭 키 정규화 — 프론트 pattern.ts 의 norm() 미러(대소문자·연속 공백 흡수)."""
    return re.sub(r"\s+", " ", value.strip().lower())


def _spec_suffix(spec: str, bundle: str) -> str:
    """규격에서 발주묶음 접두('EFEM-'·'Process ')를 벗긴 나머지 — 접두가 없으면 규격 자체.

    ERP BOM 이 접두 없는 규격('T Axis Assy')을 주는 장비가 있어(2026-08-14 실측) 매칭이
    접미로도 떨어진다. 접두 판정은 대소문자를 무시하되, 잘라내는 길이는 원본 문자 수로
    센다(대문자화가 길이를 바꾸는 문자에 대한 방어).
    """
    text = spec.strip()
    head = bundle.strip()
    if not head:
        return text
    cut = len(head) + 1
    for sep in ("-", " "):
        if text[:cut].upper() == f"{head}{sep}".upper():
            return text[cut:].strip()
    return text


def _valid_due(raw: object, *, allow_processed: bool) -> dict | None:
    """납기 규칙 검증 → {'base','offsetWeeks'} | None(형식 오류).

    bool 은 int 서브클래스라 offsetWeeks 에서 명시 배제한다(True 가 1주로 저장되는 사고 방지).
    """
    if not isinstance(raw, dict):
        return None
    base = raw.get("base")
    if not isinstance(base, str):
        return None
    base = base.strip()
    allowed = set(BASE_DATE_KEYS) | ({PROCESSED_DUE_BASE} if allow_processed else set())
    if base not in allowed:
        return None
    weeks = raw.get("offsetWeeks")
    if isinstance(weeks, bool) or not isinstance(weeks, int):
        return None
    if not (0 <= weeks <= MAX_OFFSET_WEEKS):
        return None
    return {"base": base, "offsetWeeks": weeks}


def _due_hint(*, allow_processed: bool) -> str:
    """오류 메시지에 넣을 허용 기준일 목록."""
    keys = [*BASE_DATE_KEYS, PROCESSED_DUE_BASE] if allow_processed else list(BASE_DATE_KEYS)
    return "·".join(keys)


def _check_module(raw: object, where: str, fallback_id: str = "") -> dict:
    """한 모듈 행 검증 → 정규화 dict. 위반 시 ValueError(좌표 포함 한국어).

    fallback_id 가 있으면 식별자 누락을 그 값으로 메운다(관대 리더 전용 — 프론트 관대
    파서가 newPatternId 로 채우는 것과 같은 의미론).
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{where}의 형식을 확인하세요.")
    mid = _pattern_text(raw.get("id"), _MODULE_LIMITS["id"]) or fallback_id
    spec = _pattern_text(raw.get("spec"), _MODULE_LIMITS["spec"])
    name = _pattern_text(raw.get("name"), _MODULE_LIMITS["name"])
    if not mid or not spec or name is None:
        raise ValueError(
            f"{where}의 식별자·규격({_MODULE_LIMITS['spec']}자 이하)"
            f"·품명({_MODULE_LIMITS['name']}자 이하)을 확인하세요."
        )
    return {"id": mid, "spec": spec, "name": name}


def _check_exception(raw: object, where: str, fallback_id: str = "") -> dict:
    """한 예외 행 검증 → 정규화 dict. 위반 시 ValueError(좌표 포함 한국어).

    없는 선택 필드(due/vendor/note)는 **키 자체를 넣지 않는다** — 부재가 곧 '변경 없음'이라
    기본값 JSON·프론트 관대 파서와 같은 모양이 된다.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{where}의 형식을 확인하세요.")
    eid = _pattern_text(raw.get("id"), _EXCEPTION_LIMITS["id"]) or fallback_id
    scope = raw.get("scope")
    kind = scope.get("kind") if isinstance(scope, dict) else None
    value = _pattern_text(scope.get("value"), _EXCEPTION_LIMITS["value"]) if isinstance(scope, dict) else None
    if not eid or kind not in EXCEPTION_SCOPE_KINDS or not value:
        raise ValueError(
            f"{where}의 식별자·대상(분류/거래처/분류 제외)"
            f"·대상 값({_EXCEPTION_LIMITS['value']}자 이하)을 확인하세요."
        )
    vendor = _pattern_text(raw.get("vendor"), _EXCEPTION_LIMITS["vendor"])
    note = _pattern_text(raw.get("note"), _EXCEPTION_LIMITS["note"])
    if vendor is None:
        raise ValueError(f"{where}의 거래처는 {_EXCEPTION_LIMITS['vendor']}자 이하로 입력하세요.")
    if note is None:
        raise ValueError(f"{where}의 비고는 {_EXCEPTION_LIMITS['note']}자 이하로 입력하세요.")
    due = None
    if raw.get("due") is not None:
        due = _valid_due(raw.get("due"), allow_processed=True)
        if due is None:
            raise ValueError(
                f"{where}의 납기 기준일({_due_hint(allow_processed=True)})과 "
                f"주 전(0~{MAX_OFFSET_WEEKS} 정수)을 확인하세요."
            )
    if due is None and not vendor and not note:
        raise ValueError(f"{where}는 납기·거래처·비고 중 최소 하나를 지정해야 합니다.")
    # 순환 방지 ① 거래처를 대상으로 고른 예외가 그 거래처를 다시 바꾸면 자기참조가 된다.
    if kind == "vendor" and vendor:
        raise ValueError(f"{where} — 대상이 '거래처'인 예외에는 거래처 고정을 지정할 수 없습니다.")
    # 순환 방지 ② 가공품 그룹의 납기를 '가공품납기'(=자기 자신)로 잡으면 해석이 순환한다.
    if kind == "vendorClass" and value == _PROCESSED_CLASS and due and due["base"] == PROCESSED_DUE_BASE:
        raise ValueError(
            f"{where} — '{_PROCESSED_CLASS}' 분류 예외의 납기 기준은 "
            f"'{PROCESSED_DUE_BASE}'로 지정할 수 없습니다."
        )
    out: dict = {"id": eid, "scope": {"kind": kind, "value": value}}
    if due is not None:
        out["due"] = due
    if vendor:
        out["vendor"] = vendor
    if note:
        out["note"] = note
    return out


def _check_group(raw: object, where: str, *, fallback_id: str = "", lenient: bool = False) -> dict:
    """한 발주그룹 검증 → 정규화 dict. 위반 시 ValueError(좌표 포함 한국어).

    lenient=True 면 **행 단위** 오류(모듈·예외)는 그 행만 버리고 계속한다 — 그룹 자체가
    성립하지 않을 때(발주묶음·그룹명·납기 누락, 유효 모듈 0)만 예외를 올려 호출자가 그룹을
    통째로 드랍하게 한다. 프론트 normalizeGroup 과 같은 의미론이다.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{where}의 형식을 확인하세요.")
    gid = _pattern_text(raw.get("id"), _GROUP_LIMITS["id"]) or fallback_id
    bundle = _pattern_text(raw.get("bundle"), _GROUP_LIMITS["bundle"])
    name = _pattern_text(raw.get("name"), _GROUP_LIMITS["name"])
    reason = _pattern_text(raw.get("reason"), _GROUP_LIMITS["reason"])
    if not gid or not bundle or not name:
        raise ValueError(
            f"{where}의 식별자·발주묶음({_GROUP_LIMITS['bundle']}자 이하)"
            f"·그룹명({_GROUP_LIMITS['name']}자 이하)을 확인하세요."
        )
    if reason is None:
        raise ValueError(f"{where}의 구매사유는 {_GROUP_LIMITS['reason']}자 이하로 입력하세요.")
    due = _valid_due(raw.get("due"), allow_processed=False)
    if due is None:
        raise ValueError(
            f"{where}의 납기 기준일({_due_hint(allow_processed=False)})과 "
            f"주 전(0~{MAX_OFFSET_WEEKS} 정수)을 확인하세요."
        )

    raw_modules = raw.get("modules")
    if not isinstance(raw_modules, list) or not raw_modules:
        raise ValueError(f"{where}에 모듈을 최소 1개 이상 등록하세요.")
    if not lenient and len(raw_modules) > MAX_GROUP_MODULES:
        raise ValueError(f"{where}의 모듈은 최대 {MAX_GROUP_MODULES}개까지 등록할 수 있습니다.")
    modules: list[dict] = []
    for j, item in enumerate(raw_modules[:MAX_GROUP_MODULES]):
        try:
            modules.append(
                _check_module(item, f"{where}의 {j + 1}번째 모듈", f"_m{j + 1}" if lenient else "")
            )
        except ValueError:
            if not lenient:
                raise
    if not modules:
        raise ValueError(f"{where}에 모듈을 최소 1개 이상 등록하세요.")

    raw_exceptions = raw.get("exceptions")
    if raw_exceptions is None:
        raw_exceptions = []
    if not isinstance(raw_exceptions, list):
        if not lenient:
            raise ValueError(f"{where}의 예외 목록 형식을 확인하세요.")
        raw_exceptions = []
    if not lenient and len(raw_exceptions) > MAX_GROUP_EXCEPTIONS:
        raise ValueError(f"{where}의 예외는 최대 {MAX_GROUP_EXCEPTIONS}개까지 등록할 수 있습니다.")
    exceptions: list[dict] = []
    for k, item in enumerate(raw_exceptions[:MAX_GROUP_EXCEPTIONS]):
        try:
            exceptions.append(
                _check_exception(item, f"{where}의 {k + 1}번째 예외", f"_x{k + 1}" if lenient else "")
            )
        except ValueError:
            if not lenient:
                raise

    return {
        "id": gid,
        "bundle": bundle,
        "name": name,
        "due": due,
        "reason": reason,
        "modules": modules,
        "exceptions": exceptions,
    }


def _check_spec_collisions(groups: list[dict]) -> None:
    """같은 발주묶음 안의 규격 충돌 검사 — 매칭이 비결정이 되는 조합만 막는다.

    ① 정확 규격 중복은 그룹을 가리지 않고 거부한다(어느 그룹으로 묶일지 정할 수 없다).
    ② 접두를 뺀 접미 중복은 **다른 그룹끼리만** 거부한다 — 같은 그룹에 'EFEM-T Axis Assy'
       와 무접두 'T Axis Assy' 를 함께 등록하는 교정(접두 없는 BOM 대응)은 허용해야 한다.
    """
    exact: set[tuple[str, str]] = set()
    suffix_owner: dict[tuple[str, str], str] = {}
    for i, g in enumerate(groups):
        bundle_key = _bundle_key(g["bundle"])
        for j, module in enumerate(g["modules"]):
            where = f"{i + 1}번째 그룹의 {j + 1}번째 모듈"
            spec = module["spec"]
            exact_key = (bundle_key, _match_key(spec))
            if exact_key in exact:
                raise ValueError(
                    f"{where} — 같은 발주묶음({g['bundle']})에 같은 규격이 이미 있습니다: {spec}"
                )
            exact.add(exact_key)
            suffix = _spec_suffix(spec, g["bundle"])
            suffix_key = (bundle_key, _match_key(suffix))
            owner = suffix_owner.get(suffix_key)
            if owner is not None and owner != g["id"]:
                raise ValueError(
                    f"{where} — 같은 발주묶음({g['bundle']})의 다른 그룹에 접두를 뺀 규격이 "
                    f"이미 있습니다: {suffix}"
                )
            suffix_owner.setdefault(suffix_key, g["id"])


def _validate_order_patterns(value: object) -> dict:
    """관리자 입력 order_patterns 검증 → 정규화 {'groups': [...]}. 위반 시 ValueError(한국어).

    쓰기 경로(PATCH)의 엄격 검증이다 — 읽기 경로의 관대 파서는 order_patterns_for 가 맡는다.
    """
    if not isinstance(value, dict) or not isinstance(value.get("groups"), list):
        raise ValueError('발주 패턴은 {"groups": [...]} 형태여야 합니다.')
    raw_groups = value["groups"]
    if not raw_groups:
        raise ValueError("발주 그룹을 최소 1개 이상 등록하세요.")
    if len(raw_groups) > MAX_PATTERN_GROUPS:
        raise ValueError(f"발주 그룹은 최대 {MAX_PATTERN_GROUPS}개까지 등록할 수 있습니다.")
    groups: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_groups):
        group = _check_group(raw, f"{i + 1}번째 그룹")
        if group["id"] in seen:
            raise ValueError(f"발주 그룹 식별자가 중복됩니다: {group['id']}")
        seen.add(group["id"])
        groups.append(group)
    _check_spec_collisions(groups)
    return {"groups": groups}


def order_patterns_for(stored: dict | None) -> dict:
    """저장된 발주 패턴(유효 그룹만) 또는 기본 9그룹. 실효 설정·직렬화 공용.

    menu_items 와 달리 **그룹 단위 관대** 파서다 — 그룹 하나가 깨졌다고 전체를 버리면 손실이
    크므로 파손 그룹·파손 모듈행·파손 예외행(효과 없는 예외·순환 위반 포함)만 건너뛰고,
    남는 그룹이 0일 때만 기본값으로 폴백한다. v1 의 플랫 배열 저장분도 여기서 기본값이 된다.
    (프론트 orderPatternsFromSettings 와 같은 방침. 다만 길이 상한 초과도 '파손'으로 보는
    점만 다르다 — 쓰기 경로가 막고 있어 정상 경로로는 생기지 않는 값이다.)
    """
    raw = (stored or {}).get(ORDER_PATTERNS_KEY)
    if not isinstance(raw, dict) or not isinstance(raw.get("groups"), list):
        return copy.deepcopy(DEFAULT_ORDER_PATTERNS)
    groups: list[dict] = []
    seen: set[str] = set()
    for i, item in enumerate(raw["groups"][:MAX_PATTERN_GROUPS]):
        try:
            group = _check_group(item, f"{i + 1}번째 그룹", fallback_id=f"_g{i + 1}", lenient=True)
        except ValueError:
            continue
        if group["id"] in seen:
            continue
        seen.add(group["id"])
        groups.append(group)
    return {"groups": groups} if groups else copy.deepcopy(DEFAULT_ORDER_PATTERNS)


# ── 통합 지정 거래처 후보(구매발주) ──────────────────────────────────────────
# 계획서 '통합 지정'과 발주단위 거래처 그룹 콤보박스의 **분류별 후보 목록** — 관리자가
# 추가/삭제한다(menu_items 와 동일 패턴, 2026-08-26 사용자 요청). 종전에는 프론트
# catalog.ts 에 하드코딩돼 있었다(자리표시 코드 V-11xx — ERP 로 나가는 값은 이름뿐이라
# 코드는 저장하지 않는다). 분류 키는 BOM 품목거래처명과 같은 고정 3종이다.
VENDOR_OPTIONS_KEY = "vendor_options"
VENDOR_CLASSES: tuple[str, ...] = ("가공품", "판금품", "주식회사 오텍")
MAX_VENDOR_OPTIONS_PER_CLASS = 30
MAX_VENDOR_NAME_LEN = 60

# ⚠ 프론트 미러: src/lib/purchase/vendor-options.ts 의 DEFAULT_VENDOR_OPTIONS 와 값이
#   같아야 한다(order_patterns 의 기본 9그룹과 같은 이중 리터럴 관례).
DEFAULT_VENDOR_OPTIONS: dict = {
    "가공품": [
        {"name": "우신테크"},
        {"name": "제이테크"},
        {"name": "한국메카트로닉스"},
        {"name": "해룡엔지니어링", "isDefault": True},
    ],
    "판금품": [
        {"name": "알파테크", "isDefault": True},
        {"name": "부성엘티에스"},
        {"name": "브이피시스템"},
        {"name": "이레코리아"},
    ],
    "주식회사 오텍": [
        {"name": "주식회사 오텍", "isDefault": True},
        {"name": "피르스트"},
        {"name": "훈원테크"},
    ],
}


def _validate_vendor_class_rows(vendor_class: str, value: object) -> list[dict]:
    """한 분류의 후보 목록 검증 → 정규화 [{name, isDefault}] . 위반 시 ValueError(한국어).

    최소 1행·최대 MAX, 이름 중복 금지, 기본 거래처는 정확히 1개(누락 시 첫 행으로 보정).
    """
    if not isinstance(value, list) or not value:
        raise ValueError(f"'{vendor_class}' 거래처를 최소 1개 이상 등록하세요.")
    if len(value) > MAX_VENDOR_OPTIONS_PER_CLASS:
        raise ValueError(
            f"'{vendor_class}' 거래처는 최대 {MAX_VENDOR_OPTIONS_PER_CLASS}개까지 등록할 수 있습니다."
        )
    out: list[dict] = []
    seen: set[str] = set()
    default_count = 0
    for i, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"'{vendor_class}' {i + 1}번째 거래처의 형식을 확인하세요.")
        name = str(row.get("name") or "").strip()
        if not name or len(name) > MAX_VENDOR_NAME_LEN:
            raise ValueError(
                f"'{vendor_class}' {i + 1}번째 거래처 이름을 확인하세요(1~{MAX_VENDOR_NAME_LEN}자)."
            )
        is_default = row.get("isDefault", False)
        if not isinstance(is_default, bool):
            raise ValueError(f"'{vendor_class}' {i + 1}번째 거래처의 기본 표시는 불리언이어야 합니다.")
        if name in seen:
            raise ValueError(f"'{vendor_class}' 거래처 이름이 중복됩니다: {name}")
        seen.add(name)
        if is_default:
            default_count += 1
        out.append({"name": name, "isDefault": is_default})
    if default_count > 1:
        raise ValueError(f"'{vendor_class}' 기본 거래처는 1개만 지정할 수 있습니다.")
    if default_count == 0:
        out[0] = {**out[0], "isDefault": True}
    return out


def _validate_vendor_options(value: object) -> dict:
    """관리자 입력 vendor_options 검증 → 정규화 {분류: [{name,isDefault}]}. 위반 시 ValueError.

    분류 키는 고정 3종 전부 필수 — 일부만 보내면 나머지 분류가 비어 계획서가 무너진다.
    """
    if not isinstance(value, dict):
        raise ValueError("거래처 후보 형식을 확인하세요.")
    unknown = [k for k in value if k not in VENDOR_CLASSES]
    if unknown:
        raise ValueError(f"알 수 없는 거래처 분류입니다: {', '.join(unknown)}")
    out: dict = {}
    for vendor_class in VENDOR_CLASSES:
        out[vendor_class] = _validate_vendor_class_rows(vendor_class, value.get(vendor_class))
    return out


def vendor_options_for(stored: dict | None) -> dict:
    """저장된 거래처 후보 또는 기본값. 실효 설정·직렬화 공용.

    **분류 단위 관대** 파서 — 한 분류가 깨져도 나머지는 살리고, 깨진 분류만 기본값으로
    폴백한다(order_patterns 의 그룹 단위 관대와 같은 방침).
    """
    raw = (stored or {}).get(VENDOR_OPTIONS_KEY)
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for vendor_class in VENDOR_CLASSES:
        try:
            out[vendor_class] = _validate_vendor_class_rows(vendor_class, raw.get(vendor_class))
        except ValueError:
            # 기본값도 검증기를 통과시켜 isDefault 누락을 정규화한다(리터럴은 default 만 표기).
            out[vendor_class] = _validate_vendor_class_rows(
                vendor_class, DEFAULT_VENDOR_OPTIONS[vendor_class]
            )
    return out


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
    # purchase-order: 스칼라 설정은 없고 발주 패턴(동적 목록, 위 별도 처리)만 갖는다 —
    # voucher-by-type 과 같은 이유로 빈 스키마([])를 명시해 settings 가 응답에 포함되게 한다.
    "purchase-order": [],
}

# 차량종류(동적 목록) 설정을 갖는 에이전트 — 실효 설정에 fuel_classes 를 포함하고 PATCH 에서
# fuel_classes 목록 입력을 허용한다. 현재는 출장(국내/자차)만.
_AGENTS_WITH_FUEL_CLASSES: frozenset[str] = frozenset({"trip-domestic"})

# 메뉴 항목(동적 목록) 설정을 갖는 에이전트 — 실효 설정에 menu_items 를 포함하고 PATCH 에서
# menu_items 목록 입력을 허용한다. ⚠ **에이전트 id** 기준(workflow id 아님).
_AGENTS_WITH_MENU_ITEMS: frozenset[str] = frozenset({"voucher-by-type"})

# 발주 패턴(동적 목록) 설정을 갖는 에이전트 — 실효 설정에 order_patterns 를 포함하고 PATCH 에서
# order_patterns 목록 입력을 허용한다. ⚠ **에이전트 id** 기준(workflow id 아님).
_AGENTS_WITH_ORDER_PATTERNS: frozenset[str] = frozenset({"purchase-order"})

# 통합 지정 거래처 후보(동적 목록) 설정을 갖는 에이전트 — 실효 설정에 vendor_options 를
# 포함하고 PATCH 에서 vendor_options 입력을 허용한다. ⚠ **에이전트 id** 기준.
_AGENTS_WITH_VENDOR_OPTIONS: frozenset[str] = frozenset({"purchase-order"})


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
    if agent_id in _AGENTS_WITH_ORDER_PATTERNS:
        out[ORDER_PATTERNS_KEY] = order_patterns_for(stored)
    if agent_id in _AGENTS_WITH_VENDOR_OPTIONS:
        out[VENDOR_OPTIONS_KEY] = vendor_options_for(stored)
    return out


def validate_settings(agent_id: str, incoming: dict) -> dict:
    """관리자 PATCH 입력 검증 — 키∈스키마·타입·min/max. 위반 시 ValueError(한국어).

    통과한 키만 담은 새 dict 를 반환한다(원본 불변).
    """
    defs = {d.key: d for d in AGENT_SETTINGS_SCHEMA.get(agent_id, [])}
    has_fuel_classes = agent_id in _AGENTS_WITH_FUEL_CLASSES
    has_menu_items = agent_id in _AGENTS_WITH_MENU_ITEMS
    has_order_patterns = agent_id in _AGENTS_WITH_ORDER_PATTERNS
    has_vendor_options = agent_id in _AGENTS_WITH_VENDOR_OPTIONS
    if (
        not defs
        and not has_fuel_classes
        and not has_menu_items
        and not has_order_patterns
        and not has_vendor_options
    ):
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
        # 발주 패턴(동적 목록) — purchase-order 의 발주 패턴 마스터 목록(동일 패턴).
        if has_order_patterns and key == ORDER_PATTERNS_KEY:
            validated[key] = _validate_order_patterns(value)
            continue
        # 통합 지정 거래처 후보(동적 목록) — purchase-order 계획서 콤보박스 마스터(동일 패턴).
        if has_vendor_options and key == VENDOR_OPTIONS_KEY:
            validated[key] = _validate_vendor_options(value)
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
