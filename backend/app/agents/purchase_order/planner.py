"""구매발주 계획서(planner) 순수 로직 — plannerBom 조립 + 계획 제출 검증(브라우저 무관).

plannerBom 은 프론트 데모 픽스처(src/lib/data/purchase-order-bom.json)와 **동일 shape** 다
(공유 계약) — 프론트 LivePlannerCard 가 데모 모델을 그대로 먹는다:
  {"project": {"code","name","wbs"},
   "machines": [{"itemCode","name","spec","unit","modules": [{"itemCode","name","spec","unit",
     "bomQty","parts": [{"itemCode","name","spec","unit","bomQty","remainQty","unitPrice",
     "amount","vendorClass","account","purchasable"}]}]}]}

레벨 매핑(트리그리드 getLevel, 0-idx — 프로브 실측 2026-08-13):
  0=프로젝트 / 1=장비(machine) / 2=모듈(구조행 — 계층 접힘, machine 아래로 평탄화) /
  3=SET(module, 발주단위 선택 단위) / 4=부품(part, 리프).
"""

from __future__ import annotations

from typing import Any

# 의사 거래처(실거래처 미정 분류) — 프론트 model.ts PSEUDO_VENDOR_CLASSES 미러(가공품 → 판금품
# 순서 포함). 계획 제출 검증에서 "미지정 의사 거래처 없음" 판정의 단일 기준.
PSEUDO_VENDOR_CLASSES: tuple[str, ...] = ("가공품", "판금품")

# plannerBom 키 → 트리그리드 fieldName 후보(첫 비어있지 않은 값 채택).
# ✅ 확정(프로브/화면 플랫 그리드 실측): ITEM_CD·ITEM_NM·ITEM_SPEC_DC·RMND_QT·PUR_FG·WBS_NM.
# ❓ 후보(42열 fieldName 전수 덤프 전 — 쓰기 프로브에서 확정 시 이 튜플만 갱신하면 된다):
#    unit·bomQty·unitPrice·amount·vendorClass·account. 미해석 필드는 ''/0 으로 조립된다
#    (shape 불변 — 프론트가 빈 값으로 안전 렌더).
FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "itemCode": ("ITEM_CD",),
    "name": ("ITEM_NM",),
    "spec": ("ITEM_SPEC_DC", "ITEM_SPEC"),
    "unit": ("UNIT_DC", "UNIT_CD", "UNIT_NM", "QT_UNIT_DC"),
    "bomQty": ("BOM_QT", "BOM_USE_QT"),
    "remainQty": ("RMND_QT",),
    "unitPrice": ("UNTPC", "UNIT_PRC", "PUR_UNTPC"),
    "amount": ("AMT", "PUR_AMT", "SUM_AMT"),
    "vendorClass": ("VEND_NM", "PARTNER_NM", "CUST_NM"),
    "account": ("ACCT_NM", "ACCOUNT_NM", "ACCT_DC"),
    "purchasable": ("PUR_FG", "PUR_OBJ_FG"),
    "wbs": ("WBS_NM",),
}

# TREEGRID_READ_JS 에 넘길 읽기 대상 필드(후보 전체 합집합 — 순서 고정으로 재현성 확보).
READ_FIELDS: list[str] = sorted({f for cands in FIELD_CANDIDATES.values() for f in cands})

LEVEL_MACHINE = 1
LEVEL_MODULE = 3  # SET — 발주단위 선택 단위
LEVEL_PART = 4  # 리프


def _pick(row: dict, key: str) -> Any:
    """행에서 key 의 fieldName 후보를 순서대로 보고 첫 비어있지 않은 값을 돌려준다."""
    for f in FIELD_CANDIDATES[key]:
        v = row.get(f)
        if v is not None and str(v).strip() not in ("", "null"):
            return v
    return None


def _text(row: dict, key: str) -> str:
    v = _pick(row, key)
    return "" if v is None else str(v).strip()


def _num(row: dict, key: str) -> float | int:
    """수량/단가/금액 — ERP 표시값('1,234' 등) 관용 파싱. 미해석은 0.

    ⚠ 파생 계산 없음(읽은 값 그대로) — 금액 파생이 생기면 Decimal+ROUND_HALF_UP 규율 적용 대상.
    """
    v = _pick(row, key)
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else float(v)
    s = str(v).replace(",", "").strip()
    if not s:
        return 0
    try:
        f = float(s)
    except ValueError:
        return 0
    return int(f) if f.is_integer() else f


def _bool_yn(row: dict, key: str, *, default: bool = True) -> bool:
    """Y/N 플래그 — 명시적 'N' 만 False(필드 미확정/공백은 default)."""
    v = _pick(row, key)
    if v is None:
        return default
    return str(v).strip().upper() != "N"


def assemble_planner_bom(rows: list[dict], project: dict) -> dict:
    """트리그리드 행(level+fields) → plannerBom(공유 계약 shape).

    rows 는 TREEGRID_READ_JS 반환의 rows(그리드 표시 순서 — 계층 순서 보존). 레벨 0(프로젝트)·
    2(구조행)는 건너뛰고, 3(SET)은 가장 최근 레벨 1(machine) 아래로 평탄화한다. 계층이 깨진
    행(machine 없는 module, module 없는 part)은 버린다 — 조립을 죽이는 것보다 낫고, 요약
    카운트로 드러난다.
    """
    machines: list[dict] = []
    cur_machine: dict | None = None
    cur_module: dict | None = None
    wbs = str(project.get("wbs") or "").strip()

    for row in rows:
        level = row.get("level")
        if not wbs:
            wbs = _text(row, "wbs")
        if level == LEVEL_MACHINE:
            cur_machine = {
                "itemCode": _text(row, "itemCode"),
                "name": _text(row, "name"),
                "spec": _text(row, "spec"),
                "unit": _text(row, "unit"),
                "modules": [],
            }
            cur_module = None
            machines.append(cur_machine)
        elif level == LEVEL_MODULE:
            if cur_machine is None:
                cur_module = None
                continue
            cur_module = {
                "itemCode": _text(row, "itemCode"),
                "name": _text(row, "name"),
                "spec": _text(row, "spec"),
                "unit": _text(row, "unit"),
                "bomQty": _num(row, "bomQty"),
                "parts": [],
            }
            cur_machine["modules"].append(cur_module)
        elif level == LEVEL_PART:
            if cur_module is None:
                continue
            cur_module["parts"].append(
                {
                    "itemCode": _text(row, "itemCode"),
                    "name": _text(row, "name"),
                    "spec": _text(row, "spec"),
                    "unit": _text(row, "unit"),
                    "bomQty": _num(row, "bomQty"),
                    "remainQty": _num(row, "remainQty"),
                    "unitPrice": _num(row, "unitPrice"),
                    "amount": _num(row, "amount"),
                    "vendorClass": _text(row, "vendorClass"),
                    "account": _text(row, "account"),
                    "purchasable": _bool_yn(row, "purchasable"),
                }
            )
        # level 0(프로젝트)·2(구조행)·미상(-1)은 조립 대상 아님.

    return {
        "project": {
            "code": str(project.get("code") or ""),
            "name": str(project.get("name") or ""),
            "wbs": wbs,
        },
        "machines": machines,
    }


def summarize_bom(planner_bom: dict, total_rows: int) -> dict:
    """result 용 행수 요약 — 그리드 원행수 + 조립된 machine/module/part 수."""
    machines = planner_bom.get("machines") or []
    modules = [m for mc in machines for m in (mc.get("modules") or [])]
    parts = [p for m in modules for p in (m.get("parts") or [])]
    return {
        "gridRows": total_rows,
        "machines": len(machines),
        "modules": len(modules),
        "parts": len(parts),
        "purchasableParts": sum(1 for p in parts if p.get("purchasable")),
    }


def validate_plan(plan: Any) -> tuple[bool, str]:
    """계획 제출 payload 경량 검증(서버측) — (ok, 위반 사유).

    규칙(HITL 통합 설계 확정분): ① units ≥ 1, ② 각 unit 에 purchaseReason·dueDate,
    ③ 미지정 의사 거래처 없음(가공품·판금품 그룹은 실거래처 vendor 필수).
    구조 상한(units≤50 등)은 runs.py Pydantic(PlanIn)이 경계에서 이미 강제한다.
    """
    if not isinstance(plan, dict):
        return False, "계획 형식이 올바르지 않습니다."
    units = plan.get("units")
    if not isinstance(units, list) or len(units) < 1:
        return False, "발주단위가 없습니다 — 최소 1개 발주단위를 구성해 주세요."
    for unit in units:
        seq = unit.get("seq")
        if not str(unit.get("purchaseReason") or "").strip():
            return False, f"발주단위 {seq}에 구매사유가 없습니다."
        if not str(unit.get("dueDate") or "").strip():
            return False, f"발주단위 {seq}에 납기예정일이 없습니다."
        for g in unit.get("vendorGroups") or []:
            v_class = str(g.get("vendorClass") or "")
            if v_class in PSEUDO_VENDOR_CLASSES and not str(g.get("vendor") or "").strip():
                return False, (
                    f"발주단위 {seq}의 '{v_class}' 그룹에 실거래처가 지정되지 않았습니다."
                )
    return True, ""
